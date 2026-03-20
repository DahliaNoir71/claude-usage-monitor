"""
Claude Usage Monitor - Analyzer
Computes insights and plan recommendations from usage data.
"""
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from .config import PLANS


def analyze(entries: list[dict], plan: str = "max_100", monthly_stats: list[dict] | None = None) -> dict:
    if not entries:
        return {"status": "no_data", "message": "Aucune donnée disponible. Lance un scraping."}

    current_plan = PLANS.get(plan, PLANS["max_100"])
    latest = entries[-1]

    all_models_values = [e["all_models_pct"] for e in entries if e.get("all_models_pct") is not None]
    sonnet_values = [e["sonnet_pct"] for e in entries if e.get("sonnet_pct") is not None]

    weekly_peaks = _compute_weekly_peaks(entries)
    sonnet_cycles = _compute_sonnet_cycles(entries)

    first_ts = datetime.fromisoformat(entries[0]["timestamp"])
    last_ts = datetime.fromisoformat(entries[-1]["timestamp"])
    days_covered = max((last_ts - first_ts).days, 1)

    hourly_dist = _hourly_distribution(entries)
    daily_velocity = _daily_velocity(entries)

    # Build monthly stats from entries if not provided
    if monthly_stats is None:
        monthly_stats = _compute_monthly_stats(entries)

    recommendation = _recommend_plan(
        monthly_stats=monthly_stats,
        sonnet_cycles=sonnet_cycles,
        current_plan=plan,
        days_covered=days_covered,
    )

    # Include Claude Code data if available
    claude_code_data = _get_claude_code_analysis()

    return {
        "status": "ok",
        "current_plan": plan,
        "current_plan_price": current_plan["price"],
        "entries_count": len(entries),
        "days_covered": days_covered,
        "latest": {
            "timestamp": latest["timestamp"],
            "all_models_pct": latest.get("all_models_pct", 0),
            "sonnet_pct": latest.get("sonnet_pct", 0),
            "reset_all_models": latest.get("reset_all_models"),
            "reset_sonnet": latest.get("reset_sonnet"),
        },
        "all_models": {
            "current": latest.get("all_models_pct", 0),
            "max_ever": max(all_models_values) if all_models_values else 0,
            "avg": round(sum(all_models_values) / len(all_models_values), 1) if all_models_values else 0,
        },
        "sonnet": {
            "current": latest.get("sonnet_pct", 0),
            "max_ever": max(sonnet_values) if sonnet_values else 0,
            "avg": round(sum(sonnet_values) / len(sonnet_values), 1) if sonnet_values else 0,
        },
        "weekly_peaks": weekly_peaks,
        "sonnet_cycles": sonnet_cycles,
        "monthly_stats": monthly_stats,
        "hourly_distribution": hourly_dist,
        "daily_velocity": daily_velocity,
        "recommendation": recommendation,
        "claude_code": claude_code_data,
    }


def _compute_weekly_peaks(entries: list[dict]) -> list[dict]:
    if not entries:
        return []

    cycles = []
    cycle_start = entries[0]
    cycle_max = entries[0].get("all_models_pct", 0) or 0

    for i in range(1, len(entries)):
        prev = entries[i - 1].get("all_models_pct", 0) or 0
        curr = entries[i].get("all_models_pct", 0) or 0

        if curr < prev - 2:
            cycles.append({"start": cycle_start["timestamp"], "end": entries[i - 1]["timestamp"], "peak": cycle_max})
            cycle_start = entries[i]
            cycle_max = curr
        else:
            cycle_max = max(cycle_max, curr)

    cycles.append({"start": cycle_start["timestamp"], "end": entries[-1]["timestamp"], "peak": cycle_max})
    return cycles


