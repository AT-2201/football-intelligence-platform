from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Football Intelligence API"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/football.db"
    statsbomb_base_url: str = (
        "https://raw.githubusercontent.com/hudl/open-data/master/data"
    )
    statsbomb_competition_id: int = 2
    statsbomb_season_id: int = 27
    raw_data_dir: Path = Path("data/raw/statsbomb")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

