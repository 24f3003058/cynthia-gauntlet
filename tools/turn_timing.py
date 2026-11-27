"""Per-turn latency of a policy run through the ORGANISERS' sandbox (engine.policy._SubprocessPolicy).

PYTHONPATH=. python tools/turn_timing.py POLICY.py TEAM.json BATTLES [seed_base] [opponents]

Every battle gets a fresh sandbox process (worst case: every battle has a cold first turn).
Reports median / p99 / max for first turns and for later turns, and fallbacks by reason
(timeouts etc. as reported by the sandbox itself). Run while the machine is loaded to test the
"all cores busy" case.
"""
import json
import statistics
import sys
import time
from pathlib import Path

from engine.policy import load_policy_callable
from harness.evaluate import play


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main():
    pol, team_path, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    base = int(sys.argv[4]) if len(sys.argv) > 4 else 650_000_000
    opps = (sys.argv[5] if len(sys.argv) > 5 else "policy,si_aggressive,si_patient,wr_water,wr_special").split(",")
    team = json.loads(Path(team_path).read_text(encoding="utf-8"))
    first, later, reasons, spawn = [], [], {}, []
    for i in range(n):
        sp = load_policy_callable(Path(pol), sandbox=True)
        orig = sp._spawn

        def _spawn_timed(orig=orig):
            t0 = time.perf_counter()
            orig()
            spawn.append((time.perf_counter() - t0) * 1000)
        sp._spawn = _spawn_timed
        k = [0]

        def timed(obs):
            t0 = time.perf_counter()
            act = sp(obs)
            ms = (time.perf_counter() - t0) * 1000
            if k[0] == 0 and spawn:
                ms -= spawn[-1]   # the sandbox starts its 1 s clock after Popen returns
            (first if k[0] == 0 else later).append(ms)
            k[0] += 1
            r = getattr(sp, "last_fallback_reason", None)
            if r:
                reasons[r.split(":")[0]] = reasons.get(r.split(":")[0], 0) + 1
            return act

        play(team, base + i, opps[i % len(opps)], policy=timed)
        sp.close()
    f = lambda xs: f"median {statistics.median(xs):6.0f}  p99 {pct(xs, .99):6.0f}  max {max(xs):6.0f} ms  (n={len(xs)})"
    print(f"{pol}: {n} battles, fresh sandbox per battle")
    print("  Popen call : " + f(spawn) + "  (before the sandbox clock starts)")
    print("  first turn : " + f(first) + "  (as timed by the sandbox)")
    print("  later turns: " + f(later))
    print("  all turns  : " + f(first + later))
    print(f"  fallbacks  : {sum(reasons.values())} {reasons}")
    print("  first turns > 500 ms:", sum(x > 500 for x in first), " > 1000 ms:", sum(x > 1000 for x in first))


if __name__ == "__main__":
    main()