def _compute_sonnet_cycles(entries: list[dict]) -> list[dict]:
    if not entries:
        return []

    cycles = []
    peak = 0
    cycle_start = entries[0]["timestamp"]

    for i in range(1, len(entries)):
        prev_s = entries[i - 1].get("sonnet_pct", 0) or 0
        curr_s = entries[i].get("sonnet_pct", 0) or 0
        peak = max(peak, prev_s)

        if curr_s < prev_s - 5:
            if peak > 0:
                cycles.append({"start": cycle_start, "end": entries[i - 1]["timestamp"], "peak": peak})
            peak = curr_s
            cycle_start = entries[i]["timestamp"]

    last_s = entries[-1].get("sonnet_pct", 0) or 0
    final_peak = max(peak, last_s)
    if final_peak > 0:
        cycles.append({"start": cycle_start, "end": entries[-1]["timestamp"], "peak": final_peak})

    return cycles


def _parse_reset_duration(text: str | None) -> timedelta | None:
    """Parse reset text like '18 h 36 min' or '2h 14min' into a timedelta."""
    if not text:
        return None
    m = re.search(r'(\d+)\s*h\s*(\d+)\s*min', text)
    if m:
        return timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    m = re.search(r'(\d+)\s*min', text)
    if m:
        return timedelta(minutes=int(m.group(1)))
    m = re.search(r'(\d+)\s*h', text)
    if m:
        return timedelta(hours=int(m.group(1)))
    return None


def compute_cycle_stats(entries: list[dict]) -> dict:
    """Compute cycle duration stats from reset detections and reset_all_models fields."""
    # Method 1: Use reset drops (usage going down significantly)
    cycle_durations = []
    last_reset_ts = None

    for i in range(1, len(entries)):
        prev = entries[i - 1].get("all_models_pct", 0) or 0
        curr = entries[i].get("all_models_pct", 0) or 0
        if curr < prev - 2:
            ts = datetime.fromisoformat(entries[i]["timestamp"])
            if last_reset_ts:
                duration = (ts - last_reset_ts).total_seconds()
                if 1800 < duration < 86400:  # between 30min and 24h
                    cycle_durations.append(duration)
            last_reset_ts = ts

    # Method 2: Use the latest reset_all_models field for direct countdown
    latest_reset_text = None
    latest_reset_td = None
    latest_ts = None
    for e in reversed(entries):
        if e.get("reset_all_models"):
            latest_reset_text = e["reset_all_models"]
            latest_reset_td = _parse_reset_duration(latest_reset_text)
            latest_ts = datetime.fromisoformat(e["timestamp"])
            break

    result = {
        "has_data": False,
        "median_cycle_hours": None,
        "stddev_hours": None,
        "cycles_analyzed": len(cycle_durations),
        "last_reset_timestamp": last_reset_ts.isoformat() if last_reset_ts else None,
        "next_reset_estimate": None,
        "reliable": False,
        "source": None,
    }

    # If we have a direct reset countdown from scraper, use it
    if latest_reset_td and latest_ts:
        reset_at = latest_ts + latest_reset_td
        result["has_data"] = True
        result["next_reset_estimate"] = reset_at.isoformat()
        result["source"] = "scraper"
        result["reliable"] = True

    # Compute median cycle duration from detected resets
    if cycle_durations:
        median_s = statistics.median(cycle_durations)
        result["has_data"] = True
        result["median_cycle_hours"] = round(median_s / 3600, 1)
        result["cycles_analyzed"] = len(cycle_durations)
        if len(cycle_durations) >= 3:
            stddev_s = statistics.stdev(cycle_durations)
            result["stddev_hours"] = round(stddev_s / 3600, 1)
            result["reliable"] = stddev_s / median_s < 0.3

        # Estimate next reset from median if no scraper data
        if not result.get("source") and last_reset_ts:
            next_est = last_reset_ts + timedelta(seconds=median_s)
            result["next_reset_estimate"] = next_est.isoformat()
            result["source"] = "estimated"

    return result


def _hourly_distribution(entries: list[dict]) -> dict[int, int]:
    dist: dict[int, int] = {}
    for e in entries:
        try:
            hour = datetime.fromisoformat(e["timestamp"]).hour
            dist[hour] = dist.get(hour, 0) + 1
        except (ValueError, KeyError):
            continue
    return dist


