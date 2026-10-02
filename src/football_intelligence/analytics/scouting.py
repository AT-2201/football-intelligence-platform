import math
from collections import Counter, defaultdict
from statistics import fmean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from football_intelligence.models import Player, PlayerSeasonPosition, PlayerSeasonStat, Team

SCOUTING_PROFILES: dict[str, tuple[str, ...]] = {
    "attacking": ("goals", "xg", "shots", "carries"),
    "possession": ("passes", "completed_passes", "carries"),
    "defending": ("pressures", "tackles", "interceptions"),
    "balanced": (
        "goals",
        "xg",
        "shots",
        "passes",
        "carries",
        "pressures",
        "tackles",
        "interceptions",
    ),
}

VECTOR_METRICS = SCOUTING_PROFILES["balanced"]
_POSITION_CACHE: dict[tuple[int, int], dict[int, str]] = {}


def _per_90(row: PlayerSeasonStat, metric: str) -> float:
    return (getattr(row, metric) * 90 / row.minutes) if row.minutes else 0.0


def primary_positions(
    session: Session, competition_id: int, season_id: int
) -> dict[int, str]:
    cache_key = (competition_id, season_id)
    if cache_key in _POSITION_CACHE:
        return _POSITION_CACHE[cache_key]
    rows = session.execute(
        select(
            PlayerSeasonPosition.player_id,
            PlayerSeasonPosition.position_name,
            PlayerSeasonPosition.event_count,
        )
        .where(
            PlayerSeasonPosition.competition_id == competition_id,
            PlayerSeasonPosition.season_id == season_id,
        )
    )
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for player_id, position, count in rows:
        counts[player_id][position] = count
    result = {player_id: values.most_common(1)[0][0] for player_id, values in counts.items()}
    _POSITION_CACHE[cache_key] = result
    return result


def scouting_pool(
    session: Session,
    competition_id: int,
    season_id: int,
    *,
    profile: str = "balanced",
    min_minutes: float = 450,
    position: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(PlayerSeasonStat, Player.player_name, Team.team_name)
        .join(Player, Player.player_id == PlayerSeasonStat.player_id)
        .join(Team, Team.team_id == PlayerSeasonStat.team_id)
        .where(
            PlayerSeasonStat.competition_id == competition_id,
            PlayerSeasonStat.season_id == season_id,
            PlayerSeasonStat.minutes >= min_minutes,
        )
    )
    if search:
        statement = statement.where(Player.player_name.ilike(f"%{search}%"))
    positions = primary_positions(session, competition_id, season_id)
    records: list[dict[str, Any]] = []
    for stat, player_name, team_name in session.execute(statement):
        primary_position = positions.get(stat.player_id, "Unknown")
        if position and position.casefold() not in primary_position.casefold():
            continue
        metrics = {metric: _per_90(stat, metric) for metric in VECTOR_METRICS}
        records.append(
            {
                "player_id": stat.player_id,
                "player_name": player_name,
                "team_id": stat.team_id,
                "team_name": team_name,
                "position": primary_position,
                "appearances": stat.appearances,
                "minutes": round(stat.minutes, 1),
                "totals": {"goals": stat.goals, "xg": round(stat.xg, 2)},
                "per_90": metrics,
            }
        )
    if not records:
        return []

    distributions = {
        metric: sorted(record["per_90"][metric] for record in records)
        for metric in VECTOR_METRICS
    }
    profile_metrics = SCOUTING_PROFILES.get(profile, SCOUTING_PROFILES["balanced"])
    for record in records:
        percentiles = {}
        for metric, values in distributions.items():
            value = record["per_90"][metric]
            rank = sum(item <= value for item in values)
            percentiles[metric] = round(100 * rank / len(values))
            record["per_90"][metric] = round(value, 2)
        record["percentiles"] = percentiles
        record["scouting_score"] = round(
            fmean(percentiles[metric] for metric in profile_metrics), 1
        )
    return sorted(
        records,
        key=lambda record: (record["scouting_score"], record["minutes"]),
        reverse=True,
    )


def similar_players(
    session: Session,
    competition_id: int,
    season_id: int,
    player_id: int,
    *,
    min_minutes: float = 450,
    limit: int = 10,
) -> dict[str, Any] | None:
    pool = scouting_pool(
        session,
        competition_id,
        season_id,
        profile="balanced",
        min_minutes=0,
    )
    target = next((record for record in pool if record["player_id"] == player_id), None)
    if target is None:
        return None
    candidates = [
        record
        for record in pool
        if record["player_id"] != player_id
        and record["minutes"] >= min_minutes
        and record["position"] == target["position"]
    ]
    comparison = candidates + [target]
    means = {
        metric: fmean(record["per_90"][metric] for record in comparison)
        for metric in VECTOR_METRICS
    }
    deviations = {
        metric: pstdev(record["per_90"][metric] for record in comparison) or 1.0
        for metric in VECTOR_METRICS
    }

    def distance(record: dict[str, Any]) -> float:
        return math.sqrt(
            sum(
                (
                    (record["per_90"][metric] - means[metric]) / deviations[metric]
                    - (target["per_90"][metric] - means[metric]) / deviations[metric]
                )
                ** 2
                for metric in VECTOR_METRICS
            )
        )

    for candidate in candidates:
        candidate["similarity"] = round(100 / (1 + distance(candidate)), 1)
    candidates.sort(key=lambda record: record["similarity"], reverse=True)
    return {"target": target, "similar_players": candidates[:limit]}
