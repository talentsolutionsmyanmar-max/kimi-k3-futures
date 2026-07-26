#!/usr/bin/env python3
"""KIMI K3 — autonomous crypto futures system (scalp + day). Signal/paper only.

Usage:
  python k3.py top10
  python k3.py scan --profile both [--symbols BTCUSDT ...] [--capital 10000]
  python k3.py backtest --profile both [--limit 1500]
  python k3.py research --profile scalp [--limit 1500]   # walk-forward validation
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from k3.config import PROFILES, clone_profile, get_profile
from k3.data import discover_top10, quote_volume_24h
from k3.engine import scan_universe
from k3.backtest import backtest_universe
from k3.research import research_universe

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


def _save(name: str, payload: dict) -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def _print_setup(r: dict) -> None:
    st = r.get("status")
    if st in ("ACTIVE", "WATCH"):
        tp = r["trade_plan"]
        print(
            f"\n[{st}] {r['symbol']} {r['direction']}  K3={r['k3_score']:.1f} "
            f"(agree {r['groups_agreeing']}/5)  struct={r['struct_state']} pd={r['pd_position']} "
            f"HTF={r['htf_bias']}{'!' if r['htf_conflict'] else ''}  "
            f"fz={r['funding_z']} dOI1h={r['oi_delta_1h_pct']}%  age={r['signal_age_minutes']}min"
        )
        print(f"  groups: " + "  ".join(f"{k[0].upper()}={v:+.0f}" for k, v in r["group_scores"].items()))
        print(f"  entry {r['trade_plan']['entry']:,.6g}  stop {tp['stop']:,.6g} (-{tp['stop_distance_pct']}%)")
        for t in tp["tp_ladder"]:
            print(f"    TP@{t['R']}R {t['price']:,.6g} close {int(t['close_pct']*100)}%")
        print(
            f"  risk ${tp['risk_usd']} (x{tp['risk_multiplier']})  qty {tp['quantity']:g}  "
            f"notional ${tp['notional_usd']:,.0f}  lev ~{tp['leverage_suggested']}x"
            f"{' CAPPED' if tp['leverage_capped'] else ''}  EV ladder {tp['ladder_expected_R']}R  "
            f"trail {tp['trail_atr_mult']}xATR after TP1, max {tp['max_hold_bars']} bars"
        )
        if r.get("overlay_notes"):
            print(f"  positioning: {'; '.join(r['overlay_notes'])}")
        print(f"  gates: {', '.join(r['market_gates']['reasons'])}")
    else:
        w = r.get("watch")
        extra = f" | watch: {w['side']} best={w['best_subthreshold_score']}" if w else ""
        gates = r.get("market_gates", {})
        gtxt = "" if gates.get("ok", True) else f" | GATE FAIL: {', '.join(gates.get('reasons', []))}"
        print(f"\n[{st}] {r['symbol']} — {r.get('reason', '')}{extra}{gtxt}")


def cmd_top10(_a) -> None:
    print("K3 universe — top-10 USDT-M perps by 24h quote volume:")
    for i, s in enumerate(discover_top10(), 1):
        try:
            print(f"  {i:>2}. {s:<14} ${quote_volume_24h(s):,.0f}")
        except Exception:
            print(f"  {i:>2}. {s}")


def _profiles(name: str):
    return list(PROFILES) if name == "both" else [name]


def cmd_scan(a) -> None:
    from k3.killzones import session_state
    symbols = [s.upper() for s in a.symbols] if a.symbols else discover_top10()
    ss = session_state()
    print(f"SESSION {ss['utc_hhmm']}Z  kill_zones={ss['active'] or 'NONE'}"
          f"{' CAUTION' if ss['caution'] else ''}  next={ss['next_zone'].get('name')} in {ss['next_zone'].get('opens_in_min')}min")
    payload = {"generated_utc": datetime.now(timezone.utc).isoformat(), "session": ss,
               "universe": symbols, "profiles": {}}
    for name in _profiles(a.profile):
        p = clone_profile(get_profile(name), initial_capital=a.capital)
        print(f"\n>>> K3 scanning {len(symbols)} symbols | {p.name} {p.timeframe} (ctx {p.context_tf})")
        res = scan_universe(symbols, p, a.capital)
        print(f"\n{'='*100}\nK3 {p.name}  (UTC {datetime.now(timezone.utc):%Y-%m-%d %H:%M})\n{'='*100}")
        for r in res:
            _print_setup(r)
        payload["profiles"][p.name] = res
    path = _save(f"k3_scan_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", payload)
    print(f"\nreport: {path}")


def cmd_backtest(a) -> None:
    symbols = [s.upper() for s in a.symbols] if a.symbols else discover_top10()
    payload = {"generated_utc": datetime.now(timezone.utc).isoformat(), "profiles": {}}
    for name in _profiles(a.profile):
        p = clone_profile(get_profile(name), initial_capital=a.capital)
        print(f"\n>>> K3 backtesting {len(symbols)} symbols | {p.name} {p.timeframe} bars={a.limit}")
        res = backtest_universe(symbols, p, a.limit)
        payload["profiles"][p.name] = res
        print(f"\n{p.name}: trades={res['total_trades']} win={res['avg_win_rate']}% "
              f"net=${res['total_net_pnl_usd']:,.2f} avg_ret={res['avg_return_pct']}%")
        for x in res["per_symbol"]:
            if x.get("trades", 0) > 0:
                print(f"  {x['symbol']:<14} n={x['trades']:<4} win={x['win_rate']}% "
                      f"pnl=${x['net_pnl_usd']:>9,.2f} PF={x['profit_factor']} DD={x['max_drawdown_pct']}% "
                      f"funding=${x['funding_paid_total']:.0f} tiers={x['pnl_by_tier']}")
            else:
                print(f"  {x['symbol']:<14} {x.get('note') or x.get('error')}")
    path = _save(f"k3_backtest_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", payload)
    print(f"\nreport: {path}")


def cmd_research(a) -> None:
    symbols = [s.upper() for s in a.symbols] if a.symbols else discover_top10()
    p = get_profile(a.profile)
    print(f"\n>>> K3 walk-forward research | {p.name} {p.timeframe} bars={a.limit} "
          f"grid={5*4*3} combos/symbol (train 60% / OOS 40%)")
    res = research_universe(symbols, p, a.limit)
    print(f"\nCONSENSUS (params in top-3 across most symbols):")
    for c in res["consensus"]:
        print(f"  atr_stop={c['atr_stop_mult']}  tier_active={c['tier_active']}  "
              f"tp={c['tp_variant']}  votes={c['symbols_voting']}/{len(symbols)}")
    for r in res["per_symbol"]:
        print(f"\n{r['symbol']}  (combos passing train gate: {r.get('combos_passed_train', 0)})")
        for t in r.get("top", [])[:3]:
            print(f"   {t['params']}  trainPF={t['train']['pf']}  "
                  f"OOS: n={t['oos']['trades']} win={t['oos']['win_rate']}% "
                  f"PF={t['oos']['pf']} ret={t['oos']['ret_pct']}% DD={t['oos']['max_dd']}%")
    path = _save(f"k3_research_{p.name}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", res)
    print(f"\nreport: {path}")


def cmd_replay(a) -> None:
    from k3.replay import replay, print_report
    res = replay(window_min=a.window_min)
    print_report(res)
    path = _save(f"k3_replay_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", res)
    print(f"\nreport: {path}")


def cmd_universe(a) -> None:
    from k3.screener import screen, print_report
    res = screen(top_n=a.top)
    uni = discover_top10()
    print_report(res, uni)
    res["current_universe"] = uni
    path = _save(f"k3_universe_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", res)
    print(f"\nreport: {path}")


def cmd_leaktest(a) -> None:
    from k3.leaktest import leaktest, print_report
    for name in _profiles(a.profile):
        res = leaktest(get_profile(name), seeds=a.seeds, bars=a.bars)
        print_report(res)
        path = _save(f"k3_leaktest_{name}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", res)
        print(f"report: {path}")
        if not res["passed"]:
            sys.exit(1)


def cmd_causaltest(a) -> None:
    from k3.causaltest import causaltest, print_report
    for name in _profiles(a.profile):
        res = causaltest(get_profile(name), seed=a.seed, bars=a.bars)
        print_report(res)
        path = _save(f"k3_causaltest_{name}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json", res)
        print(f"report: {path}")
        if not res["passed"]:
            sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="KIMI K3 futures system")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("top10"); p.set_defaults(fn=cmd_top10)

    p = sub.add_parser("universe")
    p.add_argument("--top", type=int, default=25)
    p.set_defaults(fn=cmd_universe)

    p = sub.add_parser("scan")
    p.add_argument("--profile", default="both", choices=["scalp", "day", "both"])
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--capital", type=float, default=10_000.0)
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("backtest")
    p.add_argument("--profile", default="both", choices=["scalp", "day", "both"])
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--limit", type=int, default=1500)
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("research")
    p.add_argument("--profile", default="scalp", choices=["scalp", "day"])
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--limit", type=int, default=1500)
    p.set_defaults(fn=cmd_research)

    p = sub.add_parser("replay")
    p.add_argument("--window-min", type=int, default=12)
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("leaktest")
    p.add_argument("--profile", default="both", choices=["scalp", "day", "both"])
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--bars", type=int, default=1200)
    p.set_defaults(fn=cmd_leaktest)

    p = sub.add_parser("causaltest")
    p.add_argument("--profile", default="both", choices=["scalp", "day", "both"])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--bars", type=int, default=600)
    p.set_defaults(fn=cmd_causaltest)

    args = ap.parse_args()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