def _daily_velocity(entries: list[dict]) -> list[dict]:
    daily: dict[str, dict] = defaultdict(lambda: {"min": 100, "max": 0, "count": 0})

    for e in entries:
        date = e["timestamp"][:10]
        v = e.get("all_models_pct", 0) or 0
        daily[date]["min"] = min(daily[date]["min"], v)
        daily[date]["max"] = max(daily[date]["max"], v)
        daily[date]["count"] += 1

    return [
        {"date": date, "min": d["min"], "max": d["max"], "delta": d["max"] - d["min"], "entries": d["count"]}
        for date, d in sorted(daily.items())
    ]


def _compute_monthly_stats(entries: list[dict]) -> list[dict]:
    """Compute monthly aggregation from raw entries."""
    monthly: dict[str, dict] = defaultdict(lambda: {
        "all_models": [], "sonnet": [], "days": set(),
    })
    for e in entries:
        month = e["timestamp"][:7]
        am = e.get("all_models_pct")
        sn = e.get("sonnet_pct")
        day = e["timestamp"][:10]
        monthly[month]["days"].add(day)
        if am is not None:
            monthly[month]["all_models"].append(am)
        if sn is not None:
            monthly[month]["sonnet"].append(sn)

    result = []
    for month in sorted(monthly.keys()):
        m = monthly[month]
        am_vals = m["all_models"]
        sn_vals = m["sonnet"]
        rate_limit_days = len({e["timestamp"][:10] for e in entries
                              if e["timestamp"][:7] == month
                              and (e.get("all_models_pct") or 0) > 80})
        result.append({
            "month": month,
            "max_all_models": max(am_vals) if am_vals else 0,
            "avg_all_models": round(sum(am_vals) / len(am_vals), 1) if am_vals else 0,
            "max_sonnet": max(sn_vals) if sn_vals else 0,
            "avg_sonnet": round(sum(sn_vals) / len(sn_vals), 1) if sn_vals else 0,
            "rate_limit_days": rate_limit_days,
            "active_days": len(m["days"]),
            "entries_count": len(am_vals),
        })
    return result


def _compute_monthly_trend(monthly_stats: list[dict]) -> str:
    """Compute trend from last 3 months of peaks."""
    if len(monthly_stats) < 2:
        return "stable"
    recent = monthly_stats[-3:]
    peaks = [m["max_all_models"] for m in recent]
    if len(peaks) >= 2:
        increases = sum(1 for i in range(1, len(peaks)) if peaks[i] > peaks[i - 1] * 1.1)
        decreases = sum(1 for i in range(1, len(peaks)) if peaks[i] < peaks[i - 1] * 0.9)
        if increases == len(peaks) - 1:
            return "rising"
        if decreases == len(peaks) - 1:
            return "falling"
    return "stable"


