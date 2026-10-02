from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from football_intelligence.analytics.transform import transform_season
from football_intelligence.db import Base
from football_intelligence.models import Event, Lineup, Match, Player, PlayerSeasonStat, Team


def test_transform_builds_player_season_stats() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Team(team_id=1, team_name="Home"),
                Team(team_id=2, team_name="Away"),
                Player(player_id=9, player_name="Striker"),
                Match(
                    match_id=100,
                    competition_id=2,
                    season_id=27,
                    match_date=date(2015, 8, 8),
                    home_team_id=1,
                    away_team_id=2,
                    home_score=1,
                    away_score=0,
                    raw_data={},
                ),
                Lineup(
                    match_id=100,
                    team_id=1,
                    player_id=9,
                    positions=[{"from": "00:00", "to": "90:00"}],
                    cards=[],
                    raw_data={},
                ),
                Event(
                    event_id="event-1",
                    match_id=100,
                    event_index=1,
                    period=1,
                    timestamp="00:10:00.000",
                    minute=10,
                    second=0,
                    type_name="Shot",
                    possession_team_id=1,
                    team_id=1,
                    player_id=9,
                    shot_outcome_name="Goal",
                    shot_statsbomb_xg=0.3,
                    raw_data={},
                ),
            ]
        )
        session.commit()

        result = transform_season(session, 2, 27)
        player_stat = session.query(PlayerSeasonStat).one()

    assert result["matches"] == 1
    assert player_stat.minutes == 90
    assert player_stat.goals == 1
    assert player_stat.xg == 0.3

