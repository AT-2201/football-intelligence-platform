"""Club-level tactical and spatial analysis for one competition-season.

The metrics in this module are deliberately transparent.  They are simple,
reproducible descriptions of StatsBomb events rather than opaque scores, so a
portfolio visitor can understand exactly what each number means.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from math import ceil
from statistics import mean
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from football_intelligence.models import Event, Match, Team, TeamMatchStat, TeamSeasonStat

DEFENSIVE_EVENTS = {"Pressure", "Ball Recovery", "Duel", "Interception", "Block", "Clearance"}
POSSESSION_EVENTS = {"Pass", "Carry", "Shot", "Dribble"}
SET_PIECE_PATTERNS = {"From Corner", "From Free Kick"}


def _round(value: float | int | None, digits: int = 1) -> float:
    return round(float(value or 0), digits)


def _pct(numerator: float, denominator: float) -> float:
    return _round(100 * numerator / denominator, 1) if denominator else 0.0


def _per_match(value: float, matches: int) -> float:
    return _round(value / matches, 2) if matches else 0.0


def _sample(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Return an even, deterministic sample while retaining season-wide coverage."""
    if len(items) <= limit:
        return items
    step = ceil(len(items) / limit)
    return items[::step][:limit]


def _formation_label(value: Any) -> str:
    digits = str(value or "")
    return "-".join(digits) if digits.isdigit() else "Unknown"


def _style_labels(metrics: dict[str, float]) -> list[str]:
    labels: list[str] = []
    possession = metrics["average_possession_pct"]
    pass_length = metrics["average_pass_length_m"]
    counter_share = metrics["counterattack_action_share_pct"]
    pressure_height = metrics["average_pressure_height"]
    crossing = metrics["crosses_per_match"]

    labels.append(
        "Possession-led"
        if possession >= 53
        else "Direct"
        if possession <= 46
        else "Balanced possession"
    )
    labels.append(
        "Short passing"
        if pass_length <= 18
        else "Longer distribution"
        if pass_length >= 21
        else "Mixed passing"
    )
    if counter_share >= 6:
        labels.append("Transition threat")
    if pressure_height >= 66:
        labels.append("High pressure")
    elif pressure_height <= 54:
        labels.append("Deeper pressure")
    if crossing >= 18:
        labels.append("Wide delivery")
    return labels[:4]


def _table_rows(matches: Iterable[Match], team_names: dict[int, str]) -> list[dict[str, Any]]:
    table = {
        team_id: {
            "team_id": team_id,
            "team_name": name,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "gf": 0,
            "ga": 0,
            "points": 0,
        }
        for team_id, name in team_names.items()
    }
    for match in matches:
        home = table.get(match.home_team_id)
        away = table.get(match.away_team_id)
        if not home or not away:
            continue
        home["played"] += 1
        away["played"] += 1
        home["gf"] += match.home_score
        home["ga"] += match.away_score
        away["gf"] += match.away_score
        away["ga"] += match.home_score
        if match.home_score > match.away_score:
            home["won"] += 1
            away["lost"] += 1
            home["points"] += 3
        elif match.home_score < match.away_score:
            away["won"] += 1
            home["lost"] += 1
            away["points"] += 3
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    rows = list(table.values())
    for row in rows:
        row["goal_difference"] = row["gf"] - row["ga"]
    rows.sort(key=lambda row: (row["points"], row["goal_difference"], row["gf"]), reverse=True)
    for index, row in enumerate(rows, 1):
        row["position"] = index
    return rows