def _recommend_plan(
    monthly_stats: list[dict],
    sonnet_cycles: list[dict],
    current_plan: str,
    days_covered: int,
) -> dict:
    if not monthly_stats:
        return {
            "plan": current_plan,
            "plan_name": PLANS.get(current_plan, {}).get("name", current_plan),
            "action": "maintain",
            "confidence": "low",
            "reason": "Pas assez de données pour recommander un changement.",
            "caveats": [],
            "savings_monthly": 0,
            "savings_yearly": 0,
            "stats": {
                "months_analyzed": 0, "monthly_peaks": [], "monthly_avgs": [],
                "rate_limit_days_per_month": [], "trend": "stable", "days_covered": days_covered,
            },
        }

    monthly_peaks = [m["max_all_models"] for m in monthly_stats]
    monthly_avgs = [m["avg_all_models"] for m in monthly_stats]
    rate_limit_days = [m.get("rate_limit_days", 0) for m in monthly_stats]
    months_analyzed = len(monthly_stats)

    monthly_avg_peak = sum(monthly_peaks) / months_analyzed
    monthly_max_peak = max(monthly_peaks)
    trend = _compute_monthly_trend(monthly_stats)

    # Confidence based on complete months (exclude current partial month)
    complete_months = months_analyzed - 1 if months_analyzed > 1 else 0
    confidence = "high" if complete_months >= 3 else "medium" if complete_months >= 1 else "low"

    current_price = PLANS.get(current_plan, PLANS["max_100"])["price"]

    recommended = current_plan
    savings = 0
    action = "maintain"
    reason = ""

    months_label = f"les {months_analyzed} derniers mois" if months_analyzed > 1 else "le dernier mois"

    if current_plan in ("max_100", "max_200"):
        if monthly_max_peak <= 30 and complete_months >= 2:
            recommended = "pro"
            savings = current_price - PLANS["pro"]["price"]
            action = "downgrade"
            reason = (
                f"Sur {months_label}, ton pic max All Models est de {monthly_max_peak}% "
                f"(moyenne {monthly_avg_peak:.0f}%). Le Pro couvrirait largement cet usage."
            )
        elif monthly_max_peak <= 50:
            recommended = "pro"
            savings = current_price - PLANS["pro"]["price"]
            action = "consider_downgrade"
            reason = (
                f"Usage modéré sur {months_label} ({monthly_max_peak}% max). "
                f"Le Pro pourrait suffire mais surveille les rate-limits."
            )
        elif monthly_max_peak <= 75:
            reason = f"Usage correct sur {months_label} ({monthly_max_peak}% max). Ton plan est adapté."
        else:
            if current_plan == "max_200" and monthly_max_peak <= 90:
                recommended = "max_100"
                savings = PLANS["max_200"]["price"] - PLANS["max_100"]["price"]
                action = "consider_downgrade"
                reason = f"Usage élevé mais le Max $100 pourrait suffire."
            else:
                reason = f"Usage élevé sur {months_label} ({monthly_max_peak}% max). Bon usage de ton plan Max."

    elif current_plan == "pro":
        frequent_rate_limits = sum(1 for rl in rate_limit_days if rl >= 2)
        if frequent_rate_limits >= 2:
            recommended = "max_100"
            savings = -(PLANS["max_100"]["price"] - PLANS["pro"]["price"])
            action = "upgrade"
            confidence = "high"
            reason = (
                f"Usage très élevé sur {months_label} ({monthly_max_peak}% max). "
                f"Rate-limité {sum(rate_limit_days)} jours au total. Le Max $100 éviterait les rate-limits."
            )
        elif monthly_max_peak >= 80:
            recommended = "max_100"
            savings = -(PLANS["max_100"]["price"] - PLANS["pro"]["price"])
            action = "upgrade"
            reason = f"Pic mensuel à {monthly_max_peak}%. Le Max $100 offrirait plus de marge."
        else:
            reason = f"Usage {'correct' if monthly_max_peak >= 50 else 'modéré'} sur {months_label} ({monthly_max_peak}% max). Plan adapté."
    else:  # free
        frequent_rate_limits = sum(1 for rl in rate_limit_days if rl >= 5)
        if frequent_rate_limits >= 1 or monthly_max_peak >= 60:
            recommended = "pro"
            savings = -PLANS["pro"]["price"]
            action = "upgrade"
            reason = "Usage élevé pour un plan gratuit. Le Pro améliorerait l'expérience."
        else:
            reason = "Usage compatible avec le plan gratuit."

    caveats = []
    if confidence == "low":
        caveats.append(f"Données sur {days_covered} jours seulement — confirme sur 1 mois complet minimum.")
    if current_plan in ("max_100", "max_200") and recommended == "pro":
        caveats.append(
            "Le plan Max offre l'extended thinking (45 min) et la priorité haute "
            "qui ne sont pas dans le Pro. Évalue si tu utilises ces fonctionnalités."
        )
    if trend == "rising":
        caveats.append("Tendance à la hausse — réévalue dans 1 mois.")

    return {
        "plan": recommended,
        "plan_name": PLANS.get(recommended, {}).get("name", recommended),
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "caveats": caveats,
        "savings_monthly": savings if savings > 0 else 0,
        "savings_yearly": savings * 12 if savings > 0 else 0,
        "stats": {
            "months_analyzed": months_analyzed,
            "monthly_peaks": monthly_peaks,
            "monthly_avgs": monthly_avgs,
            "rate_limit_days_per_month": rate_limit_days,
            "trend": trend,
            "days_covered": days_covered,
        },
    }


