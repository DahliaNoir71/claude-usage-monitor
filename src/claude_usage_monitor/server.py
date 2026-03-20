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
    claude_code_scan_enabled: bool | None = None
    claude_code_dir: str | None = None
    claude_code_scan_interval_minutes: int | None = None


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
    from .scraper import last_scrape_info
    config = load_config()
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "plan": config["plan"],
        "entries_count": db.entry_count(),
        "latest": db.get_latest_entry(),
        "data_dir": str(DATA_DIR),
        "last_scrape_status": last_scrape_info.get("status"),
        "last_scrape_error": last_scrape_info.get("error"),
        "last_scrape_timestamp": last_scrape_info.get("timestamp"),
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


# ── Claude Code API ──────────────────────────────────────────────────────────

@app.get("/api/claude-code/status")
async def claude_code_status():
    """Check if Claude Code is detected and return basic stats."""
    from .claude_code_reader import find_claude_code_dir, list_projects

    config = load_config()
    claude_dir_override = config.get("claude_code_dir")

    if claude_dir_override:
        claude_dir = Path(claude_dir_override)
        if not claude_dir.exists():
            return {"detected": False, "dir": None, "sessions_count": 0, "error": f"Directory not found: {claude_dir}"}
    else:
        claude_dir = find_claude_code_dir()
        if not claude_dir:
            return {"detected": False, "dir": None, "sessions_count": 0}

    try:
        projects = list_projects(claude_dir)
        session_count = sum(p["session_count"] for p in projects)
        latest_sessions = db.get_claude_code_sessions(days=1)
        return {
            "detected": True,
            "dir": str(claude_dir),
            "projects_count": len(projects),
            "sessions_count": session_count,
            "last_session": latest_sessions[0] if latest_sessions else None,
        }
    except Exception as e:
        logger.error(f"Error checking Claude Code status: {e}")
        return {"detected": False, "error": str(e)}


@app.get("/api/claude-code/sessions")
async def get_claude_code_sessions(days: int = 30, project: str | None = None):
    """Get Claude Code sessions with optional project filter."""
    sessions = db.get_claude_code_sessions(days=days, project=project)
    return sessions


@app.get("/api/claude-code/daily")
async def get_claude_code_daily(days: int = 90):
    """Get daily Claude Code aggregates."""
    return db.get_claude_code_daily(days=days)


@app.get("/api/claude-code/monthly")
async def get_claude_code_monthly(months: int = 6):
    """Get monthly Claude Code aggregates."""
    return db.get_claude_code_monthly(months=months)


@app.get("/api/claude-code/projects")
async def get_claude_code_projects():
    """Get projects with their aggregated consumption."""
    sessions = db.get_claude_code_sessions(days=90)

    projects = {}
    for session in sessions:
        project = session.get("project_path") or "Unknown"
        if project not in projects:
            projects[project] = {
                "name": project,
                "sessions": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "last_accessed": None,
            }

        projects[project]["sessions"] += 1
        projects[project]["total_tokens"] += session.get("total_tokens", 0)
        projects[project]["cost_usd"] += session.get("cost_usd", 0.0)

        last = session.get("end_time") or session.get("start_time")
        if last and (projects[project]["last_accessed"] is None or last > projects[project]["last_accessed"]):
            projects[project]["last_accessed"] = last

    return sorted(projects.values(), key=lambda p: p["cost_usd"], reverse=True)


@app.get("/api/claude-code/models")
async def get_claude_code_models(days: int = 30):
    """Get token breakdown by model."""
    sessions = db.get_claude_code_sessions(days=days)

    models = {}
    for session in sessions:
        model_usage = session.get("model_usage", {})
        for model_id, usage in model_usage.items():
            if model_id not in models:
                models[model_id] = {
                    "model": model_id,
                    "tokens": 0,
                    "messages": 0,
                    "cost_usd": 0.0,
                }

            tokens = (
                usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0)
                + usage.get("cache_read", 0)
                + usage.get("cache_creation", 0)
            )
            models[model_id]["tokens"] += tokens
            models[model_id]["messages"] += usage.get("message_count", 0)

    # Calculate cost for each model (estimate based on pricing)
    from .config import MODEL_PRICING

    for model in models.values():
        model_id = model["model"]
        pricing = None
        for key, price_dict in MODEL_PRICING.items():
            if model_id.startswith(key):
                pricing = price_dict
                break

        if pricing:
            # Rough estimate: assume 30% input, 70% output (typical ratio)
            input_estimate = int(model["tokens"] * 0.3)
            output_estimate = model["tokens"] - input_estimate
            cost = (
                input_estimate * pricing["input"]
                + output_estimate * pricing["output"]
            ) / 1_000_000
            model["cost_usd"] = round(cost, 2)

    return sorted(models.values(), key=lambda m: m["cost_usd"], reverse=True)


