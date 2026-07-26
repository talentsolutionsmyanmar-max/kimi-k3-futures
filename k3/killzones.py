"""K3 kill zones — ICT session clock (UTC), lineage: ict-quantrex-cursor/session_clock.py.

Standard ICT kill zones mapped to UTC (ET summer / EDT convention):
  ASIA          00:00–04:00 UTC   (20:00–00:00 ET)
  LONDON        06:00–09:00 UTC   (02:00–05:00 ET)  — highest-probability ICT window
  NEW_YORK      11:00–14:00 UTC   (07:00–10:00 ET)  — the classic NY AM kill zone
  NY_PM         17:30–20:00 UTC   (13:30–16:00 ET)
  LONDON_CLOSE  14:00–16:00 UTC   (10:00–12:00 ET)  — reversal-prone, caution

K3 behavior:
  - inside a kill zone: entries get a score boost (liquidity is being engineered there)
  - SCALP profile: outside any kill zone, ACTIVE is demoted to WATCH (discipline)
  - DAY profile: outside kill zone, no demotion, but boost applies inside
  - LONDON_CLOSE is a caution zone: no boost, slight penalty for fresh entries
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ZONES: List[Dict[str, Any]] = [
    {"name": "ASIA",         "start": (0, 0),   "end": (4, 0),   "boost": 1.0, "caution": False},
    {"name": "LONDON",       "start": (6, 0),   "end": (9, 0),   "boost": 3.0, "caution": False},
    {"name": "NEW_YORK",     "start": (11, 0),  "end": (14, 0),  "boost": 3.0, "caution": False},
    {"name": "LONDON_CLOSE", "start": (14, 0),  "end": (16, 0),  "boost": -2.0, "caution": True},
    {"name": "NY_PM",        "start": (17, 30), "end": (20, 0),  "boost": 1.5, "caution": False},
]


def _minute(hm) -> int:
    return hm[0] * 60 + hm[1]


def _in(now_min: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= now_min <= end
    return now_min >= start or now_min <= end  # cross-midnight


def active_zones(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    m = now.hour * 60 + now.minute
    return [z for z in ZONES if _in(m, _minute(z["start"]), _minute(z["end"]))]


def next_zone(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Next upcoming zone with minutes until it opens."""
    now = now or datetime.now(timezone.utc)
    m = now.hour * 60 + now.minute
    best = None
    for z in ZONES:
        s = _minute(z["start"])
        delta = (s - m) % 1440
        if delta == 0:
            delta = 1440
        if best is None or delta < best["opens_in_min"]:
            best = {"name": z["name"], "opens_in_min": delta,
                    "utc_start": f"{z['start'][0]:02d}:{z['start'][1]:02d}"}
    return best or {}


def session_state(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    act = active_zones(now)
    return {
        "utc_iso": now.isoformat(),
        "utc_hhmm": f"{now.hour:02d}:{now.minute:02d}",
        "active": [z["name"] for z in act],
        "in_kill_zone": len(act) > 0,
        "caution": any(z["caution"] for z in act),
        "boost": max((z["boost"] for z in act), default=0.0),
        "next_zone": next_zone(now),
        "all_zones": [
            {"name": z["name"], "utc": f"{z['start'][0]:02d}:{z['start'][1]:02d}-{z['end'][0]:02d}:{z['end'][1]:02d}",
             "caution": z["caution"]}
            for z in ZONES
        ],
    }


def apply_kill_zone_overlay(direction: int, score: float, tier: str, profile_name: str,
                            now: Optional[datetime] = None) -> Dict[str, Any]:
    """Adjust score/tier by session. Returns possibly modified (score, tier) + notes."""
    ss = session_state(now)
    notes: List[str] = []
    adj = 0.0
    if ss["in_kill_zone"] and not ss["caution"]:
        adj += ss["boost"]
        notes.append(f"kill zone {'+'.join(ss['active'])} boost +{ss['boost']:.0f}")
    elif ss["caution"]:
        adj += ss["boost"]  # negative boost
        notes.append(f"{','.join(ss['active'])} caution {ss['boost']:+.0f}")
    if profile_name == "SCALP" and not ss["in_kill_zone"] and tier == "ACTIVE":
        tier = "WATCH"
        notes.append("SCALP outside kill zone: ACTIVE demoted to WATCH")
    return {
        "score": max(0.0, min(100.0, score + adj)),
        "tier": tier,
        "kz_notes": notes,
        "session": ss,
    }
