from fastapi.testclient import TestClient

from football_intelligence.main import app


def test_game_day_workspace_builds_all_six_planning_stages() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/game-day/teams/22")

    assert response.status_code == 200
    workspace = response.json()
    assert workspace["team"]["team_name"] == "Leicester City"
    assert len(workspace["plans"]) == 33

    plan = workspace["plans"][0]
    assert plan["training_window"]["prior_matches"] == 5
    assert plan["training_window"]["leakage_safe"] is True
    assert len(plan["predicted_xi"]) == 11
    assert len({player["player_id"] for player in plan["predicted_xi"]}) == 11
    assert round(
        sum(item["probability"] for item in plan["formation_forecast"]["probabilities"]),
        1,
    ) == 100

    assert "inferred_unavailable_player_ids" in plan["availability"]
    assert plan["opponent"]["matches_used"] == 5
    assert plan["opponent"]["strengths"]
    assert plan["opponent"]["weaknesses"]
    assert plan["importance"]["label"] in {"Standard", "Elevated", "High"}
    assert set(plan["substitution_forecast"]) == {"leading", "level", "trailing"}
    assert plan["red_card_contingency"]["supported_positions"] == [
        "Goalkeeper",
        "Defender",
        "Midfielder",
        "Forward",
    ]

    backtest = workspace["backtest"]
    assert backtest["fixtures"] == 33
    assert 0 <= backtest["formation_accuracy_pct"] <= 100
    assert 0 <= backtest["average_correct_starters"] <= 11


def test_unknown_game_day_team_returns_not_found() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/game-day/teams/999999")

    assert response.status_code == 404
