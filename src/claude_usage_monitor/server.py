"""
Claude Usage Monitor - FastAPI Server
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import database as db
from .analyzer import analyze
from .config import APP_NAME, APP_VERSION, DATA_DIR, PLANS, STATIC_DIR, load_config, save_config

logger = logging.getLogger("monitor.server")

app = FastAPI(title=APP_NAME, version=APP_VERSION)


# ── API Models ──────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    plan: str | None = None
    scrape_interval_minutes: int | None = None
    auto_scrape: bool | None = None
    auto_export_csv: bool | None = None
    notifications_enabled: bool | None = None
    alert_all_models_threshold: int | None = None
    alert_sonnet_threshold: int | None = None
    alert_on_reset: bool | None = None
    alert_cooldown_minutes: int | None = None
    chrome_user_data_dir: str | None = None
    chrome_profile: str | None = None
    launch_at_startup: bool | None = None


class ManualEntry(BaseModel):
    all_models_pct: int
    sonnet_pct: int = 0
    reset_all_models: str | None = None
    reset_sonnet: str | None = None


# ── Dashboard ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "dashboard.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found. Check static/dashboard.html</h1>")


# ── API Routes ──────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    config = load_config()
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "plan": config["plan"],
        "entries_count": db.entry_count(),
        "latest": db.get_latest_entry(),
        "data_dir": str(DATA_DIR),
    }


@app.get("/api/analysis")
async def get_analysis():
    config = load_config()
    monthly_stats = db.get_monthly_peaks(months=6)
    return analyze(db.get_entries(), config["plan"], monthly_stats=monthly_stats)


@app.get("/api/entries")
async def get_entries(days: int | None = None, limit: int | None = None):
    return db.get_entries(days=days, limit=limit)


@app.get("/api/daily")
async def get_daily(days: int = 90):
    return db.get_daily_summaries(days=days)


@app.get("/api/weekly")
async def get_weekly(weeks: int = 12):
    return db.get_weekly_peaks(weeks=weeks)


@app.get("/api/monthly")
async def get_monthly(months: int = 6):
    return db.get_monthly_peaks(months=months)


@app.get("/api/cycle-stats")
async def get_cycle_stats():
    from .analyzer import compute_cycle_stats
    entries = db.get_entries()
    return compute_cycle_stats(entries)


@app.get("/api/sonnet-cycles")
async def get_sonnet_cycles():
    return db.get_sonnet_cycles()


@app.get("/api/resets")
async def get_resets():
    return db.detect_resets()


@app.post("/api/entry")
async def add_manual_entry(entry: ManualEntry):
    entry_id = db.add_entry(
        all_models_pct=entry.all_models_pct,
        sonnet_pct=entry.sonnet_pct,
        reset_all_models=entry.reset_all_models,
        reset_sonnet=entry.reset_sonnet,
        source="manual",
    )
    return {"id": entry_id, "success": True}


@app.delete("/api/entry/{entry_id}")
async def delete_entry(entry_id: int):
    db.delete_entry(entry_id)
    return {"success": True}


@app.get("/api/config")
async def get_config():
    return load_config()


@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    config = load_config()
    for key, value in update.model_dump(exclude_none=True).items():
        config[key] = value
    save_config(config)
    return config


@app.get("/api/plans")
async def get_plans():
    return PLANS


@app.post("/api/scrape")
async def trigger_scrape():
    from .scraper import scrape_usage_simple

    result = await scrape_usage_simple(headless=True, timeout=30)
    if result and result.get("allModels") is not None:
        entry_id = db.add_entry(
            all_models_pct=result["allModels"],
            sonnet_pct=result.get("sonnet", 0) or 0,
            reset_all_models=result.get("allModelsResetIn"),
            reset_sonnet=result.get("sonnetResetIn"),
            source="manual_scrape",
        )
        return {"success": True, "data": result, "entry_id": entry_id}
    return {"success": False, "error": "Scraping failed. Check browser session."}


@app.get("/api/export/csv")
async def export_csv():
    filepath = db.export_csv()
    if filepath:
        return FileResponse(filepath, media_type="text/csv", filename=Path(filepath).name)
    raise HTTPException(404, "No data to export")


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)):
    import shutil
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    count = db.import_csv(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    return {"success": True, "imported": count}


@app.post("/api/clear")
async def clear_data():
    db.clear_all()
    return {"success": True}