@app.post("/api/claude-code/scan")
async def trigger_claude_code_scan():
    """Trigger a manual Claude Code scan."""
    from .main import _scan_claude_code

    try:
        _scan_claude_code()
        return {"success": True, "message": "Claude Code scan triggered"}
    except Exception as e:
        logger.error(f"Claude Code scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {e}")


# ── Phase 4: Reports ────────────────────────────────────────────────────────

@app.get("/api/report/monthly")
async def monthly_report(month: str | None = None):
    """Generate comprehensive monthly report (web + Claude Code)."""
    from datetime import datetime

    if not month:
        month = datetime.now().strftime("%Y-%m")

    config = load_config()
    plan_price = PLANS.get(config["plan"], {}).get("price", 0)

    # Get web and Claude Code usage
    web_data = _get_monthly_web_usage(month)
    cc_data = _get_monthly_claude_code_usage(month)
    total_cost = cc_data["cost"] if cc_data else 0

    # Determine recommendation
    recommendation = _evaluate_plan_value(total_cost, plan_price)

    return {
        "month": month,
        "plan": config["plan"],
        "plan_price": plan_price,
        "web_usage": web_data,
        "claude_code_usage": cc_data["usage"] if cc_data else {},
        "combined": {
            "total_cost_equivalent": round(total_cost, 2),
            "plan_value_ratio": round(total_cost / plan_price, 2) if plan_price > 0 else 0,
            "recommendation": recommendation,
        },
    }


def _get_monthly_web_usage(month: str) -> dict:
    """Extract web usage for a specific month."""
    web_monthly = db.get_monthly_peaks(months=12)
    web_data = next((m for m in web_monthly if m.get("month") == month), None)
    if not web_data:
        return {}
    return {
        "max_all_models_pct": web_data.get("max_all_models", 0),
        "avg_all_models_pct": web_data.get("avg_all_models", 0),
        "max_sonnet_pct": web_data.get("max_sonnet", 0),
        "avg_sonnet_pct": web_data.get("avg_sonnet", 0),
        "rate_limit_days": web_data.get("rate_limit_days", 0),
    }


def _get_monthly_claude_code_usage(month: str) -> dict | None:
    """Extract Claude Code usage for a specific month."""
    cc_monthly = db.get_claude_code_monthly(months=12)
    cc_data = next((m for m in cc_monthly if m.get("month") == month), None)
    if not cc_data:
        return None
    return {
        "cost": cc_data.get("cost_usd", 0),
        "usage": {
            "sessions": cc_data.get("sessions", 0),
            "total_tokens": cc_data.get("total_tokens", 0),
            "cost_equivalent_usd": cc_data.get("cost_usd", 0),
            "active_days": cc_data.get("active_days", 0),
            "by_model": {
                "opus_tokens": cc_data.get("opus_tokens", 0),
                "sonnet_tokens": cc_data.get("sonnet_tokens", 0),
                "haiku_tokens": cc_data.get("haiku_tokens", 0),
            },
        },
    }


def _evaluate_plan_value(total_cost: float, plan_price: float) -> str:
    """Evaluate if plan is appropriate for the cost."""
    if total_cost > plan_price * 1.5:
        return "upgrade"
    return "maintain" if total_cost <= plan_price else "consider_upgrade"


# ── Phase 5: Configuration ──────────────────────────────────────────────────

@app.put("/api/config/claude-code")
async def update_claude_code_config(update: ConfigUpdate):
    """Update Claude Code specific configuration."""
    config = load_config()

    if update.claude_code_scan_enabled is not None:
        config["claude_code_scan_enabled"] = update.claude_code_scan_enabled
    if update.claude_code_dir is not None:
        config["claude_code_dir"] = update.claude_code_dir
    if update.claude_code_scan_interval_minutes is not None:
        config["claude_code_scan_interval_minutes"] = update.claude_code_scan_interval_minutes

    save_config(config)
    return config


@app.post("/api/pricing/refresh")
async def refresh_pricing():
    """Refresh pricing from configuration (placeholder for future API integration)."""
    from .config import MODEL_PRICING

    # For now, just return current pricing
    # In future, could fetch from Anthropic pricing API
    return {"success": True, "pricing": MODEL_PRICING}
