from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from football_intelligence.models import Event, Match, PlayerMatchStat, TeamMatchStat


def validate_season(
    session: Session, competition_id: int, season_id: int, expected_matches: int = 380
) -> dict[str, Any]:
    match_ids = list(
        session.scalars(
            select(Match.match_id).where(
                Match.competition_id == competition_id, Match.season_id == season_id
            )
        )
    )
    issues: list[dict[str, str]] = []
    if len(match_ids) != expected_matches:
        issues.append(
            {
                "level": "warning",
                "check": "season_coverage",
                "message": f"Loaded {len(match_ids)} of {expected_matches} expected matches.",
            }
        )
    if not match_ids:
        issues.append(
            {"level": "error", "check": "matches_present", "message": "No matches loaded."}
        )
        return {"status": "failed", "counts": {"matches": 0}, "issues": issues}

    event_match_ids = set(
        session.scalars(select(Event.match_id).where(Event.match_id.in_(match_ids)).distinct())
    )
    missing_events = set(match_ids) - event_match_ids
    if missing_events:
        issues.append(
            {
                "level": "error",
                "check": "events_per_match",
                "message": f"{len(missing_events)} matches have no events.",
            }
        )

    team_rows = session.execute(
        select(TeamMatchStat.match_id, func.count(TeamMatchStat.team_id))
        .where(TeamMatchStat.match_id.in_(match_ids))
        .group_by(TeamMatchStat.match_id)
    )
    team_counts = {match_id: count for match_id, count in team_rows}
    invalid_team_rows = [match_id for match_id in match_ids if team_counts.get(match_id) != 2]
    if invalid_team_rows:
        issues.append(
            {
                "level": "error",
                "check": "team_stats_per_match",
                "message": f"{len(invalid_team_rows)} matches do not have two team-stat rows.",
            }
        )

    invalid_minutes = session.scalar(
        select(func.count())
        .select_from(PlayerMatchStat)
        .where(
            PlayerMatchStat.match_id.in_(match_ids),
            (PlayerMatchStat.minutes < 0) | (PlayerMatchStat.minutes > 130),
        )
    )
    if invalid_minutes:
        issues.append(
            {
                "level": "error",
                "check": "player_minutes_range",
                "message": f"{invalid_minutes} player-match rows have invalid minutes.",
            }
        )

    event_count = session.scalar(
        select(func.count(Event.event_id)).where(Event.match_id.in_(match_ids))
    )
    player_match_count = session.scalar(
        select(func.count())
        .select_from(PlayerMatchStat)
        .where(PlayerMatchStat.match_id.in_(match_ids))
    )
    levels = Counter(issue["level"] for issue in issues)
    status = "failed" if levels["error"] else "warning" if levels["warning"] else "passed"
    return {
        "status": status,
        "counts": {
            "matches": len(match_ids),
            "events": event_count or 0,
            "team_match_stats": sum(team_counts.values()),
            "player_match_stats": player_match_count or 0,
        },
        "issues": issues,
    }
