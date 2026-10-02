from datetime import datetime
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from football_intelligence.ingestion.client import StatsBombOpenDataClient
from football_intelligence.models import CompetitionSeason, Event, Lineup, Match, Player, Team


def _name(value: dict[str, Any] | None) -> str | None:
    return value.get("name") if value else None


def _id(value: dict[str, Any] | None) -> int | None:
    return value.get("id") if value else None


def _xy(value: list[float] | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    return value[0], value[1] if len(value) > 1 else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def event_row(match_id: int, event: dict[str, Any]) -> dict[str, Any]:
    pass_data = event.get("pass", {})
    shot = event.get("shot", {})
    carry = event.get("carry", {})
    duel = event.get("duel", {})
    location_x, location_y = _xy(event.get("location"))
    pass_end_x, pass_end_y = _xy(pass_data.get("end_location"))
    shot_end_x, shot_end_y = _xy(shot.get("end_location"))
    carry_end_x, carry_end_y = _xy(carry.get("end_location"))
    return {
        "event_id": event["id"],
        "match_id": match_id,
        "event_index": event["index"],
        "period": event["period"],
        "timestamp": event["timestamp"],
        "minute": event["minute"],
        "second": event["second"],
        "duration": event.get("duration"),
        "type_name": _name(event.get("type")) or "Unknown",
        "possession": event.get("possession"),
        "possession_team_id": _id(event.get("possession_team")),
        "play_pattern_name": _name(event.get("play_pattern")),
        "team_id": _id(event.get("team")),
        "player_id": _id(event.get("player")),
        "position_name": _name(event.get("position")),
        "location_x": location_x,
        "location_y": location_y,
        "under_pressure": event.get("under_pressure", False),
        "counterpress": event.get("counterpress", False),
        "pass_recipient_id": _id(pass_data.get("recipient")),
        "pass_outcome_name": _name(pass_data.get("outcome")),
        "pass_type_name": _name(pass_data.get("type")),
        "pass_length": pass_data.get("length"),
        "pass_angle": pass_data.get("angle"),
        "pass_end_x": pass_end_x,
        "pass_end_y": pass_end_y,
        "pass_cross": pass_data.get("cross", False),
        "pass_switch": pass_data.get("switch", False),
        "shot_outcome_name": _name(shot.get("outcome")),
        "shot_type_name": _name(shot.get("type")),
        "shot_body_part_name": _name(shot.get("body_part")),
        "shot_statsbomb_xg": shot.get("statsbomb_xg"),
        "shot_end_x": shot_end_x,
        "shot_end_y": shot_end_y,
        "carry_end_x": carry_end_x,
        "carry_end_y": carry_end_y,
        "duel_type_name": _name(duel.get("type")),
        "raw_data": event,
    }


class IngestionService:
    def __init__(self, session: Session, client: StatsBombOpenDataClient) -> None:
        self.session = session
        self.client = client

    def ingest_season(
        self,
        competition_id: int,
        season_id: int,
        *,
        limit: int | None = None,
        force_download: bool = False,
        download_workers: int = 4,
    ) -> int:
        competitions = self.client.competitions(force=force_download)
        competition = next(
            (
                item
                for item in competitions
                if item["competition_id"] == competition_id and item["season_id"] == season_id
            ),
            None,
        )
        if not competition:
            raise ValueError(f"Competition {competition_id}, season {season_id} not found")

        self.session.merge(
            CompetitionSeason(
                competition_id=competition_id,
                season_id=season_id,
                country_name=competition["country_name"],
                competition_name=competition["competition_name"],
                competition_gender=competition.get("competition_gender"),
                season_name=competition["season_name"],
                match_available=_parse_datetime(competition.get("match_available")),
                raw_data=competition,
            )
        )
        matches = self.client.matches(competition_id, season_id, force=force_download)
        selected = matches[:limit] if limit else matches
        self.client.prefetch_matches(
            [item["match_id"] for item in selected],
            force=force_download,
            workers=download_workers,
        )
        for item in selected:
            self._ingest_match(item, competition_id, season_id, force_download)
        return len(selected)

    def _ingest_match(
        self,
        item: dict[str, Any],
        competition_id: int,
        season_id: int,
        force_download: bool,
    ) -> None:
        match_id = item["match_id"]
        home = item["home_team"]
        away = item["away_team"]
        self.session.merge(
            Team(team_id=home["home_team_id"], team_name=home["home_team_name"])
        )
        self.session.merge(
            Team(team_id=away["away_team_id"], team_name=away["away_team_name"])
        )

        self.session.merge(
            Match(
                match_id=match_id,
                competition_id=competition_id,
                season_id=season_id,
                match_date=datetime.strptime(item["match_date"], "%Y-%m-%d").date(),
                kick_off=datetime.strptime(item["kick_off"], "%H:%M:%S.%f").time()
                if item.get("kick_off")
                else None,
                match_week=item.get("match_week"),
                stadium_name=_name(item.get("stadium")),
                referee_name=_name(item.get("referee")),
                home_team_id=home["home_team_id"],
                away_team_id=away["away_team_id"],
                home_score=item["home_score"],
                away_score=item["away_score"],
                match_status=item.get("match_status"),
                raw_data=item,
            )
        )
        self.session.flush()

        lineup_payload = self.client.lineups(match_id, force=force_download)
        self.session.execute(delete(Lineup).where(Lineup.match_id == match_id))
        for team_lineup in lineup_payload:
            team_id = team_lineup["team_id"]
            self.session.merge(Team(team_id=team_id, team_name=team_lineup["team_name"]))
            for item_player in team_lineup["lineup"]:
                country = item_player.get("country") or {}
                self.session.merge(
                    Player(
                        player_id=item_player["player_id"],
                        player_name=item_player["player_name"],
                        player_nickname=item_player.get("player_nickname"),
                        country_name=country.get("name"),
                    )
                )
                self.session.add(
                    Lineup(
                        match_id=match_id,
                        team_id=team_id,
                        player_id=item_player["player_id"],
                        jersey_number=item_player.get("jersey_number"),
                        positions=item_player.get("positions", []),
                        cards=item_player.get("cards", []),
                        raw_data=item_player,
                    )
                )
        self.session.flush()

        events = self.client.events(match_id, force=force_download)
        self.session.execute(delete(Event).where(Event.match_id == match_id))
        rows = [event_row(match_id, event) for event in events]
        if rows:
            self.session.execute(insert(Event), rows)
        self.session.commit()
