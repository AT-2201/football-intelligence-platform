"""Export a compact, static snapshot for the public GitHub Pages demo."""

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from football_intelligence.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "football_intelligence" / "static"
OUTPUT = ROOT / "docs"


def get(client: TestClient, path: str):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    assets = OUTPUT / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copy2(STATIC / "index.html", OUTPUT / "index.html")
    for name in ("styles.css", "app.js", "data-adapter.js", "favicon.svg"):
        shutil.copy2(STATIC / name, assets / name)
    (OUTPUT / ".nojekyll").touch()

    with TestClient(app) as client:
        matches = get(client, "/api/v1/matches?limit=500")
        players = get(client, "/api/v1/players?limit=1000&min_minutes=0")
        player_ids = sorted({player["player_id"] for player in players})
        match_details = {}
        match_shots = {}
        match_players = {}
        for match in matches:
            match_id = str(match["match_id"])
            match_details[match_id] = get(client, f"/api/v1/matches/{match_id}")
            match_shots[match_id] = get(
                client, f"/api/v1/matches/{match_id}/events?event_type=Shot"
            )
            match_players[match_id] = get(client, f"/api/v1/matches/{match_id}/players")
        player_details = {
            str(player_id): get(client, f"/api/v1/players/{player_id}")
            for player_id in player_ids
        }
        player_logs = {
            str(player_id): get(client, f"/api/v1/players/{player_id}/matches?limit=100")
            for player_id in player_ids
        }
        snapshot = {
            "overview": get(client, "/api/v1/overview"),
            "standings": get(client, "/api/v1/standings"),
            "matches": matches,
            "teams": get(client, "/api/v1/teams"),
            "players": players,
            "matchDetails": match_details,
            "matchShots": match_shots,
            "matchPlayers": match_players,
            "playerDetails": player_details,
            "playerLogs": player_logs,
            "scoutingBase": get(
                client,
                "/api/v1/scouting/players?min_minutes=0&limit=1000",
            ),
        }
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    (assets / "data.js").write_text(
        f"window.PORTFOLIO_DATA={payload};\n", encoding="utf-8"
    )
    print(f"Exported {len(matches)} matches and {len(player_ids)} players to {OUTPUT}")


if __name__ == "__main__":
    main()
