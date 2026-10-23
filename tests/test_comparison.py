import pytest

from football_intelligence.analytics.scouting import (
    VECTOR_METRICS,
    compare_player_records,
    similar_player_records,
)


def _player(player_id: int, name: str, multiplier: float) -> dict:
    per_90 = {
        metric: round((index + 1) * multiplier, 2) for index, metric in enumerate(VECTOR_METRICS)
    }
    return {
        "player_id": player_id,
        "player_name": name,
        "team_id": player_id,
        "team_name": f"Team {player_id}",
        "position": "Centre Forward",
        "appearances": 30,
        "minutes": 2700,
        "totals": {metric: round(value * 30, 2) for metric, value in per_90.items()},
        "per_90": per_90,
    }


def test_comparison_returns_profiles_insights_and_similarity() -> None:
    pool = [
        _player(1, "Alpha", 1.0),
        _player(2, "Bravo", 0.8),
        _player(3, "Charlie", 0.5),
    ]

    result = compare_player_records(pool, [1, 2])

    assert [player["player_id"] for player in result["players"]] == [1, 2]
    assert set(result["players"][0]["relative_profile"]) == set(VECTOR_METRICS)
    assert len(result["players"][0]["strengths"]) == 3
    assert len(result["players"][0]["development_areas"]) == 2
    assert len(result["similarities"]) == 1
    assert 0 < result["similarities"][0]["similarity"] <= 100


def test_comparison_requires_two_to_five_unique_players() -> None:
    with pytest.raises(ValueError, match="between 2 and 5"):
        compare_player_records([_player(1, "Alpha", 1.0)], [1, 1])


def test_role_specific_similarity_explains_matches_and_trade_offs() -> None:
    target = _player(1, "Target", 1.0)
    target["position"] = "Right Center Midfield"
    progressor = _player(2, "Progressor", 1.0)
    progressor["position"] = "Center Attacking Midfield"
    ball_winner = _player(3, "Ball Winner", 1.0)
    ball_winner["position"] = "Left Center Midfield"
    for metric in ("pressures", "tackles", "interceptions"):
        progressor["per_90"][metric] *= 4
    for metric in ("passes", "carries"):
        ball_winner["per_90"][metric] *= 4

    progressive_result = similar_player_records(
        [target, progressor, ball_winner], 1, role="progressor"
    )
    defensive_result = similar_player_records(
        [target, progressor, ball_winner], 1, role="ball_winner"
    )

    assert progressive_result is not None
    assert defensive_result is not None
    assert progressive_result["position_group"] == "Central Midfielder"
    assert progressive_result["similar_players"][0]["player_name"] == "Progressor"
    assert defensive_result["similar_players"][0]["player_name"] == "Ball Winner"
    assert len(progressive_result["similar_players"][0]["match_reasons"]) == 3
    assert len(progressive_result["similar_players"][0]["trade_offs"]) == 2


def test_similarity_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="Unknown similarity role"):
        similar_player_records([_player(1, "Alpha", 1.0)], 1, role="sweeper")