def build_team_intelligence(
    db: Session,
    team_id: int,
    competition_id: int,
    season_id: int,
) -> dict[str, Any] | None:
    """Build a complete club profile from match, event and lineup data."""
    team = db.get(Team, team_id)
    season_stat = db.scalar(
        select(TeamSeasonStat).where(
            TeamSeasonStat.team_id == team_id,
            TeamSeasonStat.competition_id == competition_id,
            TeamSeasonStat.season_id == season_id,
        )
    )
    if not team or not season_stat:
        return None

    home = aliased(Team)
    away = aliased(Team)
    match_rows = list(
        db.execute(
            select(Match, home.team_name, away.team_name)
            .join(home, Match.home_team_id == home.team_id)
            .join(away, Match.away_team_id == away.team_id)
            .where(
                Match.competition_id == competition_id,
                Match.season_id == season_id,
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            )
            .order_by(Match.match_date, Match.match_id)
        )
    )
    matches = [row[0] for row in match_rows]
    match_ids = [match.match_id for match in matches]
    if not match_ids:
        return None

    all_teams = {
        row.team_id: row.team_name
        for row in db.scalars(
            select(Team)
            .join(TeamSeasonStat, TeamSeasonStat.team_id == Team.team_id)
            .where(
                TeamSeasonStat.competition_id == competition_id,
                TeamSeasonStat.season_id == season_id,
            )
        )
    }
    all_matches = list(
        db.scalars(
            select(Match).where(
                Match.competition_id == competition_id,
                Match.season_id == season_id,
            )
        )
    )
    table_row = next(
        row for row in _table_rows(all_matches, all_teams) if row["team_id"] == team_id
    )

    team_stats = {
        row.match_id: row
        for row in db.scalars(
            select(TeamMatchStat).where(
                TeamMatchStat.match_id.in_(match_ids), TeamMatchStat.team_id == team_id
            )
        )
    }
    opponent_stats = {
        row.match_id: row
        for row in db.scalars(
            select(TeamMatchStat).where(
                TeamMatchStat.match_id.in_(match_ids), TeamMatchStat.team_id != team_id
            )
        )
    }

    managers: Counter[str] = Counter()
    stadiums: Counter[str] = Counter()
    form: list[dict[str, Any]] = []
    cumulative_points = 0
    home_record = {"played": 0, "won": 0, "drawn": 0, "lost": 0, "points": 0, "gf": 0, "ga": 0}
    away_record = {"played": 0, "won": 0, "drawn": 0, "lost": 0, "points": 0, "gf": 0, "ga": 0}

    for match, home_name, away_name in match_rows:
        is_home = match.home_team_id == team_id
        opponent_id = match.away_team_id if is_home else match.home_team_id
        opponent_name = away_name if is_home else home_name
        goals_for = match.home_score if is_home else match.away_score
        goals_against = match.away_score if is_home else match.home_score
        if goals_for > goals_against:
            result, points = "W", 3
        elif goals_for < goals_against:
            result, points = "L", 0
        else:
            result, points = "D", 1
        cumulative_points += points
        split = home_record if is_home else away_record
        split["played"] += 1
        split[{"W": "won", "D": "drawn", "L": "lost"}[result]] += 1
        split["points"] += points
        split["gf"] += goals_for
        split["ga"] += goals_against

        stat = team_stats.get(match.match_id)
        opponent_stat = opponent_stats.get(match.match_id)
        form.append(
            {
                "match_id": match.match_id,
                "date": match.match_date.isoformat(),
                "match_week": match.match_week,
                "venue": "Home" if is_home else "Away",
                "opponent_id": opponent_id,
                "opponent": opponent_name,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": result,
                "points": points,
                "cumulative_points": cumulative_points,
                "xg_for": _round(stat.xg if stat else 0, 2),
                "xg_against": _round(opponent_stat.xg if opponent_stat else 0, 2),
                "shots_for": stat.shots if stat else 0,
                "shots_against": opponent_stat.shots if opponent_stat else 0,
                "possession_pct": _round(stat.possession_pct if stat else 0, 1),
            }
        )

        raw = match.raw_data or {}
        side = raw.get("home_team", {}) if is_home else raw.get("away_team", {})
        for manager in side.get("managers") or []:
            if manager.get("name"):
                managers[manager["name"]] += 1
        if is_home and match.stadium_name:
            stadiums[match.stadium_name] += 1

    event_columns = (
        Event.match_id,
        Event.event_index,
        Event.period,
        Event.minute,
        Event.second,
        Event.type_name,
        Event.possession,
        Event.possession_team_id,
        Event.play_pattern_name,
        Event.team_id,
        Event.location_x,
        Event.location_y,
        Event.under_pressure,
        Event.counterpress,
        Event.pass_outcome_name,
        Event.pass_length,
        Event.pass_end_x,
        Event.pass_end_y,
        Event.pass_cross,
        Event.pass_switch,
        Event.shot_outcome_name,
        Event.shot_type_name,
        Event.shot_statsbomb_xg,
        Event.carry_end_x,
        Event.carry_end_y,
        Event.duel_type_name,
    )
    events = list(
        db.execute(
            select(*event_columns)
            .where(
                Event.match_id.in_(match_ids),
                or_(Event.team_id == team_id, Event.type_name.in_(("Pass", "Shot"))),
            )
            .order_by(Event.match_id, Event.event_index)
        )
    )

    passes = completed_passes = crosses = switches = forward_passes = 0
    pass_length_total = 0.0
    progressive_passes = progressive_carries = 0
    final_third_entries = box_entries = 0
    pressures = counterpressures = high_pressures = 0
    pressure_x: list[float] = []
    defensive_x: list[float] = []
    pressure_events: list[dict[str, Any]] = []
    defensive_events: list[dict[str, Any]] = []
    progressive_actions: list[dict[str, Any]] = []
    shots_for: list[dict[str, Any]] = []
    shots_against: list[dict[str, Any]] = []
    channel_entries = {"left": 0, "centre": 0, "right": 0}
    counter_actions = 0
    possession_actions = 0
    set_piece_shots = 0
    box_shots = 0
    own_xg = opponent_xg = 0.0
    opponent_passes_defensive_zone = 0
    defensive_actions_pressing_zone = 0
    possessions: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"passes": 0, "start": 10_000, "end": 0}
    )

    for event in events:
        is_team = event.team_id == team_id
        x = event.location_x
        y = event.location_y

        if not is_team:
            if event.type_name == "Pass" and x is not None and x <= 72:
                opponent_passes_defensive_zone += 1
            if event.type_name == "Shot":
                xg = float(event.shot_statsbomb_xg or 0)
                opponent_xg += xg
                shots_against.append(
                    {
                        "x": _round(x, 1),
                        "y": _round(y, 1),
                        "xg": _round(xg, 3),
                        "outcome": event.shot_outcome_name or "Unknown",
                        "match_id": event.match_id,
                    }
                )
            continue

        if event.type_name in POSSESSION_EVENTS and event.possession_team_id == team_id:
            possession_actions += 1
            if event.play_pattern_name == "From Counter":
                counter_actions += 1
            if event.possession is not None:
                possession = possessions[(event.match_id, event.possession)]
                seconds = event.minute * 60 + event.second
                possession["start"] = min(possession["start"], seconds)
                possession["end"] = max(possession["end"], seconds)

        if event.type_name == "Pass":
            passes += 1
            is_complete = event.pass_outcome_name is None
            completed_passes += int(is_complete)
            pass_length_total += float(event.pass_length or 0)
            crosses += int(bool(event.pass_cross))
            switches += int(bool(event.pass_switch))
            if event.possession is not None and event.possession_team_id == team_id:
                possessions[(event.match_id, event.possession)]["passes"] += 1
            end_x, end_y = event.pass_end_x, event.pass_end_y
            if x is not None and end_x is not None:
                forward_passes += int(end_x > x + 3)
                is_progressive = is_complete and (end_x - x >= 15 or (x < 80 <= end_x))
                if is_progressive:
                    progressive_passes += 1
                    progressive_actions.append(
                        {
                            "type": "Pass",
                            "x": _round(x, 1),
                            "y": _round(y, 1),
                            "end_x": _round(end_x, 1),
                            "end_y": _round(end_y, 1),
                            "completed": is_complete,
                        }
                    )
                if is_complete and x < 80 <= end_x:
                    final_third_entries += 1
                    if end_y is not None:
                        channel = "left" if end_y < 26.7 else "right" if end_y > 53.3 else "centre"
                        channel_entries[channel] += 1
                outside_box = x < 102 or y is None or not 18 <= y <= 62
                if (
                    is_complete
                    and outside_box
                    and end_x >= 102
                    and end_y is not None
                    and 18 <= end_y <= 62
                ):
                    box_entries += 1

        elif event.type_name == "Carry":
            end_x, end_y = event.carry_end_x, event.carry_end_y
            if x is not None and end_x is not None:
                is_progressive = end_x - x >= 10 or (x < 80 <= end_x)
                if is_progressive:
                    progressive_carries += 1
                    progressive_actions.append(
                        {
                            "type": "Carry",
                            "x": _round(x, 1),
                            "y": _round(y, 1),
                            "end_x": _round(end_x, 1),
                            "end_y": _round(end_y, 1),
                            "completed": True,
                        }
                    )
                if x < 80 <= end_x:
                    final_third_entries += 1
                    if end_y is not None:
                        channel = "left" if end_y < 26.7 else "right" if end_y > 53.3 else "centre"
                        channel_entries[channel] += 1
                outside_box = x < 102 or y is None or not 18 <= y <= 62
                if outside_box and end_x >= 102 and end_y is not None and 18 <= end_y <= 62:
                    box_entries += 1

        elif event.type_name == "Shot":
            xg = float(event.shot_statsbomb_xg or 0)
            own_xg += xg
            shots_for.append(
                {
                    "x": _round(x, 1),
                    "y": _round(y, 1),
                    "xg": _round(xg, 3),
                    "outcome": event.shot_outcome_name or "Unknown",
                    "match_id": event.match_id,
                }
            )
            if x is not None and y is not None and x >= 102 and 18 <= y <= 62:
                box_shots += 1
            if event.play_pattern_name in SET_PIECE_PATTERNS or event.shot_type_name != "Open Play":
                set_piece_shots += 1

        if event.type_name == "Pressure":
            pressures += 1
            counterpressures += int(bool(event.counterpress))
            if x is not None:
                pressure_x.append(x)
                high_pressures += int(x >= 80)
                pressure_events.append(
                    {"x": _round(x, 1), "y": _round(y, 1), "counterpress": bool(event.counterpress)}
                )

        if event.type_name in DEFENSIVE_EVENTS:
            if x is not None:
                defensive_x.append(x)
                defensive_events.append(
                    {"x": _round(x, 1), "y": _round(y, 1), "type": event.type_name}
                )
                if x >= 48:
                    defensive_actions_pressing_zone += 1

    possession_durations = [
        max(0, value["end"] - value["start"])
        for value in possessions.values()
        if value["start"] < 10_000
    ]
    possession_count = len(possessions)
    match_count = len(matches)
    goals = table_row["gf"]
    goals_against = table_row["ga"]
    shot_count = len(shots_for)
    opponent_shot_count = len(shots_against)
    ppda = (
        opponent_passes_defensive_zone / defensive_actions_pressing_zone
        if defensive_actions_pressing_zone
        else 0
    )

    style_metrics = {
        "average_possession_pct": _round(season_stat.avg_possession_pct, 1),
        "pass_completion_pct": _pct(completed_passes, passes),
        "average_pass_length_m": _round(pass_length_total / passes if passes else 0, 1),
        "forward_pass_share_pct": _pct(forward_passes, passes),
        "passes_per_possession": _round(
            sum(value["passes"] for value in possessions.values()) / possession_count
            if possession_count
            else 0,
            1,
        ),
        "average_possession_duration_sec": _round(
            mean(possession_durations) if possession_durations else 0, 1
        ),
        "counterattack_action_share_pct": _pct(counter_actions, possession_actions),
        "progressive_passes_per_match": _per_match(progressive_passes, match_count),
        "progressive_carries_per_match": _per_match(progressive_carries, match_count),
        "final_third_entries_per_match": _per_match(final_third_entries, match_count),
        "box_entries_per_match": _per_match(box_entries, match_count),
        "crosses_per_match": _per_match(crosses, match_count),
        "switches_per_match": _per_match(switches, match_count),
        "average_pressure_height": _round(mean(pressure_x) if pressure_x else 0, 1),
        "high_pressure_share_pct": _pct(high_pressures, pressures),
        "ppda_proxy": _round(ppda, 1),
    }

    starting_xi_rows = list(
        db.scalars(
            select(Event).where(
                Event.match_id.in_(match_ids),
                Event.team_id == team_id,
                Event.type_name == "Starting XI",
            )
        )
    )
    formations: Counter[str] = Counter()
    formation_positions: dict[str, list[str]] = {}
    for event in starting_xi_rows:
        tactics = (event.raw_data or {}).get("tactics") or {}
        label = _formation_label(tactics.get("formation"))
        formations[label] += 1
        if label not in formation_positions:
            formation_positions[label] = [
                item.get("position", {}).get("name", "Position")
                for item in tactics.get("lineup") or []
            ]
    most_used_formation = formations.most_common(1)[0][0] if formations else "Unknown"

    manager_rows = [{"name": name, "matches": count} for name, count in managers.most_common()]
    recent_form = "".join(item["result"] for item in form[-5:])
    identity_summary = (
        f"{team.team_name} averaged {style_metrics['average_possession_pct']:.1f}% possession and "
        f"{style_metrics['final_third_entries_per_match']:.1f} final-third entries per match. "
        f"Their passes travelled {style_metrics['average_pass_length_m']:.1f} metres on average, "
        "while the press began at an average pitch position of "
        f"{style_metrics['average_pressure_height']:.1f}/120."
    )

    return {
        "team": {
            **table_row,
            "manager": manager_rows[0]["name"] if manager_rows else "Not recorded",
            "managers": manager_rows,
            "stadium": stadiums.most_common(1)[0][0] if stadiums else "Not recorded",
            "xg_for": _round(sum(stat.xg for stat in team_stats.values()), 2),
            "xg_against": _round(sum(stat.xg for stat in opponent_stats.values()), 2),
            "shots_for": sum(stat.shots for stat in team_stats.values()),
            "shots_against": sum(stat.shots for stat in opponent_stats.values()),
            "average_possession_pct": _round(season_stat.avg_possession_pct, 1),
            "clean_sheets": sum(1 for item in form if item["goals_against"] == 0),
            "recent_form": recent_form,
            "home_record": home_record,
            "away_record": away_record,
        },
        "form": form,
        "style": {
            "labels": _style_labels(style_metrics),
            "summary": identity_summary,
            "metrics": style_metrics,
        },
        "ball_movement": {
            "passes": passes,
            "completed_passes": completed_passes,
            "progressive_passes": progressive_passes,
            "progressive_carries": progressive_carries,
            "final_third_entries": final_third_entries,
            "box_entries": box_entries,
            "crosses": crosses,
            "switches": switches,
            "entry_channels": channel_entries,
            "progressive_actions": _sample(progressive_actions, 360),
        },
        "attacking": {
            "goals": goals,
            "xg": _round(own_xg, 2),
            "shots": shot_count,
            "shots_per_match": _per_match(shot_count, match_count),
            "xg_per_shot": _round(own_xg / shot_count if shot_count else 0, 3),
            "box_shot_share_pct": _pct(box_shots, shot_count),
            "set_piece_shot_share_pct": _pct(set_piece_shots, shot_count),
            "goal_conversion_pct": _pct(goals, shot_count),
            "shot_map": shots_for,
        },
        "defending": {
            "goals_against": goals_against,
            "xg_against": _round(opponent_xg, 2),
            "shots_against": opponent_shot_count,
            "shots_against_per_match": _per_match(opponent_shot_count, match_count),
            "xg_per_shot_against": _round(
                opponent_xg / opponent_shot_count if opponent_shot_count else 0, 3
            ),
            "pressures_per_match": _per_match(pressures, match_count),
            "counterpress_share_pct": _pct(counterpressures, pressures),
            "defensive_action_height": _round(mean(defensive_x) if defensive_x else 0, 1),
            "ppda_proxy": _round(ppda, 1),
            "pressure_map": _sample(pressure_events, 500),
            "defensive_action_map": _sample(defensive_events, 500),
            "opposition_shot_map": shots_against,
        },
        "formations": {
            "most_used": most_used_formation,
            "shape_positions": formation_positions.get(most_used_formation, []),
            "distribution": [
                {
                    "formation": formation,
                    "starts": starts,
                    "share_pct": _pct(starts, len(starting_xi_rows)),
                }
                for formation, starts in formations.most_common()
            ],
        },
        "methodology": {
            "progressive_action": (
                "A completed pass moving the ball at least 15m, or a carry moving it "
                "at least 10m, toward goal; final-third entries also qualify."
            ),
            "final_third_entry": (
                "A completed pass or carry crossing the x=80 line into the attacking third."
            ),
            "box_entry": "A pass or carry ending inside the penalty area from outside it.",
            "ppda_proxy": (
                "Opponent passes in their defensive 60% divided by defensive actions "
                "in the pressing zone; lower means more aggressive pressure."
            ),
            "coordinates": "StatsBomb pitch coordinates: 120 long by 80 wide.",
        },
    }
