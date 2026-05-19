# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local web app for tracking FIFA World Cup 2026 results and standings with auto-refresh. Data is sourced from the [football-data.org](https://www.football-data.org/) API (v4).

## Architecture

Two independent services that must run simultaneously:

- **Backend** (`backend/`) — Python FastAPI on port `8000`. Proxies requests to the football-data.org API to avoid CORS and to cache responses. Uses APScheduler for periodic background data refresh.
- **Frontend** (`frontend/`) — Node.js Express on port `3000` serving static HTML/CSS/JS. The browser polls the backend every 60 seconds via `fetch()`.

Data flow: `browser → Express (3000) → FastAPI (8000) → football-data.org API`

CORS is configured in `backend/app/main.py` to only allow `http://localhost:3000`.

## Running the Project

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your FOOTBALL_API_KEY
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev   # uses nodemon for auto-reload
```

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Description |
|---|---|
| `FOOTBALL_API_KEY` | API key from football-data.org (free tier available) |
| `FOOTBALL_API_URL` | `https://api.football-data.org/v4` |

## Key Endpoints (to be implemented)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/groups` | Group standings |
| GET | `/fixtures` | Match schedule and results |

New routes go in `backend/app/routes/`, new API logic in `backend/app/services/`. Register routers in `backend/app/main.py` with `app.include_router(...)`.

## Frontend JS Structure

- `frontend/src/js/api.js` — all `fetch()` calls to the backend. Add new endpoint functions here.
- `frontend/src/js/app.js` — DOM rendering and the 60-second auto-refresh loop (`setInterval`). `renderGroups()` and `renderFixtures()` are the entry points for UI updates.
