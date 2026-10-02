from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from football_intelligence.analytics.scouting import (
    SCOUTING_PROFILES,
    scouting_pool,
    similar_players,
)
from football_intelligence.config import Settings, get_settings
from football_intelligence.db import get_db
from football_intelligence.models import (
    CompetitionSeason,
    Event,
    Match,
    Player,
    PlayerMatchStat,
    PlayerSeasonStat,
    SeasonSummary,
    Team,
    TeamSeasonStat,
)

router = APIRouter(prefix="/api/v1")


@router.get("/overview")
def overview(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict:
    scope = (settings.statsbomb_competition_id, settings.statsbomb_season_id)
    competition = db.get(CompetitionSeason, scope)
    summary = db.get(SeasonSummary, scope)
    leaders = db.execute(
        select(Player.player_id, Player.player_name, Team.team_name, PlayerSeasonStat.goals)
        .join(PlayerSeasonStat, PlayerSeasonStat.player_id == Player.player_id)
        .join(Team, Team.team_id == PlayerSeasonStat.team_id)
        .where(
            PlayerSeasonStat.competition_id == scope[0],
            PlayerSeasonStat.season_id == scope[1],
        )
        .order_by(PlayerSeasonStat.goals.desc(), PlayerSeasonStat.minutes.desc())
        .limit(5)
    )
    return {
        "competition": {
            "name": competition.competition_name if competition else "Premier League",
            "season": competition.season_name if competition else "2015/2016",
            "country": competition.country_name if competition else "England",
        },
        "coverage": {
            "matches": summary.matches if summary else 0,
            "expected_matches": 380,
            "teams": summary.teams if summary else 0,
            "players": summary.players if summary else 0,
            "events": summary.events if summary else 0,
            "goals": summary.goals if summary else 0,
        },
        "top_scorers": [
            {
                "player_id": player_id,
                "player_name": name,
                "team_name": team_name,
                "goals": player_goals,
            }
            for player_id, name, team_name, player_goals in leaders
        ],
    }


@router.get("/standings")
def standings(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[dict]:
    scope = (settings.statsbomb_competition_id, settings.statsbomb_season_id)
    teams = {
        team.team_id: {
            "team_id": team.team_id,
            "team_name": team.team_name,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "gf": 0,
            "ga": 0,
            "points": 0,
        }
        for team in db.scalars(
            select(Team)
            .join(TeamSeasonStat, TeamSeasonStat.team_id == Team.team_id)
            .where(
                TeamSeasonStat.competition_id == scope[0],
                TeamSeasonStat.season_id == scope[1],
            )
        )
    }
    matches = db.scalars(
        select(Match).where(Match.competition_id == scope[0], Match.season_id == scope[1])
    )
    for match in matches:
        home = teams.get(match.home_team_id)
        away = teams.get(match.away_team_id)
        if not home or not away:
            continue
        home["played"] += 1
        away["played"] += 1
        home["gf"] += match.home_score
        home["ga"] += match.away_score
        away["gf"] += match.away_score
        away["ga"] += match.home_score
        if match.home_score > match.away_score:
            home["won"] += 1
            away["lost"] += 1
            home["points"] += 3
        elif match.home_score < match.away_score:
            away["won"] += 1
            home["lost"] += 1
            away["points"] += 3
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    table = list(teams.values())
    for row in table:
        row["goal_difference"] = row["gf"] - row["ga"]
    table.sort(key=lambda row: (row["points"], row["goal_difference"], row["gf"]), reverse=True)
    for index, row in enumerate(table, 1):
        row["position"] = index
    return table


@router.get("/matches/{match_id}/events")
def match_events(
    match_id: int,
    event_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    if not db.get(Match, match_id):
        raise HTTPException(404, "Match not found")
    statement = select(Event).where(Event.match_id == match_id).order_by(Event.event_index)
    if event_type:
        statement = statement.where(Event.type_name == event_type)
    return [
        {
            "event_id": event.event_id,
            "index": event.event_index,
            "minute": event.minute,
            "second": event.second,
            "type": event.type_name,
            "team_id": event.team_id,
            "player_id": event.player_id,
            "x": event.location_x,
            "y": event.location_y,
            "end_x": event.shot_end_x or event.pass_end_x or event.carry_end_x,
            "end_y": event.shot_end_y or event.pass_end_y or event.carry_end_y,
            "outcome": event.shot_outcome_name or event.pass_outcome_name,
            "xg": event.shot_statsbomb_xg,
        }
        for event in db.scalars(statement)
    ]


@router.get("/matches/{match_id}/players")
def match_players(match_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(PlayerMatchStat, Player.player_name, Team.team_name)
        .join(Player, Player.player_id == PlayerMatchStat.player_id)
        .join(Team, Team.team_id == PlayerMatchStat.team_id)
        .where(PlayerMatchStat.match_id == match_id, PlayerMatchStat.minutes > 0)
        .order_by(PlayerMatchStat.team_id, PlayerMatchStat.minutes.desc())
    )
    return [
        {
            "player_id": stat.player_id,
            "player_name": name,
            "team_id": stat.team_id,
            "team_name": team_name,
            "minutes": round(stat.minutes, 1),
            "goals": stat.goals,
            "shots": stat.shots,
            "xg": round(stat.xg, 3),
            "passes": stat.passes,
            "completed_passes": stat.completed_passes,
            "pressures": stat.pressures,
            "tackles": stat.tackles,
        }
        for stat, name, team_name in rows
    ]


@router.get("/players/{player_id}/matches")
def player_matches(
    player_id: int,
    limit: int = Query(38, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(PlayerMatchStat, Match.match_date)
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(PlayerMatchStat.player_id == player_id, PlayerMatchStat.minutes > 0)
        .order_by(Match.match_date.desc())
        .limit(limit)
    )
    return [
        {
            "match_id": stat.match_id,
            "date": match_date,
            "minutes": round(stat.minutes, 1),
            "goals": stat.goals,
            "shots": stat.shots,
            "xg": round(stat.xg, 3),
            "passes": stat.passes,
            "pressures": stat.pressures,
        }
        for stat, match_date in rows
    ]


@router.get("/scouting/profiles")
def scouting_profiles() -> dict[str, tuple[str, ...]]:
    return SCOUTING_PROFILES


@router.get("/scouting/players")
def scouting_players(
    profile: str = Query("balanced"),
    min_minutes: float = Query(450, ge=0),
    position: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if profile not in SCOUTING_PROFILES:
        raise HTTPException(400, f"Unknown profile: {profile}")
    return scouting_pool(
        db,
        settings.statsbomb_competition_id,
        settings.statsbomb_season_id,
        profile=profile,
        min_minutes=min_minutes,
        position=position,
        search=search,
    )[:limit]


@router.get("/scouting/players/{player_id}/similar")
def player_similarity(
    player_id: int,
    min_minutes: float = Query(450, ge=0),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    result = similar_players(
        db,
        settings.statsbomb_competition_id,
        settings.statsbomb_season_id,
        player_id,
        min_minutes=min_minutes,
        limit=limit,
    )
    if result is None:
        raise HTTPException(404, "Player not found in the current competition-season")
    return result
