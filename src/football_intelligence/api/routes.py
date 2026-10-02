from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, aliased

from football_intelligence.config import Settings, get_settings
from football_intelligence.db import get_db
from football_intelligence.models import (
    CompetitionSeason,
    Match,
    Player,
    PlayerSeasonStat,
    Team,
    TeamMatchStat,
    TeamSeasonStat,
)

router = APIRouter(prefix="/api/v1")


def _scope(settings: Settings) -> tuple[int, int]:
    return settings.statsbomb_competition_id, settings.statsbomb_season_id


@router.get("/competitions/current")
def current_competition(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    competition = db.get(CompetitionSeason, _scope(settings))
    if not competition:
        raise HTTPException(404, "Competition-season has not been ingested")
    return {
        "competition_id": competition.competition_id,
        "season_id": competition.season_id,
        "country": competition.country_name,
        "competition": competition.competition_name,
        "season": competition.season_name,
    }


@router.get("/matches")
def matches(
    team_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    home = aliased(Team)
    away = aliased(Team)
    competition_id, season_id = _scope(settings)
    statement = (
        select(Match, home.team_name, away.team_name)
        .join(home, Match.home_team_id == home.team_id)
        .join(away, Match.away_team_id == away.team_id)
        .where(Match.competition_id == competition_id, Match.season_id == season_id)
        .order_by(Match.match_date, Match.match_id)
        .offset(offset)
        .limit(limit)
    )
    if team_id is not None:
        statement = statement.where(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
        )
    return [
        {
            "match_id": match.match_id,
            "date": match.match_date,
            "match_week": match.match_week,
            "home_team": home_name,
            "away_team": away_name,
            "home_score": match.home_score,
            "away_score": match.away_score,
        }
        for match, home_name, away_name in db.execute(statement)
    ]


@router.get("/matches/{match_id}")
def match_detail(match_id: int, db: Session = Depends(get_db)) -> dict:
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    stats = db.scalars(
        select(TeamMatchStat)
        .where(TeamMatchStat.match_id == match_id)
        .order_by(TeamMatchStat.is_home.desc())
    ).all()
    return {
        "match_id": match.match_id,
        "date": match.match_date,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "team_stats": [
            {
                "team_id": row.team_id,
                "goals": row.goals,
                "shots": row.shots,
                "xg": round(row.xg, 3),
                "passes": row.passes,
                "completed_passes": row.completed_passes,
                "possession_pct": round(row.possession_pct, 1),
            }
            for row in stats
        ],
    }


@router.get("/teams")
def teams(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[dict]:
    competition_id, season_id = _scope(settings)
    rows = db.execute(
        select(TeamSeasonStat, Team.team_name)
        .join(Team, Team.team_id == TeamSeasonStat.team_id)
        .where(
            TeamSeasonStat.competition_id == competition_id,
            TeamSeasonStat.season_id == season_id,
        )
        .order_by(Team.team_name)
    )
    return [
        {
            "team_id": stat.team_id,
            "team_name": name,
            "matches": stat.matches,
            "goals": stat.goals,
            "xg": round(stat.xg, 2),
            "avg_possession_pct": round(stat.avg_possession_pct, 1),
        }
        for stat, name in rows
    ]


@router.get("/teams/{team_id}/matches")
def team_matches(
    team_id: int,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict]:
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    rows = db.scalars(
        select(TeamMatchStat)
        .where(TeamMatchStat.team_id == team_id)
        .order_by(TeamMatchStat.match_id)
        .limit(limit)
    ).all()
    return [
        {
            "match_id": row.match_id,
            "goals": row.goals,
            "shots": row.shots,
            "xg": round(row.xg, 3),
            "possession_pct": round(row.possession_pct, 1),
        }
        for row in rows
    ]


@router.get("/players")
def players(
    team_id: int | None = None,
    min_minutes: float = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    competition_id, season_id = _scope(settings)
    statement = (
        select(PlayerSeasonStat, Player.player_name, Team.team_name)
        .join(Player, Player.player_id == PlayerSeasonStat.player_id)
        .join(Team, Team.team_id == PlayerSeasonStat.team_id)
        .where(
            PlayerSeasonStat.competition_id == competition_id,
            PlayerSeasonStat.season_id == season_id,
            PlayerSeasonStat.minutes >= min_minutes,
        )
        .order_by(desc(PlayerSeasonStat.minutes))
        .limit(limit)
    )
    if team_id is not None:
        statement = statement.where(PlayerSeasonStat.team_id == team_id)
    return [
        _player_payload(stat, name, team_name)
        for stat, name, team_name in db.execute(statement)
    ]


@router.get("/players/{player_id}")
def player_detail(
    player_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    competition_id, season_id = _scope(settings)
    row = db.execute(
        select(PlayerSeasonStat, Player.player_name, Team.team_name)
        .join(Player, Player.player_id == PlayerSeasonStat.player_id)
        .join(Team, Team.team_id == PlayerSeasonStat.team_id)
        .where(
            PlayerSeasonStat.player_id == player_id,
            PlayerSeasonStat.competition_id == competition_id,
            PlayerSeasonStat.season_id == season_id,
        )
        .order_by(desc(PlayerSeasonStat.minutes))
    ).first()
    if not row:
        raise HTTPException(404, "Player not found in the current competition-season")
    return _player_payload(*row)


@router.get("/leaderboards/players")
def player_leaderboard(
    metric: Literal["goals", "xg", "shots", "passes", "carries", "pressures"] = "goals",
    min_minutes: float = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    competition_id, season_id = _scope(settings)
    column = getattr(PlayerSeasonStat, metric)
    rows = db.execute(
        select(PlayerSeasonStat, Player.player_name, Team.team_name)
        .join(Player, Player.player_id == PlayerSeasonStat.player_id)
        .join(Team, Team.team_id == PlayerSeasonStat.team_id)
        .where(
            PlayerSeasonStat.competition_id == competition_id,
            PlayerSeasonStat.season_id == season_id,
            PlayerSeasonStat.minutes >= min_minutes,
        )
        .order_by(desc(column), desc(PlayerSeasonStat.minutes))
        .limit(limit)
    )
    return [_player_payload(stat, name, team_name) for stat, name, team_name in rows]


def _player_payload(stat: PlayerSeasonStat, name: str, team_name: str) -> dict:
    nineties = stat.minutes / 90
    return {
        "player_id": stat.player_id,
        "player_name": name,
        "team_id": stat.team_id,
        "team_name": team_name,
        "appearances": stat.appearances,
        "minutes": round(stat.minutes, 1),
        "goals": stat.goals,
        "shots": stat.shots,
        "xg": round(stat.xg, 3),
        "passes": stat.passes,
        "completed_passes": stat.completed_passes,
        "carries": stat.carries,
        "pressures": stat.pressures,
        "tackles": stat.tackles,
        "interceptions": stat.interceptions,
        "per_90": {
            key: round(getattr(stat, key) / nineties, 2) if nineties else 0
            for key in (
                "goals",
                "shots",
                "xg",
                "passes",
                "carries",
                "pressures",
                "tackles",
                "interceptions",
            )
        },
    }
