from football_intelligence.analytics.scouting import (
    recommendation_records,
    squad_need_records,
)


def player(
    player_id: int,
    name: str,
    team_id: int,
    team_name: str,
    position: str,
    minutes: float,
    **metrics: float,
) -> dict:
    values = {
        "goals": 0.1,
        "xg": 0.12,
        "shots": 1.2,
        "passes": 25.0,
        "carries": 10.0,
        "pressures": 8.0,
        "tackles": 1.0,
        "interceptions": 0.5,
        **metrics,
    }
    return {
        "player_id": player_id,
        "player_name": name,
        "team_id": team_id,
        "team_name": team_name,
        "position": position,
        "appearances": 30,
        "minutes": minutes,
        "totals": {key: round(value * minutes / 90, 2) for key, value in values.items()},
        "per_90": values,
    }


def sample_pool() -> list[dict]:
    return [
        player(1, "Squad Forward", 10, "Example FC", "Center Forward", 2700, goals=0.45),
        player(2, "Squad Midfielder", 10, "Example FC", "Center Midfield", 2600),
        player(3, "Candidate Forward A", 20, "Rival A", "Center Forward", 2500, goals=0.5),
        player(4, "Candidate Forward B", 30, "Rival B", "Center Forward", 1800, goals=0.25),
        player(5, "Candidate Midfielder", 20, "Rival A", "Center Midfield", 2400),
    ]


def test_squad_needs_identifies_thin_position_coverage() -> None:
    result = squad_need_records(sample_pool(), 10)

    assert result is not None
    forward = next(
        item for item in result["diagnostics"] if item["position_group"] == "Forward"
    )
    assert forward["need_level"] == "High"
    assert forward["core_players"] == 1


def test_recommendations_are_squad_aware_and_explainable() -> None:
    result = recommendation_records(
        sample_pool(),
        10,
        scenario="replace_player",
        player_id=1,
        need="goal_threat",
        min_minutes=450,
    )

    assert result is not None
    assert result["position_group"] == "Forward"
    assert result["reference_player"]["player_id"] == 1
    assert result["recommendations"][0]["player_id"] == 3
    assert all(candidate["team_id"] != 10 for candidate in result["recommendations"])
    assert result["recommendations"][0]["why_recommended"]
    assert "_ranking_score" not in result["recommendations"][0]
