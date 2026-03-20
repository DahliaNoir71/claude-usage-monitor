"""
Claude Usage Monitor - Analyzer
Computes insights and plan recommendations from usage data.
"""
from collections import defaultdict
from datetime import datetime

from .config import PLANS


def analyze(entries: list[dict], plan: str = "max_100") -> dict:
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

    recommendation = _recommend_plan(
        weekly_peaks=weekly_peaks,
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


def _recommend_plan(
    weekly_peaks: list[dict],
    sonnet_cycles: list[dict],
    current_plan: str,
    days_covered: int,
) -> dict:
    if not weekly_peaks:
        return {
            "plan": current_plan,
            "plan_name": PLANS.get(current_plan, {}).get("name", current_plan),
            "action": "maintain",
            "confidence": "low",
            "reason": "Pas assez de données pour recommander un changement.",
            "caveats": [],
            "savings_monthly": 0,
            "savings_yearly": 0,
            "stats": {"avg_weekly_peak": 0, "max_weekly_peak": 0, "avg_sonnet_peak": 0, "max_sonnet_peak": 0, "days_covered": days_covered},
        }

    avg_peak = sum(c["peak"] for c in weekly_peaks) / len(weekly_peaks)
    max_peak = max(c["peak"] for c in weekly_peaks)

    sonnet_peaks = [c["peak"] for c in sonnet_cycles] if sonnet_cycles else [0]
    max_sonnet_peak = max(sonnet_peaks)
    avg_sonnet_peak = sum(sonnet_peaks) / len(sonnet_peaks)

    confidence = "high" if days_covered >= 28 else "medium" if days_covered >= 14 else "low"
    current_price = PLANS.get(current_plan, PLANS["max_100"])["price"]

    # Decision logic
    recommended = current_plan
    savings = 0
    action = "maintain"
    reason = ""

    if current_plan in ("max_100", "max_200"):
        if max_peak <= 30 and avg_peak <= 20:
            recommended = "pro"
            savings = current_price - PLANS["pro"]["price"]
            reason = (
                f"Ton usage All Models plafonne à {max_peak}% (moyenne {avg_peak:.0f}%). "
                f"Le plan Pro couvrirait largement cet usage. "
                f"Économie : ${savings}/mois (${savings * 12}/an)."
            )
            if max_sonnet_peak > 80:
                reason += f" Note : Sonnet atteint {max_sonnet_peak}% sur ses fenêtres de 5h, surveille si tu es rate-limité."
            action = "downgrade"
        elif max_peak <= 50:
            recommended = "pro"
            savings = current_price - PLANS["pro"]["price"]
            reason = f"Usage modéré ({max_peak}% max). Le Pro pourrait suffire mais surveille les rate-limits."
            action = "consider_downgrade"
        elif max_peak <= 75:
            reason = f"Usage correct ({max_peak}% max). Ton plan est adapté."
        else:
            if current_plan == "max_200":
                recommended = "max_100"
                savings = PLANS["max_200"]["price"] - PLANS["max_100"]["price"]
                reason = f"Usage élevé mais le Max $100 pourrait suffire."
                action = "consider_downgrade"
            else:
                reason = f"Usage élevé ({max_peak}% max). Bon usage de ton plan Max."

    elif current_plan == "pro":
        if max_peak >= 80:
            recommended = "max_100"
            savings = -(PLANS["max_100"]["price"] - PLANS["pro"]["price"])
            reason = f"Usage très élevé ({max_peak}% max). Le Max $100 éviterait les rate-limits."
            action = "upgrade"
        else:
            reason = f"Usage {'correct' if max_peak >= 50 else 'modéré'} ({max_peak}% max). Plan adapté."
    else:
        if max_peak >= 60:
            recommended = "pro"
            savings = -PLANS["pro"]["price"]
            reason = "Usage élevé pour un plan gratuit. Le Pro améliorerait l'expérience."
            action = "upgrade"
        else:
            reason = "Usage compatible avec le plan gratuit."

    caveats = []
    if confidence == "low":
        caveats.append(f"Données sur {days_covered} jours seulement — confirme sur 4 semaines minimum.")
    if current_plan in ("max_100", "max_200") and recommended == "pro":
        caveats.append(
            "Le plan Max offre l'extended thinking (45 min) et la priorité haute "
            "qui ne sont pas dans le Pro. Évalue si tu utilises ces fonctionnalités."
        )

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
            "avg_weekly_peak": round(avg_peak, 1),
            "max_weekly_peak": max_peak,
            "avg_sonnet_peak": round(avg_sonnet_peak, 1),
            "max_sonnet_peak": max_sonnet_peak,
            "days_covered": days_covered,
        },
    }
