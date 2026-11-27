"""Phase-1 measurement harness (does not modify the engine).

usage: python tools/phase1_eval.py TEAM.json POLICY.py|baseline N VARIANTS [mode]
mode = "runner": engine.runner.run_battle as shipped (a custom policy turns 'public' into 'policy')
mode = "direct": same loop as run_battle, but the requested variant is always used
Prints win rate, Wilson 95% CI, avg turns in wins, turn-limit losses, fallbacks, speed.
"""
import json, math, sys, time
from multiprocessing import Pool

_POL = None

def _init(policy_path):
    global _POL
    if policy_path != "baseline":
        from engine.policy import load_policy_callable
        from pathlib import Path
        _POL = load_policy_callable(Path(policy_path), sandbox=False)

def _direct(team, seed, variant, policy):
    """Copy of engine.runner.run_battle's loop without the public->policy override."""
    from engine.runner import _get_data, parse_team
    from engine.baseline_policy import choose_move as base
    from engine.battle import Battle
    from engine.cynthia import CynthiaBot
    data = _get_data(); team = parse_team(team)
    cyn = CynthiaBot(variant=variant); policy = policy or base
    b = Battle(team_a=team, team_b=cyn.team_for_seed(seed), seed=seed, data=data, variant=variant)
    fb = []
    def call(obs, forced):
        if hasattr(policy, "last_fallback_reason"): policy.last_fallback_reason = None
        act = policy(obs); r = getattr(policy, "last_fallback_reason", None)
        if r: fb.append(r); return act
        if forced:
            ok = isinstance(act, dict) and act.get("action") == "switch" and act.get("index") in [a["index"] for a in obs["legal_actions"] if a.get("action") == "switch"]
        else:
            ok = b._is_legal("a", act)
        if not ok: fb.append(f"illegal: {act}"); return base(obs)
        return act
    while not b.is_over:
        if b.needs_replacement("a"):
            o = b.observation("a"); a = call(o, True)
            ls = [x["index"] for x in o["legal_actions"] if x.get("action") == "switch"]
            i = a.get("index") if a.get("action") == "switch" else None
            b.replace("a", i if i in ls else ls[0])
        if b.needs_replacement("b"):
            o = b.observation("b"); a = cyn.choose_move(o)
            ls = [x["index"] for x in o["legal_actions"] if x.get("action") == "switch"]
            i = a.get("index") if a.get("action") == "switch" else None
            b.replace("b", i if i in ls else ls[0])
        if b.is_over: break
        if not b.needs_replacement("a") and not b.needs_replacement("b"):
            b.step(call(b.observation("a"), False), cyn.choose_move(b.observation("b")))
    return b.winner == "a", b.turn, b.end_reason, fb

def _run(args):
    team, seed, variant, mode = args
    if mode == "direct":
        return _direct(team, seed, variant, _POL)
    from engine.runner import run_battle
    r = run_battle(team, seed=seed, variant=variant, policy=_POL)
    return r["result"] == "win", r["turns"], r["end_reason"], [f["reason"] for f in r["policy_fallbacks"]]

def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h

if __name__ == "__main__":
    team_path, pol, n, variants = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].split(",")
    mode = sys.argv[5] if len(sys.argv) > 5 else "runner"
    team = json.load(open(team_path, encoding="utf-8"))
    from engine.validator import validate_team, calculate_team_cost
    print(f"team={team_path} policy={pol} mode={mode} legal={validate_team(team)} cost={calculate_team_cost(team)}", flush=True)
    with Pool(initializer=_init, initargs=(pol,)) as pool:
        for v in variants:
            t0 = time.time()
            res = pool.map(_run, [(team, 10_000_000 + s, v, mode) for s in range(n)], chunksize=4)
            dt = time.time() - t0
            k = sum(r[0] for r in res); lo, hi = wilson(k, n)
            wt = [r[1] for r in res if r[0]]; tl = sum(r[2] == "turn_limit_reached" for r in res)
            fbs = sum(len(r[3]) for r in res)
            print(f"  {v:10} win {100*k/n:5.1f}%  CI[{100*lo:4.1f},{100*hi:4.1f}]  win-turns {sum(wt)/max(1,len(wt)):5.1f}  turnlimit {tl}  fallbacks {fbs}  {n/dt:5.1f}/s", flush=True)
