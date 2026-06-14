from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.routes.groups import router as groups_router
from app.routes.fixtures import router as fixtures_router
from app.routes.forecast import router as forecast_router
from app.routes.odds import router as odds_router

load_dotenv()

app = FastAPI(title="WC 2026 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(groups_router)
app.include_router(fixtures_router)
app.include_router(forecast_router)
app.include_router(odds_router)


@app.get("/health")
def health():
    return {"status": "ok"}
