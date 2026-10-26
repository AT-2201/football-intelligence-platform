import math
from collections import Counter, defaultdict
from statistics import fmean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from football_intelligence.models import Player, PlayerSeasonPosition, PlayerSeasonStat, Team

VECTOR_METRICS = (
    "goals",
    "xg",
    "shots",
    "passes",
    "carries",
    "pressures",
    "tackles",
    "interceptions",
)
_POSITION_CACHE: dict[tuple[int, int], dict[int, str]] = {}


def position_group(position: str) -> str:
    """Map provider position labels into useful recruitment cohorts."""
    normalized = position.casefold()
    if "goalkeeper" in normalized:
        return "Goalkeeper"
    if "back" in normalized and "center" in normalized:
        return "Centre Back"
    if "back" in normalized:
        return "Full Back"
    if "defensive midfield" in normalized:
        return "Defensive Midfielder"
    if "midfield" in normalized:
        return "Central Midfielder"
    if "wing" in normalized:
        return "Wide Attacker"
    if "forward" in normalized:
        return "Forward"
    return "Other"


def _metric_explanation(
    target: dict[str, Any],
    candidate: dict[str, Any],
    deviations: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    comparisons = []
    for metric in VECTOR_METRICS:
        target_value = target["per_90"][metric]
        candidate_value = candidate["per_90"][metric]
        standardized_gap = abs(candidate_value - target_value) / deviations[metric]
        comparisons.append(
            {
                "metric": metric,
                "target": round(target_value, 2),
                "candidate": round(candidate_value, 2),
                "difference": round(candidate_value - target_value, 2),
                "standardized_gap": standardized_gap,
            }
        )
    matches = sorted(comparisons, key=lambda item: item["standardized_gap"])[:3]
    trade_offs = sorted(
        comparisons, key=lambda item: item["standardized_gap"], reverse=True
    )[:2]
    for item in matches + trade_offs:
        item.pop("standardized_gap", None)
    return matches, trade_offs


def similar_player_records(
    pool: list[dict[str, Any]],
    player_id: int,
    *,
    min_minutes: float = 450,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Rank position-aware replacements and explain the strongest matches and trade-offs."""
    target = next((dict(record) for record in pool if record["player_id"] == player_id), None)
    if target is None:
        return None

    target_group = position_group(target["position"])
    candidates = [
        dict(record)
        for record in pool
        if record["player_id"] != player_id
        and record["minutes"] >= min_minutes
        and position_group(record["position"]) == target_group
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
    for candidate in candidates:
        distance = math.sqrt(
            sum(
                (
                    (candidate["per_90"][metric] - means[metric]) / deviations[metric]
                    - (target["per_90"][metric] - means[metric]) / deviations[metric]
                )
                ** 2
                for metric in VECTOR_METRICS
            )
            / len(VECTOR_METRICS)
        )
        matches, trade_offs = _metric_explanation(target, candidate, deviations)
        candidate["similarity"] = round(100 / (1 + distance), 1)
        candidate["match_reasons"] = matches
        candidate["trade_offs"] = trade_offs
        candidate["position_group"] = target_group
    candidates.sort(key=lambda record: record["similarity"], reverse=True)
    target["position_group"] = target_group
    return {
        "target": target,
        "position_group": target_group,
        "similar_players": candidates[:limit],
        "methodology": "Standardized per-90 distance within the player's position family.",
    }


def replacement_player_records(
    pool: list[dict[str, Any]],
    player_id: int,
    *,
    min_minutes: float = 450,
    limit: int = 10,
    exclude_same_team: bool = False,
    min_similarity: float = 0,
) -> dict[str, Any] | None:
    """Build a decision-ready shortlist from the position-aware similarity model."""
    result = similar_player_records(
        pool,
        player_id,
        min_minutes=min_minutes,
        limit=len(pool),
    )
    if result is None:
        return None

    target = result["target"]
    candidates = [
        candidate
        for candidate in result["similar_players"]
        if candidate["similarity"] >= min_similarity
        and (not exclude_same_team or candidate["team_id"] != target["team_id"])
    ]
    for candidate in candidates:
        candidate["minutes_difference"] = round(candidate["minutes"] - target["minutes"], 1)

    return {
        "target": target,
        "position_group": result["position_group"],
        "replacement_candidates": candidates[:limit],
        "screening": {
            "minimum_minutes": min_minutes,
            "minimum_similarity": min_similarity,
            "same_team_excluded": exclude_same_team,
            "eligible_candidates": len(candidates),
        },
        "methodology": result["methodology"],
    }


def compare_player_records(pool: list[dict[str, Any]], player_ids: list[int]) -> dict[str, Any]:
    """Build a direct-stat comparison for two to five selected players."""
    unique_ids = list(dict.fromkeys(player_ids))
    if not 2 <= len(unique_ids) <= 5:
        raise ValueError("Select between 2 and 5 different players")

    by_id = {record["player_id"]: record for record in pool}
    missing = [player_id for player_id in unique_ids if player_id not in by_id]
    if missing:
        raise LookupError(f"Players not found in this competition-season: {missing}")

    benchmark = [record for record in pool if record["minutes"] >= 450] or pool
    means = {
        metric: fmean(record["per_90"][metric] for record in benchmark) for metric in VECTOR_METRICS
    }
    deviations = {
        metric: pstdev(record["per_90"][metric] for record in benchmark) or 1.0
        for metric in VECTOR_METRICS
    }

    players = []
    for player_id in unique_ids:
        record = dict(by_id[player_id])
        players.append(record)

    metric_leaders = {}
    for metric in VECTOR_METRICS:
        best_value = max(player["per_90"][metric] for player in players)
        metric_leaders[metric] = {
            "value": best_value,
            "player_ids": [
                player["player_id"]
                for player in players
                if player["per_90"][metric] == best_value
            ],
        }

    similarities = []
    for index, first in enumerate(players):
        for second in players[index + 1 :]:
            distance = math.sqrt(
                sum(
                    (
                        (first["per_90"][metric] - means[metric]) / deviations[metric]
                        - (second["per_90"][metric] - means[metric]) / deviations[metric]
                    )
                    ** 2
                    for metric in VECTOR_METRICS
                )
                / len(VECTOR_METRICS)
            )
            similarities.append(
                {
                    "player_a_id": first["player_id"],
                    "player_b_id": second["player_id"],
                    "similarity": round(100 / (1 + distance), 1),
                }
            )

    return {
        "players": players,
        "metric_leaders": metric_leaders,
        "similarities": sorted(similarities, key=lambda item: item["similarity"], reverse=True),
        "benchmark": {
            "minimum_minutes": 450,
            "players": len(benchmark),
            "method": "Direct season totals and per-90 rates",
            "visual_scale": "Bars are scaled only against the selected players.",
        },
    }


def _per_90(row: PlayerSeasonStat, metric: str) -> float:
    return (getattr(row, metric) * 90 / row.minutes) if row.minutes else 0.0


def primary_positions(session: Session, competition_id: int, season_id: int) -> dict[int, str]:
    cache_key = (competition_id, season_id)
    if cache_key in _POSITION_CACHE:
        return _POSITION_CACHE[cache_key]
    rows = session.execute(
        select(
            PlayerSeasonPosition.player_id,
            PlayerSeasonPosition.position_name,
            PlayerSeasonPosition.event_count,
        ).where(
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
                "totals": {
                    metric: round(getattr(stat, metric), 2)
                    if metric == "xg"
                    else getattr(stat, metric)
                    for metric in VECTOR_METRICS
                },
                "per_90": metrics,
            }
        )
    if not records:
        return []
    for record in records:
        record["per_90"] = {metric: round(value, 2) for metric, value in record["per_90"].items()}
    return sorted(records, key=lambda record: record["minutes"], reverse=True)


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
        min_minutes=0,
    )
    return similar_player_records(
        pool,
        player_id,
        min_minutes=min_minutes,
        limit=limit,
    )


def replacement_players(
    session: Session,
    competition_id: int,
    season_id: int,
    player_id: int,
    *,
    min_minutes: float = 450,
    limit: int = 10,
    exclude_same_team: bool = False,
    min_similarity: float = 0,
) -> dict[str, Any] | None:
    pool = scouting_pool(session, competition_id, season_id, min_minutes=0)
    return replacement_player_records(
        pool,
        player_id,
        min_minutes=min_minutes,
        limit=limit,
        exclude_same_team=exclude_same_team,
        min_similarity=min_similarity,
    )


def compare_players(
    session: Session,
    competition_id: int,
    season_id: int,
    player_ids: list[int],
) -> dict[str, Any]:
    return compare_player_records(
        scouting_pool(session, competition_id, season_id, min_minutes=0), player_ids
    )
