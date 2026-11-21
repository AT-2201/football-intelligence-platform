"""Event-based opposition scouting, with StatsBomb's attacking orientation."""

from collections import defaultdict

from sqlalchemy import select

from football_intelligence.models import Event

PHASES = ("0–15", "15–30", "30–HT", "HT–60", "60–75", "75–FT")


def opposition_match_profiles(db, team_id, matches, team_names, player_stats, player_names):
    profiles = {}
    for match in matches:
        other = match.away_team_id if match.home_team_id == team_id else match.home_team_id
        profiles[match.match_id] = {
            "date": str(match.match_date),
            "opponent": team_names[other],
            "score": [match.home_score, match.away_score] if match.home_team_id == team_id
            else [match.away_score, match.home_score],
            "phases": [
                dict(label=label, xg=0, xga=0, shots=0, entries=0, allowed=0,
                     high_pressures=0, left=0, centre=0, right=0, direct=0, passes=0)
                for label in PHASES
            ],
            "players": [],
            "possessions": [],
        }
    contributions = defaultdict(lambda: defaultdict(int))
    sequences = {}
    columns = (
        Event.match_id, Event.team_id, Event.player_id, Event.period, Event.minute,
        Event.type_name, Event.location_x, Event.pass_end_x, Event.pass_end_y,
        Event.carry_end_x, Event.carry_end_y, Event.pass_outcome_name,
        Event.pass_length, Event.shot_statsbomb_xg, Event.under_pressure,
        Event.possession, Event.possession_team_id, Event.second, Event.location_y,
    )
    rows = db.execute(select(*columns).where(
        Event.match_id.in_(profiles), Event.period.in_((1, 2)),
        Event.type_name.in_(("Pass", "Carry", "Shot", "Pressure")),
    ).order_by(Event.match_id, Event.event_index))
    for row_data in rows:
        (
            mid, team, player, half, minute, kind, x, px, py, cx, cy, outcome,
            length, xg, pressured, possession, possession_team, second, start_y,
        ) = row_data
        phase = min(2, minute // 15) if half == 1 else max(3, min(5, minute // 15))
        row = profiles[mid]["phases"][phase]
        own = team == team_id
        if own and possession_team == team_id and possession is not None and x is not None:
            if kind != "Pressure":
                # Store only the measurements needed to cluster and review each sequence.
                clock = minute * 60 + second
                sequence = sequences.setdefault(
                    (mid, half, possession),
                    [clock, x, x, start_y, 0, 0, 0, player, phase, clock],
                )
                sequence[4] += 1
                sequence[6] += xg or 0
                sequence[9] = clock
                end_x, end_y = (px, py) if kind == "Pass" and outcome is None else (cx, cy)
                for point_x, point_y in ((x, start_y), (end_x, end_y)):
                    if point_x is not None and point_x >= sequence[2]:
                        sequence[2:4] = [point_x, point_y]
        if kind == "Shot":
            row["xg" if own else "xga"] += xg or 0
            row["shots"] += int(own)
        if own and kind == "Pressure" and x is not None and x >= 80:
            row["high_pressures"] += 1
        if own and kind == "Pass":
            row["passes"] += 1
            row["direct"] += int((length or 0) >= 30)
            if pressured and player is not None:
                contributions[mid, player]["pressured"] += 1
                contributions[mid, player]["failed"] += int(outcome is not None)
        end_x, y = (px, py) if kind == "Pass" and outcome is None else (cx, cy)
        if x is not None and end_x is not None and y is not None and x < 80 <= end_x:
            row["entries" if own else "allowed"] += 1
            if own:
                row["left" if y < 80 / 3 else "right" if y >= 160 / 3 else "centre"] += 1
                if player is not None:
                    contributions[mid, player]["entries"] += 1
    for (mid, _, possession), sequence in sequences.items():
        if sequence[4] >= 2 and sequence[3] is not None:
            sequence[5] = max(0, sequence.pop() - sequence[0])
            sequence[6] = round(sequence[6], 3)
            profiles[mid]["possessions"].append([possession, *sequence])
    for (mid, pid), stat in player_stats.items():
        if stat.minutes > 0:
            profiles[mid]["players"].append(dict(
                id=pid, name=player_names.get(pid, str(pid)), minutes=stat.minutes,
                xg=stat.xg, goals=stat.goals, defensive=stat.tackles + stat.interceptions,
                **contributions.get((mid, pid), {}),
            ))
    for profile in profiles.values():
        for phase in profile["phases"]:
            for key in ("xg", "xga"):
                phase[key] = round(phase[key], 3)
    return list(profiles.values())
