"""Phase-1 measurement: baseline-policy win rate per variant, Wilson 95% CI, throughput."""
import json, math, sys, time
from multiprocessing import Pool

def _run(args):
    team, seed, variant = args
    from engine.runner import run_battle
    r = run_battle(team, seed=seed, variant=variant)
    return r["result"] == "win", r["turns"], r["end_reason"]

def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h

if __name__ == "__main__":
    team = json.load(open(sys.argv[1], encoding="utf-8"))
    n = int(sys.argv[2]); variants = sys.argv[3].split(","); base = int(sys.argv[4]) if len(sys.argv) > 4 else 10_000_000
    from engine.validator import validate_team
    print("validator:", validate_team(team))
    with Pool() as pool:
        for v in variants:
            t0 = time.time()
            res = pool.map(_run, [(team, base + s, v) for s in range(n)], chunksize=8)
            dt = time.time() - t0
            k = sum(w for w, _, _ in res); lo, hi = wilson(k, n)
            wt = [t for w, t, _ in res if w]
            tl = sum(1 for _, _, e in res if e == "turn_limit_reached")
            print(f"{v:10} win {100*k/n:5.1f}%  95%CI [{100*lo:4.1f},{100*hi:4.1f}]  avg win turns {sum(wt)/max(1,len(wt)):5.1f}  turn-limit {tl}  {n/dt:6.1f} battles/s")
