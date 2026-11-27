"""Check that harness.fastcache gives bit-identical battle logs to the stock engine.

PYTHONPATH=. python tools/verify_fastcache.py [n_seeds]
Runs the same battles in a stock process and a cached process, compares SHA1 of every full log.
"""
import hashlib, json, sys, time
from multiprocessing import Pool

TEAMS = ["examples/best_team.json", "examples/run1000_team.json", "examples/site_default_team.json"]
OPPS = ["public", "policy", "si_patient", "si_altteam_b"]
POLICIES = [None, "examples/best_policy.py"]


def run(args):
    fast, team_path, opp, seed, pol = args
    from harness import evaluate as ev
    if fast:
        from harness.fastcache import install
        install()
    team = json.load(open(team_path, encoding="utf-8"))
    p = ev._load_policy(pol) if pol else None
    t0 = time.perf_counter()
    r = ev.play(team, seed, opp, p, want_log=True)
    return hashlib.sha1(json.dumps(r["log"], sort_keys=True, default=str).encode()).hexdigest(), time.perf_counter() - t0


if __name__ == "__main__":
    from harness.opponents import write_standins
    write_standins()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    jobs = [(t, o, 5_000_000 + s, p) for t in TEAMS for o in OPPS for p in POLICIES for s in range(n)]
    with Pool(maxtasksperchild=1000) as pool:
        stock = pool.map(run, [(False,) + j for j in jobs], chunksize=2)
    with Pool() as pool:
        fast = pool.map(run, [(True,) + j for j in jobs], chunksize=2)
    mism = [j for j, a, b in zip(jobs, stock, fast) if a[0] != b[0]]
    ts, tf = sum(x[1] for x in stock), sum(x[1] for x in fast)
    print(f"{len(jobs)} battles compared, mismatching logs: {len(mism)}  {mism[:5]}")
    print(f"cpu-time per battle: stock {1000*ts/len(jobs):.0f} ms, cached {1000*tf/len(jobs):.0f} ms, speedup x{ts/tf:.1f}")
