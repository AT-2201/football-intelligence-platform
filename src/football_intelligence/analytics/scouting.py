import math
from collections import Counter, defaultdict
from statistics import pstdev
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
SIMILARITY_BENCHMARK_MINUTES = 450
POSITION_GROUPS = (
    "Goalkeeper",
    "Centre Back",
    "Full Back",
    "Defensive Midfielder",
    "Central Midfielder",
    "Wide Attacker",
    "Forward",
)
NEED_PROFILES = {
    "goal_threat": {
        "label": "More goal threat",
        "metrics": ("goals", "xg", "shots"),
    },
    "passing_involvement": {
        "label": "More passing involvement",
        "metrics": ("passes",),
    },
    "ball_carrying": {
        "label": "More ball carrying",
        "metrics": ("carries",),
    },
    "pressing": {
        "label": "More pressing intensity",
        "metrics": ("pressures", "tackles"),
    },
    "defensive_activity": {
        "label": "More defensive activity",
        "metrics": ("tackles", "interceptions", "pressures"),
    },
}
_POSITION_CACHE: dict[tuple[int, int], dict[int, str]] = {}


def _similarity_deviations(pool: list[dict[str, Any]]) -> dict[str, float]:
    """Return the shared league-wide scale used by every similarity surface."""
    benchmark = [
        record for record in pool if record["minutes"] >= SIMILARITY_BENCHMARK_MINUTES
    ] or pool
    return {
        metric: pstdev(record["per_90"][metric] for record in benchmark) or 1.0
        for metric in VECTOR_METRICS
    }


def _similarity_score(
    first: dict[str, Any],
    second: dict[str, Any],
    deviations: dict[str, float],
) -> float:
    distance = math.sqrt(
        sum(
            (
                (first["per_90"][metric] - second["per_90"][metric])
                / deviations[metric]
            )
            ** 2
            for metric in VECTOR_METRICS
        )
        / len(VECTOR_METRICS)
    )
    return round(100 / (1 + distance), 1)


