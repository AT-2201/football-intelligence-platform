from football_intelligence.ingestion.service import event_row


def test_event_row_flattens_shot() -> None:
    payload = {
        "id": "event-1",
        "index": 12,
        "period": 1,
        "timestamp": "00:10:12.000",
        "minute": 10,
        "second": 12,
        "type": {"id": 16, "name": "Shot"},
        "team": {"id": 1, "name": "Home"},
        "player": {"id": 9, "name": "Striker"},
        "location": [102.0, 40.0],
        "shot": {
            "statsbomb_xg": 0.31,
            "outcome": {"id": 97, "name": "Goal"},
            "end_location": [120.0, 40.0, 1.0],
        },
    }

    row = event_row(100, payload)

    assert row["match_id"] == 100
    assert row["type_name"] == "Shot"
    assert row["shot_outcome_name"] == "Goal"
    assert row["shot_statsbomb_xg"] == 0.31
    assert row["location_x"] == 102.0

