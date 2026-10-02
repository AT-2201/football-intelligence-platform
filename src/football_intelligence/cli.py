import json
from typing import Annotated

import typer

from football_intelligence.analytics.transform import transform_season
from football_intelligence.analytics.validation import validate_season
from football_intelligence.config import get_settings
from football_intelligence.db import SessionLocal, create_tables
from football_intelligence.ingestion.client import StatsBombOpenDataClient
from football_intelligence.ingestion.service import IngestionService

app = typer.Typer(help="Football Intelligence data pipeline")


@app.command("init-db")
def init_db() -> None:
    """Create source and analytics tables."""
    create_tables()
    typer.echo("Database tables are ready.")


@app.command()
def ingest(
    limit: Annotated[int | None, typer.Option(help="Only ingest the first N matches")] = None,
    force_download: Annotated[
        bool, typer.Option(help="Ignore the local raw-data cache")
    ] = False,
    download_workers: Annotated[
        int, typer.Option(min=1, max=12, help="Concurrent raw-data downloads")
    ] = 4,
) -> None:
    """Ingest the configured StatsBomb competition-season."""
    settings = get_settings()
    create_tables()
    client = StatsBombOpenDataClient(settings.statsbomb_base_url, settings.raw_data_dir)
    with SessionLocal() as session:
        count = IngestionService(session, client).ingest_season(
            settings.statsbomb_competition_id,
            settings.statsbomb_season_id,
            limit=limit,
            force_download=force_download,
            download_workers=download_workers,
        )
    typer.echo(f"Ingested {count} match(es).")


@app.command()
def transform() -> None:
    """Build match and season analytics for the configured scope."""
    settings = get_settings()
    create_tables()
    with SessionLocal() as session:
        result = transform_season(
            session, settings.statsbomb_competition_id, settings.statsbomb_season_id
        )
    typer.echo(f"Built analytics: {result}")


@app.command()
def validate(
    strict: Annotated[
        bool, typer.Option(help="Fail when the full 380-match season is not loaded")
    ] = False,
) -> None:
    """Run source and analytics quality checks."""
    settings = get_settings()
    with SessionLocal() as session:
        report = validate_season(
            session, settings.statsbomb_competition_id, settings.statsbomb_season_id
        )
    typer.echo(json.dumps(report, indent=2))
    has_errors = any(issue["level"] == "error" for issue in report["issues"])
    incomplete = report["counts"]["matches"] != 380
    if has_errors or (strict and incomplete):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
