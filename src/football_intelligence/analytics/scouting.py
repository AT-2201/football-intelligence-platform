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
ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "balanced": {
        "label": "Balanced profile",
        "description": "Weights attacking, possession and defensive output evenly.",
        "weights": {metric: 1.0 for metric in VECTOR_METRICS},
    },
    "progressor": {
        "label": "Ball progressor",
        "description": "Prioritizes passing volume and carrying contribution.",
        "weights": {
            "goals": 0.35,
            "xg": 0.45,
            "shots": 0.35,
            "passes": 2.5,
            "carries": 2.5,
            "pressures": 0.6,
            "tackles": 0.4,
            "interceptions": 0.4,
        },
    },
    "creator": {
        "label": "Possession creator",
        "description": "Emphasizes passing, carrying and attacking involvement.",
        "weights": {
            "goals": 0.8,
            "xg": 1.0,
            "shots": 0.7,
            "passes": 2.3,
            "carries": 2.0,
            "pressures": 0.7,
            "tackles": 0.35,
            "interceptions": 0.35,
        },
    },
    "ball_winner": {
        "label": "Ball winner",
        "description": "Prioritizes pressure, tackling and interception activity.",
        "weights": {
            "goals": 0.25,
            "xg": 0.25,
            "shots": 0.25,
            "passes": 0.8,
            "carries": 0.45,
            "pressures": 2.2,
            "tackles": 2.5,
            "interceptions": 2.5,
        },
    },
    "goal_threat": {
        "label": "Goal threat",
        "description": "Emphasizes shooting volume, expected goals and goals.",
        "weights": {
            "goals": 2.5,
            "xg": 2.5,
            "shots": 2.2,
            "passes": 0.35,
            "carries": 1.0,
            "pressures": 0.55,
            "tackles": 0.2,
            "interceptions": 0.2,
        },
    },
}
_POSITION_CACHE: dict[tuple[int, int], dict[int, str]] = {}


def _percentile(value: float, values: list[float]) -> int:
    return round(100 * sum(item <= value for item in values) / len(values))


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
    weights: dict[str, float],
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
                "weighted_gap": standardized_gap * math.sqrt(weights[metric]),
            }
        )
    role_metrics = [item for item in comparisons if weights[item["metric"]] >= 0.6]
    matches = sorted(role_metrics, key=lambda item: item["weighted_gap"])[:3]
    trade_offs = sorted(comparisons, key=lambda item: item["weighted_gap"], reverse=True)[:2]
    for item in matches + trade_offs:
        item.pop("weighted_gap", None)
    return matches, trade_offs


def similar_player_records(
    pool: list[dict[str, Any]],
    player_id: int,
    *,
    min_minutes: float = 450,
    limit: int = 10,
    role: str = "balanced",
) -> dict[str, Any] | None:
    """Rank position-aware replacements and explain the strongest matches and trade-offs."""
    if role not in ROLE_PROFILES:
        raise ValueError(f"Unknown similarity role: {role}")
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
    profile = ROLE_PROFILES[role]
    weights = profile["weights"]
    weight_total = sum(weights.values())

    for candidate in candidates:
        distance = math.sqrt(
            sum(
                weights[metric]
                * (
                    (candidate["per_90"][metric] - means[metric]) / deviations[metric]
                    - (target["per_90"][metric] - means[metric]) / deviations[metric]
                )
                ** 2
                for metric in VECTOR_METRICS
            )
            / weight_total
        )
        matches, trade_offs = _metric_explanation(target, candidate, deviations, weights)
        candidate["similarity"] = round(100 / (1 + distance), 1)
        candidate["match_reasons"] = matches
        candidate["trade_offs"] = trade_offs
        candidate["position_group"] = target_group
    candidates.sort(key=lambda record: record["similarity"], reverse=True)
    target["position_group"] = target_group
    priority_metrics = sorted(VECTOR_METRICS, key=lambda metric: weights[metric], reverse=True)[:3]
    return {
        "target": target,
        "role": {
            "key": role,
            "label": profile["label"],
            "description": profile["description"],
            "priority_metrics": priority_metrics,
        },
        "position_group": target_group,
        "similar_players": candidates[:limit],
        "methodology": "Weighted per-90 distance within the player's position family.",
    }


def compare_player_records(pool: list[dict[str, Any]], player_ids: list[int]) -> dict[str, Any]:
    """Build a league-normalized comparison for two to five selected players."""
    unique_ids = list(dict.fromkeys(player_ids))
    if not 2 <= len(unique_ids) <= 5:
        raise ValueError("Select between 2 and 5 different players")

    by_id = {record["player_id"]: record for record in pool}
    missing = [player_id for player_id in unique_ids if player_id not in by_id]
    if missing:
        raise LookupError(f"Players not found in this competition-season: {missing}")

    benchmark = [record for record in pool if record["minutes"] >= 450] or pool
    distributions = {
        metric: sorted(record["per_90"][metric] for record in benchmark)
        for metric in VECTOR_METRICS
    }
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
        relative_profile = {
            metric: _percentile(record["per_90"][metric], distributions[metric])
            for metric in VECTOR_METRICS
        }
        ranked = sorted(VECTOR_METRICS, key=lambda metric: relative_profile[metric], reverse=True)
        record["relative_profile"] = relative_profile
        record["strengths"] = ranked[:3]
        record["development_areas"] = ranked[-2:]
        players.append(record)

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
        "similarities": sorted(similarities, key=lambda item: item["similarity"], reverse=True),
        "benchmark": {
            "minimum_minutes": 450,
            "players": len(benchmark),
            "method": "League-relative per-90 profile",
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
    role: str = "balanced",
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
        role=role,
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
