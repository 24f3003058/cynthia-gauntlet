"""Parallel, reproducible evaluation harness.

    PYTHONPATH=. python -m harness.evaluate --team team.json [--policy policy.py] \
        [--opponents core|all|public,si_patient,...] [--n 500] [--seeds tune|test|<int base>] [--out results/x.json]

* Battle loop = engine.runner.run_battle's loop, except the requested opponent is always used
  (the stock runner silently replaces 'public' with 'policy' when a policy is given).
* Seeds: battle i vs opponent o uses seed BASE + i (same seeds for every opponent and candidate:
  common random numbers make A/B comparisons much less noisy).
  TUNE base = 1_000_000, TEST base = 900_000_000 (never used for tuning).
* Every policy fallback (exception, non-dict, illegal action, >1 s) is counted by reason.
* Wilson 95% CIs per opponent; overall = mean of per-opponent win rates (equal weights).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from multiprocessing import Pool
from pathlib import Path

SEED_BASES = {"tune": 1_000_000, "test": 900_000_000}
TURN_LIMIT_S = 1.0

_POLICY = None
_POLICY_NAME = "baseline"


def _load_policy(path, params=None, debug=True):
    """Load a policy file in-process after the official AST scan.
    params: dict merged into the module's P (tuning). debug: set DEBUG_RAISE so internal
    errors surface as counted fallbacks instead of being swallowed by the policy's own guard."""
    import importlib.util
    from engine.policy import scan_policy_source
    src = Path(path).read_text(encoding="utf-8")
    bad = scan_policy_source(src)
    if bad:
        raise ValueError(f"policy rejected by scanner: {bad}")
    spec = importlib.util.spec_from_file_location(f"_pol_{abs(hash(path))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if params:
        mod.P.update(params)
    if debug and hasattr(mod, "DEBUG_RAISE"):
        mod.DEBUG_RAISE = True
    return mod.choose_move


def _init(policy_path, fast, params=None):
    global _POLICY, _POLICY_NAME
    if fast:
        from harness.fastcache import install
        install()
    if policy_path:
        _POLICY = _load_policy(policy_path, params)
        _POLICY_NAME = policy_path


def play(team, seed, opponent, policy=None, want_log=False):
    """One battle. Returns dict(win, turns, end, fallbacks[list], max_ms)."""
    from engine.runner import _get_data, parse_team
    from engine.baseline_policy import choose_move as baseline
    from engine.battle import Battle
    from engine.cynthia import CynthiaBot
    from harness.opponents import config_path

    data = _get_data()
    team = parse_team(team)
    bot = CynthiaBot(variant=opponent, config_path=config_path(opponent))
    b = Battle(team_a=team, team_b=bot.team_for_seed(seed), seed=seed, data=data, variant=opponent)
    fallbacks, max_ms = [], 0.0

    def call(obs, forced):
        nonlocal max_ms
        if policy is None:
            return baseline(obs)
        t0 = time.perf_counter()
        try:
            act = policy(obs)
        except Exception as e:  # mirrors _InProcessPolicy: exception -> baseline
            fallbacks.append(f"exception:{type(e).__name__}:{e}")
            return baseline(obs)
        ms = (time.perf_counter() - t0) * 1000.0
        max_ms = max(max_ms, ms)
        if ms > TURN_LIMIT_S * 1000.0:
            fallbacks.append("timeout")
            return baseline(obs)
        if not isinstance(act, dict):
            fallbacks.append("non_dict")
            return baseline(obs)
        if forced:
            ok = act.get("action") == "switch" and act.get("index") in [
                a["index"] for a in obs["legal_actions"] if a.get("action") == "switch"]
        else:
            ok = b._is_legal("a", act)
        if not ok:
            fallbacks.append(f"illegal:{act}")
            return baseline(obs)
        return act

    def pick_switch(obs, act):
        legal = [a["index"] for a in obs["legal_actions"] if a.get("action") == "switch"]
        i = act.get("index") if isinstance(act, dict) and act.get("action") == "switch" else None
        return i if i in legal else legal[0]

    while not b.is_over:
        if b.needs_replacement("a"):
            o = b.observation("a")
            b.replace("a", pick_switch(o, call(o, True)))
        if b.needs_replacement("b"):
            o = b.observation("b")
            b.replace("b", pick_switch(o, bot.choose_move(o)))
        if b.is_over:
            break
        if not b.needs_replacement("a") and not b.needs_replacement("b"):
            b.step(call(b.observation("a"), False), bot.choose_move(b.observation("b")))
    out = dict(win=b.winner == "a", turns=b.turn, end=b.end_reason, fallbacks=fallbacks, max_ms=max_ms)
    if want_log:
        out["log"] = b.log
    return out


def _task(args):
    team, seed, opp = args
    r = play(team, seed, opp, _POLICY)
    r.update(seed=seed, opp=opp)
    return r


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def summarise(results, opponents):
    per = {}
    for o in opponents:
        rs = [r for r in results if r["opp"] == o]
        n, k = len(rs), sum(r["win"] for r in rs)
        wt = [r["turns"] for r in rs if r["win"]]
        lo, hi = wilson(k, n)
        fb = {}
        for r in rs:
            for f in r["fallbacks"]:
                key = f.split(":")[0]
                fb[key] = fb.get(key, 0) + 1
        per[o] = dict(n=n, wins=k, win_rate=k / n if n else 0.0, ci95=[lo, hi],
                      avg_win_turns=sum(wt) / len(wt) if wt else None,
                      turn_limit=sum(r["end"] == "turn_limit_reached" for r in rs),
                      fallbacks=fb, max_policy_ms=max((r["max_ms"] for r in rs), default=0.0))
    wrs = [p["win_rate"] for p in per.values()]
    # SE of the mean of independent per-opponent proportions
    se = math.sqrt(sum(p["win_rate"] * (1 - p["win_rate"]) / max(1, p["n"]) for p in per.values())) / len(per)
    mean = sum(wrs) / len(wrs)
    all_wt = [r["turns"] for r in results if r["win"]]
    return dict(per_opponent=per, mean_win_rate=mean, mean_ci95=[mean - 1.96 * se, mean + 1.96 * se],
                worst=min(per, key=lambda o: per[o]["win_rate"]),
                avg_win_turns=sum(all_wt) / len(all_wt) if all_wt else None,
                total_fallbacks=sum(sum(p["fallbacks"].values()) for p in per.values()))


def evaluate(team, policy_path=None, opponents=None, n=200, seed_base="tune", workers=None, fast=True,
             pool=None, params=None):
    from harness.opponents import CORE, write_standins
    write_standins()
    opponents = opponents or CORE
    base = SEED_BASES.get(seed_base, seed_base) if isinstance(seed_base, str) else seed_base
    tasks = [(team, base + i, o) for o in opponents for i in range(n)]
    if pool is not None:
        results = pool.map(_task, tasks, chunksize=4)
    else:
        with Pool(workers or os.cpu_count(), initializer=_init, initargs=(policy_path, fast, params)) as p:
            results = p.map(_task, tasks, chunksize=4)
    return summarise(results, opponents), results


def _fingerprint(team, policy_path):
    h = hashlib.sha1(json.dumps(team, sort_keys=True).encode())
    if policy_path:
        h.update(Path(policy_path).read_bytes())
    return h.hexdigest()[:10]


def print_summary(s, label=""):
    print(f"== {label}")
    for o, p in s["per_opponent"].items():
        lo, hi = p["ci95"]
        awt = f"{p['avg_win_turns']:.1f}" if p["avg_win_turns"] else "  - "
        fb = ",".join(f"{k}={v}" for k, v in p["fallbacks"].items()) or "0"
        print(f"  {o:14} {100*p['win_rate']:5.1f}%  [{100*lo:4.1f},{100*hi:4.1f}]  win-turns {awt:>5}  "
              f"turnlimit {p['turn_limit']}  fallbacks {fb}  max {p['max_policy_ms']:.0f}ms")
    lo, hi = s["mean_ci95"]
    print(f"  MEAN {100*s['mean_win_rate']:.2f}% [{100*lo:.1f},{100*hi:.1f}]  worst={s['worst']}  "
          f"avg-win-turns={s['avg_win_turns'] and round(s['avg_win_turns'], 2)}  fallbacks={s['total_fallbacks']}",
          flush=True)


def main():
    from harness.opponents import CORE, SHIPPED, STANDINS
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--opponents", default="core")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seeds", default="tune")
    ap.add_argument("--no-fast", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--params", default=None, help="JSON dict merged into the policy's P")
    a = ap.parse_args()
    opps = {"core": CORE, "all": SHIPPED + [k for k in STANDINS], "shipped": SHIPPED}.get(a.opponents) \
        or a.opponents.split(",")
    team = json.loads(Path(a.team).read_text(encoding="utf-8"))
    from engine.validator import validate_team, calculate_team_cost
    ok, errs = validate_team(team)
    print(f"team {a.team}: legal={ok} {errs} cost={calculate_team_cost(team)}  policy={a.policy or 'baseline'}  "
          f"fp={_fingerprint(team, a.policy)}")
    seed_base = int(a.seeds) if a.seeds.isdigit() else a.seeds
    t0 = time.time()
    params = json.loads(a.params) if a.params else None
    s, _ = evaluate(team, a.policy, opps, a.n, seed_base, fast=not a.no_fast, params=params)
    dt = time.time() - t0
    print_summary(s, f"{a.n} battles/opponent, seeds={a.seeds}, {len(opps)*a.n/dt:.1f} battles/s")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(dict(team=a.team, policy=a.policy, n=a.n, seeds=a.seeds,
                                               fingerprint=_fingerprint(team, a.policy), summary=s), indent=1))


if __name__ == "__main__":
    main()
