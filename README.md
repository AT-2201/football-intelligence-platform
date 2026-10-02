# Football Club Intelligence & Scouting Platform — V1

[**Launch the live demo**](https://at-2201.github.io/football-intelligence-platform/) ·
[API documentation](#useful-api-endpoints) ·
[StatsBomb Open Data](https://github.com/hudl/open-data)

> Portfolio project: a full-season football intelligence product covering 380 Premier
> League matches, 1.3 million events, 550 players with recorded minutes, and interactive
> match, team, player, and recruitment analysis.

A modular analytics foundation built on **StatsBomb Open Data**, initially scoped to the
complete **Premier League 2015/16** competition-season (`competition_id=2`, `season_id=27`).

V1 delivers:

- repeatable ingestion of competitions, matches, lineups, and events;
- a normalized PostgreSQL-ready model with the source JSON retained for traceability;
- derived team-match, player-match, team-season, and player-season statistics;
- a FastAPI foundation for competition, match, team, and player analytics;
- a responsive analyst dashboard with overview, match, team, player, and scouting views;
- league percentiles, configurable recruitment profiles, and similar-player search;
- source-to-mart validation with a strict full-season readiness check;
- dbt-style SQL models and data-quality tests for teams that prefer dbt.

## Architecture

```text
StatsBomb Open Data JSON
        │
        ▼
data/raw/statsbomb (gitignored cache)
        │
        ▼
PostgreSQL source tables
 competitions ─ matches ─ events
                 ├─────── lineups
                 ├─────── teams
                 └─────── players
        │
        ▼
Python transformations (portable) / dbt SQL models (PostgreSQL)
        │
        ▼
player_match_stats ─ player_season_stats
team_match_stats   ─ team_season_stats
        │
        ▼
FastAPI (/api/v1/...)
```

The source, analytics, and API layers are separated so later `match_analysis`,
`player_analysis`, and `scouting` modules can be added without changing the ingestion
contract.

## Quick start

Prerequisites: Python 3.11+, Docker, and Docker Compose.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
docker compose up -d postgres
football init-db
```

Test the pipeline with one match first:

```bash
football ingest --limit 1
football transform
uvicorn football_intelligence.main:app --reload
```

Open `http://localhost:8000` for the analyst workspace or `/docs` for the API. When the
one-match smoke test works, ingest the complete season:

```bash
football ingest
football transform
football validate --strict
```

Raw downloads are cached. Re-running ingestion is idempotent; pass `--force-download` to
refresh the cache. Match files are prefetched with four concurrent downloads by default;
use `--download-workers` to tune this. Full-season ingestion is intentionally a separate
command because the event dataset is large.

## Public portfolio demo

The public GitHub Pages edition is a 6 MB static analytics snapshot generated from the
validated database. It retains the complete interactive product experience without
publishing the 851 MB raw-data cache or 1.3 GB development database.

Regenerate it after changing the data or analytics:

```bash
python scripts/export_portfolio.py
```

The generated `docs/` directory is deployed automatically by the GitHub Pages workflow.
The FastAPI/PostgreSQL implementation remains the source of truth; the static adapter exists
only to make the portfolio demo fast, free to host, and resilient for reviewers.

## Useful API endpoints

- `GET /health`
- `GET /api/v1/competitions/current`
- `GET /api/v1/overview`
- `GET /api/v1/standings`
- `GET /api/v1/matches`
- `GET /api/v1/matches/{match_id}`
- `GET /api/v1/matches/{match_id}/events`
- `GET /api/v1/matches/{match_id}/players`
- `GET /api/v1/teams`
- `GET /api/v1/teams/{team_id}/matches`
- `GET /api/v1/players?team_id=...&min_minutes=...`
- `GET /api/v1/players/{player_id}`
- `GET /api/v1/players/{player_id}/matches`
- `GET /api/v1/leaderboards/players?metric=goals`
- `GET /api/v1/scouting/players?profile=attacking&min_minutes=900`
- `GET /api/v1/scouting/players/{player_id}/similar`

Pagination is bounded to protect the API. Interactive request and response schemas are
available in the generated OpenAPI documentation at `/docs`.

## Product modules

- **Overview:** coverage, competition totals, calculated standings, and scoring leaders.
- **Match Analysis:** searchable fixtures, team comparison, xG, shot map, and player output.
- **Team Analysis:** season production, xG, and possession profiles.
- **Player Analysis:** totals, per-90 statistics, workload, and match logs.
- **Scouting:** minimum-minute qualification, positional filtering, role-based percentile
  scores, and standardized same-position similarity.

Scouting scores are screening aids, not objective player valuations. They average the league
percentiles of the metrics in the selected profile and should be paired with video, role,
age, contract, physical, and contextual analysis before recruitment decisions.

## Data model and metrics

`events.raw_data`, `matches.raw_data`, and `lineups.raw_data` retain provider payloads so
new fields can be backfilled without downloading again. Frequently queried event fields
are promoted to typed columns.

The initial transformations calculate:

- team: shots, goals, xG, passes, completed passes, possession share;
- player: appearances, minutes, shots, goals, xG, passes, completed passes, carries,
  pressures, tackles, and interceptions;
- season totals and per-90 values exposed by the API.

Minutes are calculated from StatsBomb lineup position intervals. They are suitable for V1
comparison and should be hardened around unusual extra-time or incomplete-lineup cases
before production scouting decisions.

## dbt-style transformations

The application uses a Python transformation command by default, which also works with
SQLite during tests. Equivalent PostgreSQL/dbt models live in `transformations/`:

```bash
python -m pip install -e '.[dbt]'
cd transformations
dbt build --profiles-dir .
```

Set `DBT_DATABASE`, `DBT_HOST`, `DBT_USER`, `DBT_PASSWORD`, and `DBT_PORT` as needed.

## Development

```bash
pytest
ruff check .
```

Run pipeline quality checks at any point:

```bash
football validate          # partial datasets produce a coverage warning
football validate --strict # non-zero exit until all 380 matches are ready
```

## Repository layout

```text
src/football_intelligence/
├── analytics/       # transformations, validation, scouting models
├── api/             # operational and analytical routes
├── ingestion/       # StatsBomb cache client and normalized loading
├── static/          # responsive analyst workspace
├── models.py        # source and analytics database model
├── cli.py           # init, ingest, transform, validate
└── main.py          # FastAPI application
transformations/     # optional dbt project
tests/               # mapping, API, and transformation tests
```

For local tests, set `DATABASE_URL=sqlite:///./data/test.db`; production is designed for
PostgreSQL.

## Data terms and attribution

The application code and StatsBomb data have separate terms. The raw dataset is not
committed or redistributed by this repository. StatsBomb makes selected data freely
available for research and genuine interest in football analytics. Published analysis must
identify StatsBomb as the source and use its logo, per the
[official repository terms](https://github.com/hudl/open-data). Review those terms before
commercial deployment.