def position_group(position: str) -> str:
    """Map provider position labels into useful recruitment cohorts."""
    normalized = position.casefold()
    if "goalkeeper" in normalized:
        return "Goalkeeper"
    if "back" in normalized and "center" in normalized:
        return "Centre Back"
    if "back" in normalized:
        return "Full Back"
    if (
        "wing" in normalized
        or "left midfield" in normalized
        or "right midfield" in normalized
    ):
        return "Wide Attacker"
    if "defensive midfield" in normalized:
        return "Defensive Midfielder"
    if "midfield" in normalized:
        return "Central Midfielder"
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
    deviations = _similarity_deviations(pool)
    for candidate in candidates:
        matches, trade_offs = _metric_explanation(target, candidate, deviations)
        candidate["similarity"] = _similarity_score(target, candidate, deviations)
        candidate["match_reasons"] = matches
        candidate["trade_offs"] = trade_offs
        candidate["position_group"] = target_group
    candidates.sort(key=lambda record: record["similarity"], reverse=True)
    target["position_group"] = target_group
    return {
        "target": target,
        "position_group": target_group,
        "similar_players": candidates[:limit],
        "methodology": (
            "Standardized per-90 distance using the shared league-wide 450-minute "
            "benchmark; candidates are restricted to the player's position family."
        ),
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


def _weighted_profile(records: list[dict[str, Any]]) -> dict[str, float]:
    total_minutes = sum(record["minutes"] for record in records) or 1.0
    return {
        metric: sum(record["per_90"][metric] * record["minutes"] for record in records)
        / total_minutes
        for metric in VECTOR_METRICS
    }


def _need_level(core_players: int, top_share: float) -> tuple[str, int]:
    if core_players <= 1 or top_share >= 0.68:
        return "High", 3
    if core_players <= 2 or top_share >= 0.52:
        return "Medium", 2
    return "Covered", 1


def squad_need_records(pool: list[dict[str, Any]], team_id: int) -> dict[str, Any] | None:
    """Describe position coverage and concentration risk for one squad."""
    team_players = [record for record in pool if record["team_id"] == team_id]
    if not team_players:
        return None

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in team_players:
        group = position_group(record["position"])
        if group != "Other":
            groups[group].append(record)

    diagnostics = []
    for group in POSITION_GROUPS:
        players = sorted(groups.get(group, []), key=lambda item: item["minutes"], reverse=True)
        total_minutes = sum(player["minutes"] for player in players)
        core_players = sum(player["minutes"] >= SIMILARITY_BENCHMARK_MINUTES for player in players)
        top_share = (players[0]["minutes"] / total_minutes) if total_minutes else 1.0
        level, priority = _need_level(core_players, top_share)
        if not players:
            reason = "No player has this as a primary recorded position."
        elif core_players <= 1:
            reason = "Only one player reached the 450-minute evidence threshold."
        elif top_share >= 0.68:
            reason = (
                f"{players[0]['player_name']} supplied "
                f"{round(top_share * 100)}% of recorded minutes."
            )
        elif core_players <= 2:
            reason = "Only two players reached the 450-minute evidence threshold."
        else:
            reason = f"{core_players} players supplied meaningful league minutes."
        diagnostics.append(
            {
                "position_group": group,
                "need_level": level,
                "priority": priority,
                "players": len(players),
                "core_players": core_players,
                "total_minutes": round(total_minutes, 1),
                "top_player_share": round(top_share * 100, 1) if players else 100.0,
                "top_player": players[0]["player_name"] if players else None,
                "reason": reason,
            }
        )
    diagnostics.sort(
        key=lambda item: (item["priority"], item["top_player_share"]), reverse=True
    )
    return {
        "team_id": team_id,
        "team_name": team_players[0]["team_name"],
        "players": len(team_players),
        "diagnostics": diagnostics,
        "methodology": (
            "Coverage risk uses primary position, recorded league minutes, a 450-minute "
            "evidence threshold and the share carried by the most-used player."
        ),
    }


def _band(value: float, *, strong: float = 68, good: float = 52) -> str:
    if value >= strong:
        return "Strong"
    if value >= good:
        return "Good"
    return "Developing"


def recommendation_records(
    pool: list[dict[str, Any]],
    team_id: int,
    *,
    scenario: str = "add_depth",
    player_id: int | None = None,
    position: str | None = None,
    need: str = "goal_threat",
    min_minutes: float = 450,
    limit: int = 8,
) -> dict[str, Any] | None:
    """Rank explainable squad-context recommendations for one club."""
    squad = squad_need_records(pool, team_id)
    if squad is None:
        return None
    if scenario not in {"replace_player", "add_depth", "improve_need"}:
        raise ValueError("Scenario must be replace_player, add_depth or improve_need")
    if need not in NEED_PROFILES:
        raise ValueError(f"Unknown performance need: {need}")

    team_players = [record for record in pool if record["team_id"] == team_id]
    target = None
    if scenario == "replace_player":
        target = next(
            (
                record
                for record in team_players
                if record["player_id"] == player_id
            ),
            None,
        )
        if target is None:
            raise LookupError("The selected player is not in this squad")
        selected_group = position_group(target["position"])
    else:
        selected_group = position or squad["diagnostics"][0]["position_group"]
        if selected_group not in POSITION_GROUPS:
            raise ValueError(f"Unknown position group: {selected_group}")

    team_group = [
        record for record in team_players if position_group(record["position"]) == selected_group
    ]
    league_group = [
        record
        for record in pool
        if position_group(record["position"]) == selected_group
        and record["minutes"] >= SIMILARITY_BENCHMARK_MINUTES
    ]
    reference_records = [target] if target else team_group or league_group
    reference_profile = _weighted_profile(reference_records)
    deviations = _similarity_deviations(pool)
    need_metrics = NEED_PROFILES[need]["metrics"]

    candidates = [
        dict(record)
        for record in pool
        if record["team_id"] != team_id
        and record["minutes"] >= min_minutes
        and position_group(record["position"]) == selected_group
    ]
    ranked = []
    for candidate in candidates:
        distance = math.sqrt(
            sum(
                (
                    (candidate["per_90"][metric] - reference_profile[metric])
                    / deviations[metric]
                )
                ** 2
                for metric in VECTOR_METRICS
            )
            / len(VECTOR_METRICS)
        )
        profile_match = 100 / (1 + distance)
        need_z = sum(
            (candidate["per_90"][metric] - reference_profile[metric])
            / deviations[metric]
            for metric in need_metrics
        ) / len(need_metrics)
        need_strength = max(0.0, min(100.0, 50 + need_z * 18))
        evidence = max(0.0, min(100.0, candidate["minutes"] / 2700 * 100))
        if scenario == "replace_player":
            ranking_score = profile_match * 0.68 + need_strength * 0.17 + evidence * 0.15
        elif scenario == "improve_need":
            ranking_score = profile_match * 0.30 + need_strength * 0.55 + evidence * 0.15
        else:
            ranking_score = profile_match * 0.50 + need_strength * 0.25 + evidence * 0.25

        metric_evidence = sorted(
            (
                {
                    "metric": metric,
                    "candidate": round(candidate["per_90"][metric], 2),
                    "squad_reference": round(reference_profile[metric], 2),
                    "difference": round(
                        candidate["per_90"][metric] - reference_profile[metric], 2
                    ),
                }
                for metric in need_metrics
            ),
            key=lambda item: item["difference"],
            reverse=True,
        )
        positive_evidence = [item for item in metric_evidence if item["difference"] >= 0]
        trade_offs = sorted(
            (
                {
                    "metric": metric,
                    "candidate": round(candidate["per_90"][metric], 2),
                    "squad_reference": round(reference_profile[metric], 2),
                    "difference": round(
                        candidate["per_90"][metric] - reference_profile[metric], 2
                    ),
                }
                for metric in VECTOR_METRICS
                if candidate["per_90"][metric] < reference_profile[metric]
            ),
            key=lambda item: (
                item["metric"] not in need_metrics,
                item["difference"] / deviations[item["metric"]],
            ),
        )[:2]
        candidate.update(
            {
                "position_group": selected_group,
                "profile_match": round(profile_match, 1),
                "need_fit": _band(need_strength),
                "evidence_confidence": _band(evidence, strong=80, good=45),
                "why_recommended": (positive_evidence or metric_evidence[:1])[:3],
                "trade_offs": trade_offs,
                "_ranking_score": ranking_score,
            }
        )
        ranked.append(candidate)

    ranked.sort(key=lambda record: record["_ranking_score"], reverse=True)
    for candidate in ranked:
        candidate.pop("_ranking_score", None)

    return {
        "team": {"team_id": team_id, "team_name": squad["team_name"]},
        "scenario": scenario,
        "position_group": selected_group,
        "need": {"key": need, **NEED_PROFILES[need]},
        "reference_player": target,
        "squad_reference": {
            metric: round(value, 2) for metric, value in reference_profile.items()
        },
        "recommendations": ranked[:limit],
        "screening": {
            "minimum_minutes": min_minutes,
            "eligible_candidates": len(ranked),
            "current_club_excluded": True,
        },
        "methodology": (
            "Recommendations combine position-group profile match, the selected squad "
            "need and minutes-based evidence. Rankings are screening guidance, not transfer value."
        ),
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

    benchmark = [
        record for record in pool if record["minutes"] >= SIMILARITY_BENCHMARK_MINUTES
    ] or pool
    deviations = _similarity_deviations(pool)

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
            similarities.append(
                {
                    "player_a_id": first["player_id"],
                    "player_b_id": second["player_id"],
                    "similarity": _similarity_score(first, second, deviations),
                }
            )

    return {
        "players": players,
        "metric_leaders": metric_leaders,
        "similarities": sorted(similarities, key=lambda item: item["similarity"], reverse=True),
        "benchmark": {
            "minimum_minutes": SIMILARITY_BENCHMARK_MINUTES,
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


def squad_needs(
    session: Session,
    competition_id: int,
    season_id: int,
    team_id: int,
) -> dict[str, Any] | None:
    return squad_need_records(
        scouting_pool(session, competition_id, season_id, min_minutes=0), team_id
    )


def recommend_players(
    session: Session,
    competition_id: int,
    season_id: int,
    team_id: int,
    *,
    scenario: str = "add_depth",
    player_id: int | None = None,
    position: str | None = None,
    need: str = "goal_threat",
    min_minutes: float = 450,
    limit: int = 8,
) -> dict[str, Any] | None:
    return recommendation_records(
        scouting_pool(session, competition_id, season_id, min_minutes=0),
        team_id,
        scenario=scenario,
        player_id=player_id,
        position=position,
        need=need,
        min_minutes=min_minutes,
        limit=limit,
    )
