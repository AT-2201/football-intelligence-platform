from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from football_intelligence.db import Base


class CompetitionSeason(Base):
    __tablename__ = "competition_seasons"

    competition_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_name: Mapped[str] = mapped_column(String(100))
    competition_name: Mapped[str] = mapped_column(String(150), index=True)
    competition_gender: Mapped[str | None] = mapped_column(String(20))
    season_name: Mapped[str] = mapped_column(String(30))
    match_available: Mapped[datetime | None] = mapped_column(DateTime)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_name: Mapped[str] = mapped_column(String(150), index=True)
    country_name: Mapped[str | None] = mapped_column(String(100))


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_name: Mapped[str] = mapped_column(String(200), index=True)
    player_nickname: Mapped[str | None] = mapped_column(String(200))
    country_name: Mapped[str | None] = mapped_column(String(100))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_competition_season", "competition_id", "season_id"),
        Index("ix_matches_teams", "home_team_id", "away_team_id"),
    )

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(Integer)
    season_id: Mapped[int] = mapped_column(Integer)
    match_date: Mapped[date] = mapped_column(Date, index=True)
    kick_off: Mapped[time | None] = mapped_column(Time)
    match_week: Mapped[int | None] = mapped_column(Integer)
    stadium_name: Mapped[str | None] = mapped_column(String(200))
    referee_name: Mapped[str | None] = mapped_column(String(200))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), index=True)
    home_score: Mapped[int] = mapped_column(Integer)
    away_score: Mapped[int] = mapped_column(Integer)
    match_status: Mapped[str | None] = mapped_column(String(50))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Lineup(Base):
    __tablename__ = "lineups"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id"), primary_key=True)
    jersey_number: Mapped[int | None] = mapped_column(Integer)
    positions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_match_team", "match_id", "team_id"),
        Index("ix_events_match_player", "match_id", "player_id"),
        Index("ix_events_type", "type_name"),
    )

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id"), index=True)
    event_index: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[str] = mapped_column(String(20))
    minute: Mapped[int] = mapped_column(Integer)
    second: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    type_name: Mapped[str] = mapped_column(String(100))
    possession: Mapped[int | None] = mapped_column(Integer)
    possession_team_id: Mapped[int | None] = mapped_column(Integer)
    play_pattern_name: Mapped[str | None] = mapped_column(String(100))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.team_id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.player_id"))
    position_name: Mapped[str | None] = mapped_column(String(100))
    location_x: Mapped[float | None] = mapped_column(Float)
    location_y: Mapped[float | None] = mapped_column(Float)
    under_pressure: Mapped[bool] = mapped_column(Boolean, default=False)
    counterpress: Mapped[bool] = mapped_column(Boolean, default=False)
    pass_recipient_id: Mapped[int | None] = mapped_column(Integer)
    pass_outcome_name: Mapped[str | None] = mapped_column(String(100))
    pass_type_name: Mapped[str | None] = mapped_column(String(100))
    pass_length: Mapped[float | None] = mapped_column(Float)
    pass_angle: Mapped[float | None] = mapped_column(Float)
    pass_end_x: Mapped[float | None] = mapped_column(Float)
    pass_end_y: Mapped[float | None] = mapped_column(Float)
    pass_cross: Mapped[bool] = mapped_column(Boolean, default=False)
    pass_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    shot_outcome_name: Mapped[str | None] = mapped_column(String(100))
    shot_type_name: Mapped[str | None] = mapped_column(String(100))
    shot_body_part_name: Mapped[str | None] = mapped_column(String(100))
    shot_statsbomb_xg: Mapped[float | None] = mapped_column(Float)
    shot_end_x: Mapped[float | None] = mapped_column(Float)
    shot_end_y: Mapped[float | None] = mapped_column(Float)
    carry_end_x: Mapped[float | None] = mapped_column(Float)
    carry_end_y: Mapped[float | None] = mapped_column(Float)
    duel_type_name: Mapped[str | None] = mapped_column(String(100))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)


class TeamMatchStat(Base):
    __tablename__ = "team_match_stats"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), primary_key=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    is_home: Mapped[bool] = mapped_column(Boolean)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    xg: Mapped[float] = mapped_column(Float, default=0)
    passes: Mapped[int] = mapped_column(Integer, default=0)
    completed_passes: Mapped[int] = mapped_column(Integer, default=0)
    possession_pct: Mapped[float] = mapped_column(Float, default=0)


class PlayerMatchStat(Base):
    __tablename__ = "player_match_stats"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.match_id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    minutes: Mapped[float] = mapped_column(Float, default=0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    xg: Mapped[float] = mapped_column(Float, default=0)
    passes: Mapped[int] = mapped_column(Integer, default=0)
    completed_passes: Mapped[int] = mapped_column(Integer, default=0)
    carries: Mapped[int] = mapped_column(Integer, default=0)
    pressures: Mapped[int] = mapped_column(Integer, default=0)
    tackles: Mapped[int] = mapped_column(Integer, default=0)
    interceptions: Mapped[int] = mapped_column(Integer, default=0)


class TeamSeasonStat(Base):
    __tablename__ = "team_season_stats"
    __table_args__ = (
        UniqueConstraint("competition_id", "season_id", "team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), index=True)
    matches: Mapped[int] = mapped_column(Integer)
    goals: Mapped[int] = mapped_column(Integer)
    shots: Mapped[int] = mapped_column(Integer)
    xg: Mapped[float] = mapped_column(Float)
    passes: Mapped[int] = mapped_column(Integer)
    completed_passes: Mapped[int] = mapped_column(Integer)
    avg_possession_pct: Mapped[float] = mapped_column(Float)


class PlayerSeasonStat(Base):
    __tablename__ = "player_season_stats"
    __table_args__ = (
        UniqueConstraint("competition_id", "season_id", "player_id", "team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.player_id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), index=True)
    appearances: Mapped[int] = mapped_column(Integer)
    minutes: Mapped[float] = mapped_column(Float)
    shots: Mapped[int] = mapped_column(Integer)
    goals: Mapped[int] = mapped_column(Integer)
    xg: Mapped[float] = mapped_column(Float)
    passes: Mapped[int] = mapped_column(Integer)
    completed_passes: Mapped[int] = mapped_column(Integer)
    carries: Mapped[int] = mapped_column(Integer)
    pressures: Mapped[int] = mapped_column(Integer)
    tackles: Mapped[int] = mapped_column(Integer)
    interceptions: Mapped[int] = mapped_column(Integer)


class PlayerSeasonPosition(Base):
    __tablename__ = "player_season_positions"

    competition_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.player_id"), primary_key=True, index=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), primary_key=True)
    position_name: Mapped[str] = mapped_column(String(100))
    event_count: Mapped[int] = mapped_column(Integer)


class SeasonSummary(Base):
    __tablename__ = "season_summaries"

    competition_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    matches: Mapped[int] = mapped_column(Integer)
    teams: Mapped[int] = mapped_column(Integer)
    players: Mapped[int] = mapped_column(Integer)
    events: Mapped[int] = mapped_column(Integer)
    goals: Mapped[int] = mapped_column(Integer)
