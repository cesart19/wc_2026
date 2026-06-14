import asyncio
import json
from datetime import datetime, timezone

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BACKEND_URL = "http://localhost:8000"

app = Server("wc2026")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_standings",
            description=(
                "Get group standings for FIFA World Cup 2026. "
                "Pass a group letter (A–L) to filter, or omit for all 12 groups."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "description": "Group letter: A, B, C, D, E, F, G, H, I, J, K, or L.",
                    }
                },
            },
        ),
        Tool(
            name="get_fixtures",
            description=(
                "Get match fixtures and results for FIFA World Cup 2026. "
                "Filter by team name, match status, or tournament stage."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Team name (partial match ok). E.g. 'Mexico', 'Brazil', 'France'.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["SCHEDULED", "LIVE", "IN_PLAY", "PAUSED", "FINISHED"],
                        "description": "Match status to filter by.",
                    },
                    "stage": {
                        "type": "string",
                        "enum": [
                            "GROUP_STAGE",
                            "LAST_32",
                            "LAST_16",
                            "QUARTER_FINALS",
                            "SEMI_FINALS",
                            "THIRD_PLACE",
                            "FINAL",
                        ],
                        "description": "Tournament stage to filter by.",
                    },
                },
            },
        ),
        Tool(
            name="get_today_matches",
            description="Get all matches scheduled or played today (UTC) in the 2026 World Cup.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


async def _fetch(path: str) -> list:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BACKEND_URL}{path}", timeout=15)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise RuntimeError(
            "No se puede conectar al backend (http://localhost:8000). "
            "Inícialo con: cd backend && uvicorn app.main:app --port 8000"
        )


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_standings":
        data = await _fetch("/groups")
        group_filter = arguments.get("group", "").upper()
        if group_filter:
            data = [g for g in data if g.get("group", "").endswith(f"_{group_filter}")]
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    if name == "get_fixtures":
        data = await _fetch("/fixtures")
        team = arguments.get("team", "").lower()
        status = arguments.get("status", "").upper()
        stage = arguments.get("stage", "").upper()
        if team:
            data = [
                m for m in data
                if team in m["homeTeam"]["name"].lower() or team in m["awayTeam"]["name"].lower()
            ]
        if status:
            data = [m for m in data if m.get("status") == status]
        if stage:
            data = [m for m in data if m.get("stage") == stage]
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    if name == "get_today_matches":
        data = await _fetch("/fixtures")
        today = datetime.now(timezone.utc).date().isoformat()
        data = [m for m in data if m.get("utcDate", "").startswith(today)]
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
