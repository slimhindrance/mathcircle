"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import STATIC_DIR, TEMPLATES_DIR
from .database import SessionLocal, init_db
from .routes import api as api_routes
from .routes import auth as auth_routes
from .routes import web as web_routes
from .seed import ensure_default_children, seed_database

log = logging.getLogger("mathcircle")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        result = seed_database(db)
        ensure_default_children(db)
        db.commit()
    log.info("seeded — added=%s, total=%s", result["added"], result["total"])
    yield


app = FastAPI(title="Math Circle Home", version="0.1.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Custom Jinja filters / globals
def _strand_color(key: str) -> str:
    palette = {
        "number_sense": "#e76f51",
        "add_sub_structures": "#f4a261",
        "missing_number_stories": "#e9c46a",
        "equality_balance": "#2a9d8f",
        "patterns": "#264653",
        "logic_classification": "#9b5de5",
        "geometry_spatial": "#00bbf9",
        "measurement": "#00f5d4",
        "combinatorics_counting": "#f15bb5",
        "math_games": "#fee440",
    }
    return palette.get(key, "#888")


def _kind_label(kind: str) -> str:
    return {
        "warm_up": "Warm-up",
        "rich_puzzle": "Rich puzzle",
        "visual": "Visual / hands-on",
        "story": "Story problem",
        "explain": "Explain your thinking",
        "game": "Math game",
        "parent_extension": "Parent extension",
    }.get(kind, kind.replace("_", " ").title())


def _kind_emoji(kind: str) -> str:
    return {
        "warm_up": "☀️",
        "rich_puzzle": "🧩",
        "visual": "🖐️",
        "story": "📖",
        "explain": "💬",
        "game": "🎲",
        "parent_extension": "🏡",
    }.get(kind, "•")


templates.env.globals["strand_color"] = _strand_color
templates.env.globals["kind_label"] = _kind_label
templates.env.globals["kind_emoji"] = _kind_emoji
templates.env.globals["app_version"] = app.version

app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Auth routes own `/`, `/request-access`, `/auth/*`, `/admin/*` — register first
# so they take precedence over any web.py wildcard routes.
app.include_router(auth_routes.router)
app.include_router(web_routes.router)
app.include_router(api_routes.router)


# Make footer attribution available as Jinja globals so any template can render it.
from .config import FOOTER_AUTHOR, FOOTER_LOCATION
templates.env.globals["FOOTER_AUTHOR"] = FOOTER_AUTHOR
templates.env.globals["FOOTER_LOCATION"] = FOOTER_LOCATION
