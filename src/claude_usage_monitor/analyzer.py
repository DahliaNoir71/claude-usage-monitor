"""
Claude Usage Monitor - Analyzer
Computes insights and plan recommendations from usage data.
"""
from collections import defaultdict
from datetime import datetime

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