def _get_claude_code_analysis() -> dict:
    """Analyze Claude Code sessions for the current month."""
    try:
        from . import database as db
        from datetime import datetime

        # Get current month
        now = datetime.now()
        current_month = now.strftime("%Y-%m")

        # Get all sessions this month
        sessions = db.get_claude_code_sessions(days=31)
        sessions_this_month = [s for s in sessions if s.get("start_time", "").startswith(current_month)]

        if not sessions_this_month:
            return {"detected": False}

        # Aggregate metrics
        total_tokens = sum(s.get("total_tokens", 0) for s in sessions_this_month)
        total_cost = sum(s.get("cost_usd", 0) for s in sessions_this_month)
        session_count = len(sessions_this_month)

        # Extract and aggregate model usage
        model_usage = _aggregate_model_usage(sessions_this_month)
        model_split = _compute_model_split(model_usage, total_tokens)
        primary_model = max(model_usage.items(), key=lambda x: x[1])[0] if model_usage else "unknown"

        # Aggregate projects
        projects = _aggregate_projects(sessions_this_month)
        top_projects = sorted(
            [{"name": name, "tokens": data["tokens"], "cost": round(data["cost"], 2)} for name, data in projects.items()],
            key=lambda x: x["cost"],
            reverse=True,
        )[:5]

        # Daily averages
        active_days = len({s.get("start_time", "")[:10] for s in sessions_this_month})
        daily_avg_tokens = round(total_tokens / active_days, 0) if active_days > 0 else 0
        daily_avg_cost = round(total_cost / active_days, 2) if active_days > 0 else 0

        return {
            "detected": True,
            "sessions_this_month": session_count,
            "tokens_this_month": total_tokens,
            "cost_equivalent_this_month": round(total_cost, 2),
            "primary_model": primary_model,
            "model_split": model_split,
            "top_projects": top_projects,
            "daily_avg_tokens": daily_avg_tokens,
            "daily_avg_cost": daily_avg_cost,
            "active_days": active_days,
        }

    except Exception as e:
        # Log but don't crash if Claude Code analysis fails
        import logging
        logger = logging.getLogger("monitor.analyzer")
        logger.debug(f"Claude Code analysis failed: {e}")
        return {"detected": False, "error": str(e)}


def _aggregate_model_usage(sessions: list[dict]) -> dict:
    """Aggregate token usage by model across sessions."""
    model_usage = {}
    for session in sessions:
        for model_id, usage in session.get("model_usage", {}).items():
            if model_id not in model_usage:
                model_usage[model_id] = 0
            model_usage[model_id] += (
                usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0)
                + usage.get("cache_read", 0)
                + usage.get("cache_creation", 0)
            )
    return model_usage


def _compute_model_split(model_usage: dict, total_tokens: int) -> dict:
    """Compute normalized model split percentages."""
    model_split = {}
    for model_id, tokens in model_usage.items():
        pct = round(100 * tokens / total_tokens, 1) if total_tokens > 0 else 0
        key = _normalize_model_name(model_id)
        model_split[key] = model_split.get(key, 0) + pct
    return model_split


def _normalize_model_name(model_id: str) -> str:
    """Normalize model ID to display name."""
    if "opus" in model_id:
        return "opus"
    if "sonnet" in model_id:
        return "sonnet"
    if "haiku" in model_id:
        return "haiku"
    return model_id


def _aggregate_projects(sessions: list[dict]) -> dict:
    """Aggregate token and cost usage by project."""
    projects = {}
    for session in sessions:
        project = session.get("project_path") or "Unknown"
        if project not in projects:
            projects[project] = {"tokens": 0, "cost": 0}
        projects[project]["tokens"] += session.get("total_tokens", 0)
        projects[project]["cost"] += session.get("cost_usd", 0)
    return projects
