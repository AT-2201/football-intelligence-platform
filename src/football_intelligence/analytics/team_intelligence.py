"""Match-by-match tactical analysis for a club competition-season.

The output intentionally uses transparent event counts, rates and locations.
It describes how a team played in each match without an opaque style score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from statistics import mean
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from football_intelligence.models import Event, Match, Team, TeamMatchStat, TeamSeasonStat

DEFENSIVE_EVENTS = {"Pressure", "Ball Recovery", "Duel", "Interception", "Block", "Clearance"}
POSSESSION_EVENTS = {"Pass", "Carry", "Shot", "Dribble"}


def _round(value: float | int | None, digits: int = 1) -> float:
    return round(float(value or 0), digits)


def _pct(numerator: float, denominator: float) -> float:
    return _round(100 * numerator / denominator, 1) if denominator else 0.0


def _formation_label(value: Any) -> str:
    digits = str(value or "")
    return "-".join(digits) if digits.isdigit() else "Unknown"


def _mean(records: list[dict[str, Any]], key: str) -> float:
    values = [float(record[key]) for record in records if record.get(key) is not None]
    return _round(mean(values) if values else 0, 1)


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


def _empty_match_bucket() -> dict[str, Any]:
    return {
        "passes": 0,
        "completed_passes": 0,
        "pass_length_total": 0.0,
        "forward_passes": 0,
        "direct_passes": 0,
        "under_pressure_passes": 0,
        "under_pressure_completed": 0,
        "crosses": 0,
        "switches": 0,
        "pass_start_x": [],
        "final_third_passes": 0,
        "final_third_entries": 0,
        "entry_channels": {"left": 0, "centre": 0, "right": 0},
        "possession_actions": 0,
        "counter_actions": 0,
        "possessions": defaultdict(lambda: {"passes": 0, "start": 10_000, "end": 0}),
        "pressures": 0,
        "pressure_x": [],
        "high_pressures": 0,
        "counterpressures": 0,
        "defensive_x": [],
        "defensive_actions_pressing_zone": 0,
        "opponent_passes": 0,
        "opponent_completed_passes": 0,
        "opponent_passes_defensive_zone": 0,
        "opponent_final_third_passes": 0,
    }


def _match_style_labels(metrics: dict[str, float]) -> list[str]:
    labels: list[str] = []
    possession = metrics["possession_pct"]
    pass_length = metrics["average_pass_length_m"]
    duration = metrics["average_possession_duration_sec"]
    pressure_height = metrics["pressure_height"]
    centre_share = metrics["centre_entry_share_pct"]
    wide_share = metrics["left_entry_share_pct"] + metrics["right_entry_share_pct"]
    labels.append(
        "Ball-dominant"
        if possession >= 55
        else "Without-ball plan"
        if possession <= 44
        else "Balanced control"
    )
    labels.append(
        "Patient build-up"
        if pass_length <= 18.5 and duration >= 13
        else "Direct build-up"
        if pass_length >= 21.5
        else "Mixed build-up"
    )
    labels.append(
        "Sustained possession"
        if duration >= 15
        else "Quick sequences"
        if duration <= 10
        else "Measured tempo"
    )
    labels.append(
        "Central progression"
        if centre_share >= 40
        else "Wide progression"
        if wide_share >= 70
        else "Mixed channels"
    )
    labels.append(
        "High press"
        if pressure_height >= 65
        else "Deeper block"
        if pressure_height <= 52
        else "Mid-block"
    )
    return labels


def _match_observations(team_name: str, report: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    metrics = report["metrics"]
    opponent = report["opponent"]
    control = (
        "controlled most of the ball"
        if metrics["possession_pct"] >= 55
        else "accepted a smaller share of possession"
        if metrics["possession_pct"] <= 44
        else "shared possession relatively evenly"
    )
    distribution = (
        "used longer, earlier distribution"
        if metrics["average_pass_length_m"] >= 21.5
        else "built with shorter passing sequences"
        if metrics["average_pass_length_m"] <= 18.5
        else "mixed short combinations with longer distribution"
    )
    summary = (
        f"Against {opponent}, {team_name} {control} and {distribution}. "
        f"The average possession lasted {metrics['average_possession_duration_sec']:.1f} seconds, "
        f"while defensive pressure was applied at x={metrics['pressure_height']:.1f}/120."
    )
    dominant_channel = max(
        ("left", metrics["left_entry_share_pct"]),
        ("centre", metrics["centre_entry_share_pct"]),
        ("right", metrics["right_entry_share_pct"]),
        key=lambda item: item[1],
    )
    observations = [
        {
            "title": "Build-up and tempo",
            "text": (
                f"{metrics['passes_per_possession']:.1f} passes per possession with "
                f"{metrics['pass_completion_pct']:.1f}% completion. "
                f"{metrics['direct_pass_share_pct']:.1f}% of passes travelled at least 25m."
            ),
        },
        {
            "title": "Territory and width",
            "text": (
                f"{metrics['field_tilt_pct']:.1f}% field tilt and "
                f"{metrics['final_third_entries']:.0f} final-third entries. "
                f"The {dominant_channel[0]} channel supplied {dominant_channel[1]:.1f}% of entries."
            ),
        },
        {
            "title": "Transitions",
            "text": (
                f"{metrics['counterattack_action_share_pct']:.1f}% of possession actions came "
                f"from counters; {metrics['counterpress_share_pct']:.1f}% of pressures were "
                "recorded as counterpresses."
            ),
        },
        {
            "title": "Pressing and block",
            "text": (
                f"Pressure height was {metrics['pressure_height']:.1f}/120, with "
                f"{metrics['high_pressure_share_pct']:.1f}% in the attacking third. "
                f"The pressure-intensity proxy was {metrics['ppda_proxy']:.1f}."
            ),
        },
    ]
    return summary, observations


def _match_metrics(bucket: dict[str, Any], possession_pct: float) -> dict[str, float]:
    possessions = bucket["possessions"]
    durations = [
        max(0, item["end"] - item["start"])
        for item in possessions.values()
        if item["start"] < 10_000
    ]
    entries = sum(bucket["entry_channels"].values())
    final_third_total = bucket["final_third_passes"] + bucket["opponent_final_third_passes"]
    ppda = (
        bucket["opponent_passes_defensive_zone"] / bucket["defensive_actions_pressing_zone"]
        if bucket["defensive_actions_pressing_zone"]
        else 0
    )
    return {
        "possession_pct": _round(possession_pct, 1),
        "pass_completion_pct": _pct(bucket["completed_passes"], bucket["passes"]),
        "passes_per_possession": _round(
            sum(item["passes"] for item in possessions.values()) / len(possessions)
            if possessions
            else 0,
            1,
        ),
        "average_possession_duration_sec": _round(mean(durations) if durations else 0, 1),
        "average_pass_length_m": _round(
            bucket["pass_length_total"] / bucket["passes"] if bucket["passes"] else 0,
            1,
        ),
        "forward_pass_share_pct": _pct(bucket["forward_passes"], bucket["passes"]),
        "direct_pass_share_pct": _pct(bucket["direct_passes"], bucket["passes"]),
        "under_pressure_completion_pct": _pct(
            bucket["under_pressure_completed"], bucket["under_pressure_passes"]
        ),
        "average_pass_start_x": _round(
            mean(bucket["pass_start_x"]) if bucket["pass_start_x"] else 0, 1
        ),
        "field_tilt_pct": _pct(bucket["final_third_passes"], final_third_total),
        "final_third_entries": float(bucket["final_third_entries"]),
        "left_entry_share_pct": _pct(bucket["entry_channels"]["left"], entries),
        "centre_entry_share_pct": _pct(bucket["entry_channels"]["centre"], entries),
        "right_entry_share_pct": _pct(bucket["entry_channels"]["right"], entries),
        "crosses_per_100_passes": _pct(bucket["crosses"], bucket["passes"]),
        "switches_per_100_passes": _pct(bucket["switches"], bucket["passes"]),
        "counterattack_action_share_pct": _pct(
            bucket["counter_actions"], bucket["possession_actions"]
        ),
        "pressure_height": _round(mean(bucket["pressure_x"]) if bucket["pressure_x"] else 0, 1),
        "high_pressure_share_pct": _pct(bucket["high_pressures"], bucket["pressures"]),
        "counterpress_share_pct": _pct(bucket["counterpressures"], bucket["pressures"]),
        "defensive_action_height": _round(
            mean(bucket["defensive_x"]) if bucket["defensive_x"] else 0, 1
        ),
        "ppda_proxy": _round(ppda, 1),
        "opponent_pass_completion_pct": _pct(
            bucket["opponent_completed_passes"], bucket["opponent_passes"]
        ),
    }


def build_team_intelligence(
    db: Session,
    team_id: int,
    competition_id: int,
    season_id: int,
) -> dict[str, Any] | None:
    """Build results, formations and match-level style reports for one club."""
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
        result, points = (
            ("W", 3)
            if goals_for > goals_against
            else ("L", 0)
            if goals_for < goals_against
            else ("D", 1)
        )
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
        Event.carry_end_x,
        Event.carry_end_y,
    )
    events = db.execute(
        select(*event_columns)
        .where(
            Event.match_id.in_(match_ids),
            or_(Event.team_id == team_id, Event.type_name == "Pass"),
        )
        .order_by(Event.match_id, Event.event_index)
    )
    buckets = {match_id: _empty_match_bucket() for match_id in match_ids}
    for event in events:
        bucket = buckets[event.match_id]
        is_team = event.team_id == team_id
        x = event.location_x
        if not is_team:
            if event.type_name == "Pass":
                bucket["opponent_passes"] += 1
                complete = event.pass_outcome_name is None
                bucket["opponent_completed_passes"] += int(complete)
                if x is not None and x <= 72:
                    bucket["opponent_passes_defensive_zone"] += 1
                if complete and event.pass_end_x is not None and event.pass_end_x >= 80:
                    bucket["opponent_final_third_passes"] += 1
            continue

        if event.type_name in POSSESSION_EVENTS and event.possession_team_id == team_id:
            bucket["possession_actions"] += 1
            bucket["counter_actions"] += int(event.play_pattern_name == "From Counter")
            if event.possession is not None:
                possession = bucket["possessions"][event.possession]
                seconds = event.minute * 60 + event.second
                possession["start"] = min(possession["start"], seconds)
                possession["end"] = max(possession["end"], seconds)

        if event.type_name == "Pass":
            bucket["passes"] += 1
            complete = event.pass_outcome_name is None
            bucket["completed_passes"] += int(complete)
            bucket["pass_length_total"] += float(event.pass_length or 0)
            bucket["direct_passes"] += int(float(event.pass_length or 0) >= 25)
            bucket["crosses"] += int(bool(event.pass_cross))
            bucket["switches"] += int(bool(event.pass_switch))
            if event.under_pressure:
                bucket["under_pressure_passes"] += 1
                bucket["under_pressure_completed"] += int(complete)
            if x is not None:
                bucket["pass_start_x"].append(x)
            if event.possession is not None and event.possession_team_id == team_id:
                bucket["possessions"][event.possession]["passes"] += 1
            end_x, end_y = event.pass_end_x, event.pass_end_y
            if x is not None and end_x is not None:
                bucket["forward_passes"] += int(end_x > x + 3)
                bucket["final_third_passes"] += int(complete and end_x >= 80)
                if complete and x < 80 <= end_x:
                    bucket["final_third_entries"] += 1
                    if end_y is not None:
                        channel = "left" if end_y < 26.7 else "right" if end_y > 53.3 else "centre"
                        bucket["entry_channels"][channel] += 1
        elif event.type_name == "Carry":
            end_x, end_y = event.carry_end_x, event.carry_end_y
            if x is not None and end_x is not None and x < 80 <= end_x:
                bucket["final_third_entries"] += 1
                if end_y is not None:
                    channel = "left" if end_y < 26.7 else "right" if end_y > 53.3 else "centre"
                    bucket["entry_channels"][channel] += 1
        if event.type_name == "Pressure":
            bucket["pressures"] += 1
            bucket["counterpressures"] += int(bool(event.counterpress))
            if x is not None:
                bucket["pressure_x"].append(x)
                bucket["high_pressures"] += int(x >= 80)
        if event.type_name in DEFENSIVE_EVENTS and x is not None:
            bucket["defensive_x"].append(x)
            bucket["defensive_actions_pressing_zone"] += int(x >= 48)

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
    match_formations: dict[int, str] = {}
    for event in starting_xi_rows:
        tactics = (event.raw_data or {}).get("tactics") or {}
        label = _formation_label(tactics.get("formation"))
        formations[label] += 1
        match_formations[event.match_id] = label
        if label not in formation_positions:
            formation_positions[label] = [
                item.get("position", {}).get("name", "Position")
                for item in tactics.get("lineup") or []
            ]
    most_used_formation = formations.most_common(1)[0][0] if formations else "Unknown"

    match_reports: list[dict[str, Any]] = []
    for match_row in form:
        metrics = _match_metrics(buckets[match_row["match_id"]], match_row["possession_pct"])
        report = {
            **match_row,
            "formation": match_formations.get(match_row["match_id"], "Unknown"),
            "metrics": metrics,
            "labels": _match_style_labels(metrics),
        }
        summary, observations = _match_observations(team.team_name, report)
        report["summary"] = summary
        report["observations"] = observations
        match_reports.append(report)

    baseline_keys = [
        "possession_pct",
        "pass_completion_pct",
        "passes_per_possession",
        "average_possession_duration_sec",
        "average_pass_length_m",
        "forward_pass_share_pct",
        "direct_pass_share_pct",
        "under_pressure_completion_pct",
        "average_pass_start_x",
        "field_tilt_pct",
        "final_third_entries",
        "left_entry_share_pct",
        "centre_entry_share_pct",
        "right_entry_share_pct",
        "crosses_per_100_passes",
        "switches_per_100_passes",
        "counterattack_action_share_pct",
        "pressure_height",
        "high_pressure_share_pct",
        "counterpress_share_pct",
        "defensive_action_height",
        "ppda_proxy",
        "opponent_pass_completion_pct",
    ]
    metric_records = [report["metrics"] for report in match_reports]
    season_baseline = {key: _mean(metric_records, key) for key in baseline_keys}
    manager_rows = [{"name": name, "matches": count} for name, count in managers.most_common()]

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
            "recent_form": "".join(item["result"] for item in form[-5:]),
            "home_record": home_record,
            "away_record": away_record,
        },
        "form": form,
        "playing_style": {
            "season_baseline": season_baseline,
            "match_reports": match_reports,
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
            "possession_sequence": (
                "Passes and duration within one StatsBomb possession for the selected team."
            ),
            "direct_pass": "A pass travelling at least 25 metres.",
            "field_tilt": (
                "The team's share of completed final-third passes by both clubs in the match."
            ),
            "final_third_entry": (
                "A completed pass or carry crossing the x=80 line into the attacking third."
            ),
            "pressure_height": "Average x-coordinate of pressure events on a 120x80 pitch.",
            "high_pressure": "A pressure event beginning in the attacking third (x at least 80).",
            "counterpress": "The share of pressures marked as counterpresses by StatsBomb.",
            "pressure_intensity_proxy": (
                "Opponent passes in their defensive 60% divided by the team's defensive "
                "actions in the pressing zone; lower indicates more frequent pressure."
            ),
        },
    }
