"""K3 replay harness — validates the live order-flow overlay against accrued history.

Joins live_snapshots.jsonl (scanner artifacts, every 15 min) with
orderflow_history.jsonl (per-run CVD / delta-z / imbalance records) and asks:

  1. Coverage  — how many historical setups could have been scored with real
                 order flow at the time?
  2. Alignment — when the overlay agreed with the trade direction (of_adj > 0),
                 did the setup's r_now improve by the next snapshot more often
                 than when it disagreed? (sign-vs-drift contingency)
  3. Magnitude — distribution of |of_adj| and its effect on k3_score.

This is an honest research readout, not a backtest: order-flow history starts
accruing from the day the live engine shipped, so early runs have small samples.
The more weeks of data, the sharper the verdict.

Run:  python3 k3.py replay [--window-min 12]
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
SNAPSHOTS = REPORTS / "live_snapshots.jsonl"
OF_HISTORY = REPORTS / "orderflow_history.jsonl"


def _load_jsonl(path: Path) -> List[dict]:
    try:
        out = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
    except FileNotFoundError:
        return []


def _iso_to_ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _nearest_flow(hist: List[dict], ts: float, sym: str, window_sec: float) -> Optional[dict]:
    best, best_dt = None, window_sec
    for h in hist:
        dt = abs(h.get("ts", 0) - ts)
        if dt <= best_dt:
            row = (h.get("symbols") or {}).get(sym)
            if row:
                best, best_dt = row, dt
    return best


def _overlay(flow: Optional[dict], direction: Optional[str]) -> Optional[float]:
    """Same math as the scanner's _orderflow_overlay (kept in sync by test)."""
    if not flow or direction not in ("LONG", "SHORT"):
        return None
    sign = 1.0 if direction == "LONG" else -1.0
    adj = 0.0
    dz, imb, cvd = flow.get("dz"), flow.get("imb"), flow.get("cvd_1m")
    if dz is not None:
        adj += max(-2.0, min(2.0, dz)) * sign * 1.5
    elif cvd:
        adj += sign * (1.0 if cvd > 0 else -1.0) * 0.75
    if imb is not None:
        adj += sign * max(-1.0, min(1.0, imb)) * 4.0
    return round(max(-5.0, min(5.0, adj)), 1)


def replay(window_min: int = 12) -> Dict[str, Any]:
    snaps = _load_jsonl(SNAPSHOTS)
    hist = _load_jsonl(OF_HISTORY)
    window_sec = window_min * 60

    # flatten setups across snapshots, keyed for next-snapshot r_now drift
    setups: List[dict] = []
    for snap in snaps:
        ts = _iso_to_ts(snap.get("generated_utc"))
        for prof, rows in (snap.get("profiles") or {}).items():
            for r in rows or []:
                if r.get("status") in ("ACTIVE", "WATCH") and r.get("direction"):
                    setups.append({
                        "ts": ts, "profile": prof, "symbol": r.get("symbol"),
                        "direction": r.get("direction"), "status": r.get("status"),
                        "k3_score": r.get("k3_score"), "r_now": r.get("r_now"),
                        "key": f"{prof}|{r.get('symbol')}|{r.get('direction')}|{r.get('entry')}",
                    })

    joined, drift_pairs = [], {"agree": [], "disagree": []}
    for s in setups:
        flow = _nearest_flow(hist, s["ts"], s["symbol"], window_sec)
        adj = _overlay(flow, s["direction"])
        if adj is None:
            continue
        rec = dict(s)
        rec["of_adj"] = adj
        joined.append(rec)
        # drift: same setup key in a later snapshot within 3h
        later = [x for x in setups
                 if x["key"] == s["key"] and 0 < x["ts"] - s["ts"] <= 3 * 3600
                 and x.get("r_now") is not None and s.get("r_now") is not None]
        if later:
            drift = min(later, key=lambda x: x["ts"])["r_now"] - s["r_now"]
            (drift_pairs["agree"] if adj > 0 else drift_pairs["disagree"]).append(drift)

    def _stats(xs):
        if not xs:
            return {"n": 0}
        xs = sorted(xs)
        n = len(xs)
        return {"n": n, "mean": round(sum(xs) / n, 3),
                "median": round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 3),
                "pct_positive": round(100.0 * sum(1 for x in xs if x > 0) / n, 1)}

    adjs = [j["of_adj"] for j in joined]
    agree, disagree = drift_pairs["agree"], drift_pairs["disagree"]
    # simple readout: does agreement correlate with forward r_now improvement?
    verdict = "insufficient data"
    if len(agree) >= 10 and len(disagree) >= 10:
        a_pos = sum(1 for x in agree if x > 0) / len(agree)
        d_pos = sum(1 for x in disagree if x > 0) / len(disagree)
        edge = a_pos - d_pos
        verdict = (f"overlay agreement associates with +{edge * 100:.1f}pp forward-drift hit rate"
                   if edge > 0 else
                   f"no positive association detected ({edge * 100:.1f}pp) — review overlay weights")

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "window_min": window_min,
        "snapshots": len(snaps),
        "orderflow_records": len(hist),
        "setups_seen": len(setups),
        "setups_joined": len(joined),
        "coverage_pct": round(100.0 * len(joined) / len(setups), 1) if setups else None,
        "of_adj_distribution": _stats(adjs),
        "forward_drift_when_agree": _stats(agree),
        "forward_drift_when_disagree": _stats(disagree),
        "verdict": verdict,
    }


def print_report(res: Dict[str, Any]) -> None:
    print(f"\nK3 REPLAY — order-flow overlay validation (window ±{res['window_min']}min)")
    print(f"  snapshots={res['snapshots']}  orderflow_records={res['orderflow_records']}  "
          f"setups={res['setups_seen']}  joined={res['setups_joined']} "
          f"(coverage {res['coverage_pct']}%)")
    print(f"  |of_adj| dist: {res['of_adj_distribution']}")
    print(f"  forward r_now drift | overlay AGREED:    {res['forward_drift_when_agree']}")
    print(f"  forward r_now drift | overlay DISAGREED: {res['forward_drift_when_disagree']}")
    print(f"  verdict: {res['verdict']}")
