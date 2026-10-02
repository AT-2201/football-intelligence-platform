from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from football_intelligence.models import (
    Event,
    Lineup,
    Match,
    PlayerMatchStat,
    PlayerSeasonPosition,
    PlayerSeasonStat,
    SeasonSummary,
    TeamMatchStat,
    TeamSeasonStat,
)


def _clock_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    parts = [float(part) for part in value.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0] * 60 + parts[1]


def _lineup_minutes(
    positions: list[dict[str, Any]], match_end_seconds: float | None = None
) -> float:
    seconds = sum(
        max(
            0.0,
            (
                _clock_seconds(segment.get("to"))
                if segment.get("to")
                else (match_end_seconds or 0.0)
            )
            - _clock_seconds(segment.get("from")),
        )
        for segment in positions
    )
    return round(seconds / 60, 2)


def transform_season(session: Session, competition_id: int, season_id: int) -> dict[str, int]:
    matches = session.scalars(
        select(Match).where(
            Match.competition_id == competition_id, Match.season_id == season_id
        )
    ).all()
    match_ids = [match.match_id for match in matches]
    if not match_ids:
        raise ValueError("No ingested matches found for this competition-season")

    for model in (
        TeamMatchStat,
        PlayerMatchStat,
        TeamSeasonStat,
        PlayerSeasonStat,
        PlayerSeasonPosition,
        SeasonSummary,
    ):
        session.execute(
            delete(model).where(
                model.competition_id == competition_id, model.season_id == season_id
            )
        )

    player_match_count = 0
    event_count = 0
    for match in matches:
        events = session.scalars(select(Event).where(Event.match_id == match.match_id)).all()
        event_count += len(events)
        lineups = session.scalars(select(Lineup).where(Lineup.match_id == match.match_id)).all()
        total_possession_events = sum(event.possession_team_id is not None for event in events)
        match_end_seconds = max(
            (event.minute * 60 + event.second + (event.duration or 0) for event in events),
            default=90 * 60,
        )

        for team_id, is_home, goals in (
            (match.home_team_id, True, match.home_score),
            (match.away_team_id, False, match.away_score),
        ):
            team_events = [event for event in events if event.team_id == team_id]
            possession_events = sum(event.possession_team_id == team_id for event in events)
            passes = [event for event in team_events if event.type_name == "Pass"]
            shots = [event for event in team_events if event.type_name == "Shot"]
            session.add(
                TeamMatchStat(
                    match_id=match.match_id,
                    team_id=team_id,
                    competition_id=competition_id,
                    season_id=season_id,
                    is_home=is_home,
                    goals=goals,
                    shots=len(shots),
                    xg=sum(event.shot_statsbomb_xg or 0 for event in shots),
                    passes=len(passes),
                    completed_passes=sum(event.pass_outcome_name is None for event in passes),
                    possession_pct=(100 * possession_events / total_possession_events)
                    if total_possession_events
                    else 0,
                )
            )

        for lineup in lineups:
            player_events = [event for event in events if event.player_id == lineup.player_id]
            passes = [event for event in player_events if event.type_name == "Pass"]
            shots = [event for event in player_events if event.type_name == "Shot"]
            session.add(
                PlayerMatchStat(
                    match_id=match.match_id,
                    player_id=lineup.player_id,
                    team_id=lineup.team_id,
                    competition_id=competition_id,
                    season_id=season_id,
                    minutes=_lineup_minutes(lineup.positions, match_end_seconds),
                    shots=len(shots),
                    goals=sum(event.shot_outcome_name == "Goal" for event in shots),
                    xg=sum(event.shot_statsbomb_xg or 0 for event in shots),
                    passes=len(passes),
                    completed_passes=sum(event.pass_outcome_name is None for event in passes),
                    carries=sum(event.type_name == "Carry" for event in player_events),
                    pressures=sum(event.type_name == "Pressure" for event in player_events),
                    tackles=sum(
                        event.type_name == "Duel" and event.duel_type_name == "Tackle"
                        for event in player_events
                    ),
                    interceptions=sum(
                        event.type_name == "Interception" for event in player_events
                    ),
                )
            )
            player_match_count += 1
        session.flush()

    team_rows = session.scalars(
        select(TeamMatchStat).where(
            TeamMatchStat.competition_id == competition_id,
            TeamMatchStat.season_id == season_id,
        )
    ).all()
    by_team: dict[int, list[TeamMatchStat]] = defaultdict(list)
    for row in team_rows:
        by_team[row.team_id].append(row)
    for team_id, rows in by_team.items():
        session.add(
            TeamSeasonStat(
                competition_id=competition_id,
                season_id=season_id,
                team_id=team_id,
                matches=len(rows),
                goals=sum(row.goals for row in rows),
                shots=sum(row.shots for row in rows),
                xg=sum(row.xg for row in rows),
                passes=sum(row.passes for row in rows),
                completed_passes=sum(row.completed_passes for row in rows),
                avg_possession_pct=sum(row.possession_pct for row in rows) / len(rows),
            )
        )

    player_rows = session.scalars(
        select(PlayerMatchStat).where(
            PlayerMatchStat.competition_id == competition_id,
            PlayerMatchStat.season_id == season_id,
        )
    ).all()
    by_player_team: dict[tuple[int, int], list[PlayerMatchStat]] = defaultdict(list)
    for row in player_rows:
        by_player_team[(row.player_id, row.team_id)].append(row)
    fields = (
        "minutes",
        "shots",
        "goals",
        "xg",
        "passes",
        "completed_passes",
        "carries",
        "pressures",
        "tackles",
        "interceptions",
    )
    for (player_id, team_id), rows in by_player_team.items():
        totals = {field: sum(getattr(row, field) for row in rows) for field in fields}
        session.add(
            PlayerSeasonStat(
                competition_id=competition_id,
                season_id=season_id,
                player_id=player_id,
                team_id=team_id,
                appearances=sum(row.minutes > 0 for row in rows),
                **totals,
            )
        )

    position_counts: dict[tuple[int, int], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for player_id, team_id, position_name, count in session.execute(
        select(
            Event.player_id,
            Event.team_id,
            Event.position_name,
            func.count(Event.event_id),
        )
        .where(
            Event.match_id.in_(match_ids),
            Event.player_id.is_not(None),
            Event.team_id.is_not(None),
            Event.position_name.is_not(None),
        )
        .group_by(Event.player_id, Event.team_id, Event.position_name)
    ):
        position_counts[(player_id, team_id)][position_name] = count
    for (player_id, team_id), counts in position_counts.items():
        position_name, position_event_count = max(counts.items(), key=lambda item: item[1])
        session.add(
            PlayerSeasonPosition(
                competition_id=competition_id,
                season_id=season_id,
                player_id=player_id,
                team_id=team_id,
                position_name=position_name,
                event_count=position_event_count,
            )
        )
    session.add(
        SeasonSummary(
            competition_id=competition_id,
            season_id=season_id,
            matches=len(matches),
            teams=len(by_team),
            players=len({row.player_id for row in player_rows if row.minutes > 0}),
            events=event_count,
            goals=sum(match.home_score + match.away_score for match in matches),
        )
    )
    session.commit()
    return {
        "matches": len(matches),
        "team_match_rows": len(team_rows),
        "player_match_rows": player_match_count,
    }
