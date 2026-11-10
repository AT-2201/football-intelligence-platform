"""Leakage-safe historical game-day forecasts and contingency planning."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from football_intelligence.models import (
    Event,
    Lineup,
    Match,
    Player,
    PlayerMatchStat,
    Team,
    TeamMatchStat,
)


def _round(value: float, digits: int = 1) -> float:
    return round(float(value or 0), digits)


def _formation_label(value: Any) -> str:
    digits = str(value or "")
    return "-".join(digits) if digits.isdigit() else "Unknown"


def _position_group(position: str | None) -> str:
    name = (position or "").lower()
    if "goalkeeper" in name:
        return "Goalkeeper"
    if "back" in name and "center" in name:
        return "Centre Back"
    if "back" in name:
        return "Full Back"
    if "defensive midfield" in name:
        return "Defensive Midfielder"
    if "wing" in name or "left midfield" in name or "right midfield" in name:
        return "Wide Player"
    if "midfield" in name:
        return "Central Midfielder"
    if "forward" in name:
        return "Forward"
    return "Other"


def _starting_lineup(event: Event | None) -> list[dict[str, Any]]:
    tactics = ((event.raw_data if event else {}) or {}).get("tactics") or {}
    return [
        {
            "player_id": item.get("player", {}).get("id"),
            "player_name": item.get("player", {}).get("name", "Unknown player"),
            "position": item.get("position", {}).get("name", "Unknown"),
        }
        for item in tactics.get("lineup") or []
        if item.get("player", {}).get("id") is not None
    ]


def _result(match: Match, team_id: int) -> str:
    goals_for = match.home_score if match.home_team_id == team_id else match.away_score
    goals_against = match.away_score if match.home_team_id == team_id else match.home_score
    return "W" if goals_for > goals_against else "D" if goals_for == goals_against else "L"


def _points_table(matches: list[Match], team_names: dict[int, str]) -> list[dict[str, Any]]:
    table = {
        team_id: {"team_id": team_id, "team_name": name, "points": 0, "gf": 0, "ga": 0}
        for team_id, name in team_names.items()
    }
    for match in matches:
        home, away = table[match.home_team_id], table[match.away_team_id]
        home["gf"] += match.home_score
        home["ga"] += match.away_score
        away["gf"] += match.away_score
        away["ga"] += match.home_score
        if match.home_score > match.away_score:
            home["points"] += 3
        elif match.home_score < match.away_score:
            away["points"] += 3
        else:
            home["points"] += 1
            away["points"] += 1
    rows = list(table.values())
    for row in rows:
        row["goal_difference"] = row["gf"] - row["ga"]
    rows.sort(key=lambda row: (row["points"], row["goal_difference"], row["gf"]), reverse=True)
    for index, row in enumerate(rows, 1):
        row["position"] = index
    return rows


def _importance(
    target: Match,
    earlier_matches: list[Match],
    team_id: int,
    opponent_id: int,
    team_names: dict[int, str],
) -> dict[str, Any]:
    table = _points_table(earlier_matches, team_names)
    by_team = {row["team_id"]: row for row in table}
    team_row, opponent_row = by_team[team_id], by_team[opponent_id]
    position_gap = abs(team_row["position"] - opponent_row["position"])
    direct_rival = position_gap <= 3
    boundary_gap = min(
        abs(team_row["position"] - boundary) for boundary in (1, 4, 17, 18)
    )
    late_season = (target.match_week or 1) / 38
    score = 25 + late_season * 35 + (20 if direct_rival else 0) + (20 if boundary_gap <= 1 else 0)
    score = min(100, round(score))
    label = "High" if score >= 70 else "Elevated" if score >= 50 else "Standard"
    reasons = [
        f"Matchweek {target.match_week} with "
        f"{39 - (target.match_week or 1)} games remaining."
    ]
    if direct_rival:
        reasons.append(
            f"The clubs entered the match only {position_gap} league positions apart."
        )
    if boundary_gap <= 1:
        reasons.append("The club was close to a major league-table boundary.")
    return {
        "label": label,
        "score": score,
        "team_position": team_row["position"],
        "team_points": team_row["points"],
        "opponent_position": opponent_row["position"],
        "opponent_points": opponent_row["points"],
        "direct_rival": direct_rival,
        "reasons": reasons,
        "method": "Transparent table-leverage proxy; not a psychological measurement.",
    }


def _opponent_profile(
    target: Match,
    opponent_id: int,
    all_matches: list[Match],
    stats: dict[tuple[int, int], Any],
    team_names: dict[int, str],
) -> dict[str, Any]:
    prior = [
        match
        for match in all_matches
        if match.match_date < target.match_date
        and opponent_id in (match.home_team_id, match.away_team_id)
    ][-5:]
    own_stats = [stats.get((match.match_id, opponent_id)) for match in prior]
    own_stats = [row for row in own_stats if row]
    against_stats = []
    for match in prior:
        other_id = match.away_team_id if match.home_team_id == opponent_id else match.home_team_id
        row = stats.get((match.match_id, other_id))
        if row:
            against_stats.append(row)
    def average(rows: list[Any], attribute: str) -> float:
        return _round(mean(getattr(row, attribute) for row in rows), 1) if rows else 0

    possession = average(own_stats, "possession_pct")
    pass_completion = _round(
        100
        * sum(row.completed_passes for row in own_stats)
        / max(sum(row.passes for row in own_stats), 1),
        1,
    )
    shots = average(own_stats, "shots")
    xg = average(own_stats, "xg")
    xg_against = average(against_stats, "xg")
    strengths = []
    weaknesses = []
    if possession >= 55:
        strengths.append(
            "Regularly controls possession and makes opponents defend for longer spells."
        )
    elif possession <= 45:
        strengths.append("Comfortable attacking without long possession spells.")
    if shots >= 13:
        strengths.append("Creates a high volume of shots in recent matches.")
    if pass_completion >= 80:
        strengths.append("Retains the ball reliably through its passing structure.")
    if xg >= 1.5:
        strengths.append("Recent chance quality has been above the league's typical match level.")
    if xg_against >= 1.5:
        weaknesses.append("Has recently allowed opponents a meaningful expected-goals total.")
    if possession >= 55 and xg < 1.25:
        weaknesses.append("Possession has not consistently become high-quality chances.")
    if shots < 10:
        weaknesses.append("Recent attacking volume has been relatively limited.")
    if not strengths:
        strengths.append("Recent output is balanced without one dominant statistical tendency.")
    if not weaknesses:
        weaknesses.append(
            "No major five-match weakness is visible in the available baseline metrics."
        )
    form = "".join(_result(match, opponent_id) for match in prior)
    return {
        "team_id": opponent_id,
        "team_name": team_names[opponent_id],
        "matches_used": len(prior),
        "recent_form": form,
        "metrics": {
            "possession_pct": possession,
            "pass_completion_pct": pass_completion,
            "shots_per_match": shots,
            "xg_per_match": xg,
            "xg_against_per_match": xg_against,
        },
        "strengths": strengths[:3],
        "weaknesses": weaknesses[:3],
    }


def _match_score_state(
    match_id: int,
    team_id: int,
    event_index: int,
    goal_events: dict[int, list[Event]],
) -> str:
    own = sum(
        1
        for event in goal_events.get(match_id, [])
        if event.event_index < event_index and event.team_id == team_id
    )
    against = sum(
        1
        for event in goal_events.get(match_id, [])
        if event.event_index < event_index and event.team_id != team_id
    )
    return "leading" if own > against else "trailing" if own < against else "level"


def _forecast_substitutions(
    prior_match_ids: list[int],
    predicted_ids: set[int],
    candidate_ids: set[int],
    substitutions: dict[int, list[Event]],
    goals: dict[int, list[Event]],
    team_id: int,
    player_names: dict[int, str],
    player_positions: dict[int, str],
) -> dict[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    total_matches = len(prior_match_ids)
    for match_index, match_id in enumerate(prior_match_ids):
        recency = 0.78 ** (total_matches - match_index - 1)
        for event in substitutions.get(match_id, []):
            replacement = (
                ((event.raw_data or {}).get("substitution") or {}).get("replacement") or {}
            )
            on_id = replacement.get("id")
            if event.player_id is None or on_id is None:
                continue
            rows.append(
                {
                    "off_id": event.player_id,
                    "on_id": on_id,
                    "minute": event.minute,
                    "state": _match_score_state(
                        match_id, team_id, event.event_index, goals
                    ),
                    "weight": recency,
                }
            )

    output: dict[str, list[dict[str, Any]]] = {}
    for scenario in ("leading", "level", "trailing"):
        scenario_rows = [row for row in rows if row["state"] == scenario] or rows
        pairs: dict[tuple[int, int], dict[str, float]] = defaultdict(
            lambda: {"weight": 0, "minutes": 0}
        )
        for row in scenario_rows:
            if row["off_id"] not in predicted_ids:
                continue
            if row["on_id"] in predicted_ids or row["on_id"] not in candidate_ids:
                continue
            pair = pairs[(row["off_id"], row["on_id"])]
            pair["weight"] += row["weight"]
            pair["minutes"] += row["minute"] * row["weight"]
        ranked = sorted(pairs.items(), key=lambda item: item[1]["weight"], reverse=True)
        total_weight = sum(item[1]["weight"] for item in ranked) or 1
        forecasts = []
        for (off_id, on_id), values in ranked[:5]:
            minute = round(values["minutes"] / values["weight"])
            off_group = _position_group(player_positions.get(off_id))
            on_group = _position_group(player_positions.get(on_id))
            if scenario == "leading":
                reason = "Protect the result, refresh defensive work or preserve the team shape."
            elif scenario == "trailing":
                reason = "Increase attacking threat or change the profile of the forward line."
            elif off_group == on_group:
                reason = "A like-for-like role refresh based on the manager's earlier changes."
            else:
                reason = "A structural change seen in the manager's earlier substitution patterns."
            forecasts.append(
                {
                    "off_player_id": off_id,
                    "off_player_name": player_names.get(off_id, "Unknown player"),
                    "on_player_id": on_id,
                    "on_player_name": player_names.get(on_id, replacement_name(on_id, rows)),
                    "probability": _round(100 * values["weight"] / total_weight, 1),
                    "minute_from": max(45, minute - 8),
                    "minute_to": min(90, minute + 8),
                    "reason": reason,
                }
            )
        output[scenario] = forecasts
    return output


def replacement_name(player_id: int, _: list[dict[str, Any]]) -> str:
    return f"Player {player_id}"


def _discipline_status(
    prior_matches: list[Match],
    lineups_by_match: dict[int, list[Lineup]],
) -> tuple[set[int], dict[int, dict[str, Any]]]:
    inferred_unavailable: set[int] = set()
    details: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"yellow_cards": 0, "red_cards": 0, "status": "Available"}
    )
    for match in prior_matches:
        for row in lineups_by_match.get(match.match_id, []):
            for card in row.cards or []:
                card_type = card.get("card_type")
                if card_type == "Yellow Card":
                    details[row.player_id]["yellow_cards"] += 1
                elif card_type in {"Red Card", "Second Yellow"}:
                    details[row.player_id]["red_cards"] += 1
                    if match.match_id == prior_matches[-1].match_id:
                        inferred_unavailable.add(row.player_id)
                        details[row.player_id]["status"] = "Inferred suspension"
    for item in details.values():
        if item["status"] == "Available" and item["yellow_cards"] >= 4:
            item["status"] = "Disciplinary watch"
    return inferred_unavailable, details


def _build_plan(
    target: Match,
    team_id: int,
    all_matches: list[Match],
    team_matches: list[Match],
    starting_events: dict[int, Event],
    lineups_by_match: dict[int, list[Lineup]],
    player_stats: dict[tuple[int, int], PlayerMatchStat],
    substitutions: dict[int, list[Event]],
    goals: dict[int, list[Event]],
    team_stats: dict[tuple[int, int], Any],
    player_names: dict[int, str],
    team_names: dict[int, str],
) -> dict[str, Any]:
    prior_matches = [match for match in team_matches if match.match_date < target.match_date]
    opponent_id = target.away_team_id if target.home_team_id == team_id else target.home_team_id
    formation_history = []
    for match in prior_matches:
        event = starting_events.get(match.match_id)
        lineup = _starting_lineup(event)
        formation_history.append(
            {
                "match": match,
                "formation": _formation_label(
                    ((event.raw_data or {}).get("tactics") or {}).get("formation")
                )
                if event
                else "Unknown",
                "lineup": lineup,
            }
        )

    formation_scores: Counter[str] = Counter()
    for index, row in enumerate(formation_history):
        distance = len(formation_history) - index - 1
        weight = 0.74**distance
        same_venue = (row["match"].home_team_id == team_id) == (target.home_team_id == team_id)
        formation_scores[row["formation"]] += weight * (1.12 if same_venue else 1)
    total_formation = sum(formation_scores.values()) or 1
    formation_probabilities = [
        {"formation": formation, "probability": _round(100 * value / total_formation, 1)}
        for formation, value in formation_scores.most_common(3)
    ]
    predicted_formation = formation_probabilities[0]["formation"]
    template = next(
        (
            row["lineup"]
            for row in reversed(formation_history)
            if row["formation"] == predicted_formation
        ),
        formation_history[-1]["lineup"],
    )
    slots = [row["position"] for row in template]

    recent = prior_matches[-5:]
    weights = {
        match.match_id: 0.68 ** (len(recent) - index - 1)
        for index, match in enumerate(recent)
    }
    total_weight = sum(weights.values()) or 1
    start_weight: Counter[int] = Counter()
    position_weight: dict[int, Counter[str]] = defaultdict(Counter)
    last_started: set[int] = set()
    for row in formation_history:
        for player in row["lineup"]:
            position_weight[player["player_id"]][player["position"]] += 1
    for row in formation_history[-5:]:
        match_weight = weights.get(row["match"].match_id, 0)
        for player in row["lineup"]:
            start_weight[player["player_id"]] += match_weight
        if row is formation_history[-1]:
            last_started = {player["player_id"] for player in row["lineup"]}

    candidate_ids: set[int] = set()
    for match in recent:
        candidate_ids.update(row.player_id for row in lineups_by_match.get(match.match_id, []))
    candidate_ids.update(start_weight)
    inferred_unavailable, discipline = _discipline_status(prior_matches, lineups_by_match)
    candidate_ids -= inferred_unavailable

    candidate_rows = []
    primary_positions: dict[int, str] = {}
    for player_id in candidate_ids:
        position = (
            position_weight[player_id].most_common(1)[0][0]
            if position_weight[player_id]
            else "Unknown"
        )
        primary_positions[player_id] = position
        recent_rows = [
            player_stats.get((match.match_id, player_id)) for match in recent
        ]
        minutes = sum(row.minutes for row in recent_rows if row)
        xg = sum(row.xg for row in recent_rows if row)
        goals_scored = sum(row.goals for row in recent_rows if row)
        recent_start_rate = start_weight[player_id] / total_weight
        workload = min(1, minutes / 450)
        form_signal = min(1, (xg + goals_scored * 0.6) / 3)
        score = (
            48 * recent_start_rate
            + 18 * int(player_id in last_started)
            + 18 * workload
            + 8 * form_signal
        )
        probability = max(5, min(97, round(12 + score)))
        reasons = []
        if player_id in last_started:
            reasons.append("Started the club's previous league match.")
        reasons.append(
            f"Started {round(recent_start_rate * 5)} of the weighted "
            "last five match equivalents."
        )
        if minutes >= 360:
            reasons.append("Completed a high share of the available recent minutes.")
        if discipline[player_id]["status"] != "Available":
            reasons.append(discipline[player_id]["status"] + " based on league cards.")
        candidate_rows.append(
            {
                "player_id": player_id,
                "player_name": player_names.get(player_id, f"Player {player_id}"),
                "primary_position": position,
                "position_group": _position_group(position),
                "position_groups": sorted(
                    {_position_group(item) for item in position_weight[player_id]}
                ),
                "start_probability": probability,
                "recent_starts_weighted": _round(recent_start_rate * 5, 1),
                "recent_minutes": _round(minutes, 0),
                "recent_xg": _round(xg, 2),
                "recent_goals": goals_scored,
                "discipline": discipline[player_id],
                "reasons": reasons[:3],
            }
        )

    fallback_groups = {
        "Centre Back": {"Centre Back", "Full Back"},
        "Full Back": {"Full Back", "Centre Back", "Wide Player"},
        "Defensive Midfielder": {"Defensive Midfielder", "Central Midfielder"},
        "Central Midfielder": {"Central Midfielder", "Defensive Midfielder"},
        "Wide Player": {"Wide Player", "Full Back", "Forward"},
        "Forward": {"Forward", "Wide Player"},
    }

    def candidates_for_slot(slot: str, excluded: set[int]) -> list[dict[str, Any]]:
        slot_group = _position_group(slot)
        available = [row for row in candidate_rows if row["player_id"] not in excluded]
        if slot_group == "Goalkeeper":
            return [row for row in available if row["position_group"] == "Goalkeeper"]
        available = [row for row in available if row["position_group"] != "Goalkeeper"]
        experienced = [row for row in available if slot_group in row["position_groups"]]
        if experienced:
            return experienced
        plausible = [
            row
            for row in available
            if row["position_group"] in fallback_groups.get(slot_group, {slot_group})
        ]
        return plausible or available

    slot_order = sorted(
        enumerate(slots),
        key=lambda item: (
            0
            if any(
                _position_group(item[1]) in row["position_groups"]
                for row in candidate_rows
            )
            else 1,
            len(candidates_for_slot(item[1], set())),
        ),
    )
    chosen_by_slot: dict[int, dict[str, Any]] = {}
    used: set[int] = set()
    for slot_index, slot in slot_order:
        slot_group = _position_group(slot)
        eligible = candidates_for_slot(slot, used)
        if not eligible:
            continue
        def fit_score(
            row: dict[str, Any], target_slot: str = slot, target_group: str = slot_group
        ) -> float:
            exact = 20 if row["primary_position"] == target_slot else 0
            same_group = 13 if row["position_group"] == target_group else 0
            return row["start_probability"] + exact + same_group

        selected = max(eligible, key=fit_score)
        used.add(selected["player_id"])
        chosen_by_slot[slot_index] = {**selected, "predicted_position": slot}
    chosen = [chosen_by_slot[index] for index in range(len(slots)) if index in chosen_by_slot]
    if len(chosen) < 11:
        for row in sorted(candidate_rows, key=lambda item: item["start_probability"], reverse=True):
            if row["player_id"] in used:
                continue
            chosen.append({**row, "predicted_position": row["primary_position"]})
            used.add(row["player_id"])
            if len(chosen) == 11:
                break

    bench = [
        row
        for row in sorted(candidate_rows, key=lambda item: item["start_probability"], reverse=True)
        if row["player_id"] not in used
    ][:9]
    actual_lineup = _starting_lineup(starting_events.get(target.match_id))
    actual_ids = {row["player_id"] for row in actual_lineup}
    predicted_ids = {row["player_id"] for row in chosen}
    actual_event = starting_events.get(target.match_id)
    actual_formation = _formation_label(
        ((actual_event.raw_data or {}).get("tactics") or {}).get("formation")
    ) if actual_event else "Unknown"
    substitution_forecast = _forecast_substitutions(
        [match.match_id for match in prior_matches],
        predicted_ids,
        {row["player_id"] for row in candidate_rows},
        substitutions,
        goals,
        team_id,
        player_names,
        primary_positions,
    )
    target_subs = substitutions.get(target.match_id, [])
    actual_off_ids = {event.player_id for event in target_subs if event.player_id}
    actual_on_ids = {
        (((event.raw_data or {}).get("substitution") or {}).get("replacement") or {}).get("id")
        for event in target_subs
    }
    actual_on_ids.discard(None)
    default_forecasts = substitution_forecast["level"][:3]
    predicted_off = {row["off_player_id"] for row in default_forecasts}
    predicted_on = {row["on_player_id"] for row in default_forecasts}
    venue = "Home" if target.home_team_id == team_id else "Away"
    recent_form = "".join(_result(match, team_id) for match in recent)
    opponent = _opponent_profile(target, opponent_id, all_matches, team_stats, team_names)
    matchup_notes = []
    if opponent["metrics"]["possession_pct"] >= 55:
        matchup_notes.append(
            "Prepare a compact out-of-possession structure and clear counterattacking outlets."
        )
    if opponent["metrics"]["xg_against_per_match"] >= 1.5:
        matchup_notes.append(
            "There is evidence to attack assertively rather than only protecting against "
            "their strengths."
        )
    if opponent["metrics"]["pass_completion_pct"] >= 80:
        matchup_notes.append(
            "Pressing triggers should be selective; uncoordinated pressure may be played through."
        )
    if not matchup_notes:
        matchup_notes.append(
            "Use the preferred recent structure while monitoring the opponent's "
            "first-phase build-up."
        )
    prior_reds = sum(
        1
        for match in prior_matches
        for lineup in lineups_by_match.get(match.match_id, [])
        for card in lineup.cards or []
        if card.get("card_type") in {"Red Card", "Second Yellow"}
    )
    return {
        "fixture": {
            "match_id": target.match_id,
            "match_week": target.match_week,
            "date": str(target.match_date),
            "venue": venue,
            "team_id": team_id,
            "team_name": team_names[team_id],
            "opponent_id": opponent_id,
            "opponent_name": team_names[opponent_id],
        },
        "training_window": {
            "prior_matches": len(prior_matches),
            "recent_matches": len(recent),
            "cutoff_date": str(prior_matches[-1].match_date),
            "leakage_safe": True,
        },
        "recent_form": recent_form,
        "formation_forecast": {
            "predicted": predicted_formation,
            "probabilities": formation_probabilities,
            "actual_for_validation": actual_formation,
        },
        "predicted_xi": chosen,
        "bench_candidates": bench,
        "candidate_pool": sorted(
            candidate_rows, key=lambda item: item["start_probability"], reverse=True
        ),
        "availability": {
            "inferred_unavailable_player_ids": sorted(inferred_unavailable),
            "note": (
                "Red-card absences are inferred from the previous league match. Injuries, "
                "illness, cup bans and training information are not in Open Data and remain "
                "user inputs."
            ),
        },
        "opponent": opponent,
        "matchup_notes": matchup_notes,
        "importance": _importance(
            target,
            [match for match in all_matches if match.match_date < target.match_date],
            team_id,
            opponent_id,
            team_names,
        ),
        "substitution_forecast": substitution_forecast,
        "red_card_contingency": {
            "historical_team_send_offs_before_match": prior_reds,
            "supported_positions": ["Goalkeeper", "Defender", "Midfielder", "Forward"],
            "note": (
                "This is a conditional response planner, not an attempt to predict who will "
                "be sent off."
            ),
        },
        "validation": {
            "actual_starters": actual_lineup,
            "correct_starters": len(predicted_ids & actual_ids),
            "formation_correct": predicted_formation == actual_formation,
            "substitute_off_top3_hit": bool(actual_off_ids & predicted_off),
            "substitute_on_top3_hit": bool(actual_on_ids & predicted_on),
        },
    }


def build_game_day_workspace(
    db: Session,
    team_id: int,
    competition_id: int,
    season_id: int,
) -> dict[str, Any] | None:
    """Build all chronologically valid forecasts for one club from matchweek six onward."""
    team = db.get(Team, team_id)
    if not team:
        return None
    all_matches = list(
        db.scalars(
            select(Match)
            .where(Match.competition_id == competition_id, Match.season_id == season_id)
            .order_by(Match.match_date, Match.match_id)
        )
    )
    team_matches = [
        match for match in all_matches if team_id in (match.home_team_id, match.away_team_id)
    ]
    match_ids = [match.match_id for match in team_matches]
    starting_events = {
        event.match_id: event
        for event in db.scalars(
            select(Event).where(
                Event.match_id.in_(match_ids),
                Event.team_id == team_id,
                Event.type_name == "Starting XI",
            )
        )
    }
    lineups_by_match: dict[int, list[Lineup]] = defaultdict(list)
    for row in db.scalars(
        select(Lineup).where(Lineup.match_id.in_(match_ids), Lineup.team_id == team_id)
    ):
        lineups_by_match[row.match_id].append(row)
    player_stats = {
        (row.match_id, row.player_id): row
        for row in db.scalars(
            select(PlayerMatchStat).where(
                PlayerMatchStat.match_id.in_(match_ids), PlayerMatchStat.team_id == team_id
            )
        )
    }
    event_rows = list(
        db.scalars(
            select(Event).where(
                Event.match_id.in_(match_ids),
                or_(
                    Event.type_name == "Substitution",
                    (Event.type_name == "Shot") & (Event.shot_outcome_name == "Goal"),
                ),
            )
        )
    )
    substitutions: dict[int, list[Event]] = defaultdict(list)
    goals: dict[int, list[Event]] = defaultdict(list)
    for event in event_rows:
        if event.type_name == "Substitution" and event.team_id == team_id:
            substitutions[event.match_id].append(event)
        elif event.type_name == "Shot" and event.shot_outcome_name == "Goal":
            goals[event.match_id].append(event)

    team_stats = {
        (row.match_id, row.team_id): row
        for row in db.scalars(
            select(TeamMatchStat).where(
                TeamMatchStat.competition_id == competition_id,
                TeamMatchStat.season_id == season_id,
            )
        )
    }
    team_names = {
        row.team_id: row.team_name
        for row in db.scalars(select(Team).where(Team.team_id.in_({
            item for match in all_matches for item in (match.home_team_id, match.away_team_id)
        })))
    }
    player_ids = {row.player_id for rows in lineups_by_match.values() for row in rows}
    player_names = {
        row.player_id: row.player_name
        for row in db.scalars(select(Player).where(Player.player_id.in_(player_ids)))
    }
    eligible_targets = team_matches[5:]
    plans = [
        _build_plan(
            target,
            team_id,
            all_matches,
            team_matches,
            starting_events,
            lineups_by_match,
            player_stats,
            substitutions,
            goals,
            team_stats,
            player_names,
            team_names,
        )
        for target in eligible_targets
    ]
    plan_count = len(plans) or 1
    backtest = {
        "fixtures": len(plans),
        "formation_accuracy_pct": _round(
            100 * sum(plan["validation"]["formation_correct"] for plan in plans) / plan_count,
            1,
        ),
        "average_correct_starters": _round(
            sum(plan["validation"]["correct_starters"] for plan in plans) / plan_count, 2
        ),
        "substitute_off_top3_accuracy_pct": _round(
            100
            * sum(plan["validation"]["substitute_off_top3_hit"] for plan in plans)
            / plan_count,
            1,
        ),
        "substitute_on_top3_accuracy_pct": _round(
            100
            * sum(plan["validation"]["substitute_on_top3_hit"] for plan in plans)
            / plan_count,
            1,
        ),
        "method": (
            "Walk-forward backtest: every forecast uses only matches before the selected "
            "fixture."
        ),
    }
    return {
        "team": {"team_id": team_id, "team_name": team.team_name},
        "plans": plans,
        "backtest": backtest,
        "model": {
            "name": "Explainable Game Day Forecast v1",
            "formation": "Recency-weighted formation frequency with a home/away adjustment.",
            "lineup": (
                "Recent starts, previous-XI continuity, minutes, form and position "
                "compatibility, constrained to eleven players."
            ),
            "substitutions": (
                "Manager-specific historical replacement pairs, conditioned on leading, "
                "level or trailing score states."
            ),
            "scope": (
                "Premier League 2015/16 only; no injuries, training data, live bans or cup "
                "matches."
            ),
        },
    }
