from football_intelligence.analytics.team_intelligence import (
    _empty_match_bucket,
    _match_metrics,
    _match_style_labels,
)


def test_match_metrics_describe_one_fixture() -> None:
    bucket = _empty_match_bucket()
    bucket.update(
        {
            "passes": 100,
            "completed_passes": 80,
            "pass_length_total": 2000,
            "forward_passes": 55,
            "direct_passes": 25,
            "under_pressure_passes": 20,
            "under_pressure_completed": 14,
            "final_third_passes": 30,
            "opponent_final_third_passes": 20,
            "final_third_entries": 18,
            "entry_channels": {"left": 8, "centre": 4, "right": 6},
            "pressures": 20,
            "pressure_x": [60, 70],
            "high_pressures": 5,
            "counterpressures": 6,
            "defensive_x": [48, 52],
            "defensive_actions_pressing_zone": 10,
            "opponent_passes": 100,
            "opponent_completed_passes": 75,
            "opponent_passes_defensive_zone": 60,
        }
    )
    bucket["possessions"][1] = {"passes": 4, "start": 10, "end": 22}
    bucket["possessions"][2] = {"passes": 6, "start": 30, "end": 48}

    metrics = _match_metrics(bucket, possession_pct=55)

    assert metrics["pass_completion_pct"] == 80
    assert metrics["passes_per_possession"] == 5
    assert metrics["average_possession_duration_sec"] == 15
    assert metrics["field_tilt_pct"] == 60
    assert metrics["ppda_proxy"] == 6


def test_match_style_labels_use_tactical_behaviour() -> None:
    metrics = {
        "possession_pct": 58,
        "average_pass_length_m": 18,
        "average_possession_duration_sec": 16,
        "pressure_height": 67,
        "left_entry_share_pct": 25,
        "centre_entry_share_pct": 45,
        "right_entry_share_pct": 30,
    }

    labels = _match_style_labels(metrics)

    assert labels == [
        "Ball-dominant",
        "Patient build-up",
        "Sustained possession",
        "Central progression",
        "High press",
    ]
