"""Coordinate sweep of policy parameters on the CORE opponents (tune seeds, common random numbers).

PYTHONPATH=. python tools/sweep.py TEAM.json POLICY.py N 'JSON list of param dicts' [label]
Prints one line per candidate: mean win rate, per-opponent win rates, avg win turns.
Appends every result to results/sweeps.jsonl (the experiment log references it).
"""
import json
import sys
import time
from pathlib import Path

from harness.evaluate import evaluate
from harness.opponents import CORE as _CORE
import os

# SWEEP_OBJECTIVE=zip: score as the zip's runner would for a policy entry (1/3 'policy' boss variant that replaces
# public, 2/3 mean of the non-public CORE stand-ins). Default: equal-weight CORE.
ZIP = os.environ.get("SWEEP_OBJECTIVE") == "zip"
CORE = (["policy"] + [o for o in _CORE if o != "public"]) if ZIP else list(_CORE)


def _score(s):
    if not ZIP:
        return s["mean_win_rate"]
    po = s["per_opponent"]
    rest = [po[o]["win_rate"] for o in CORE[1:]]
    return po["policy"]["win_rate"] / 3 + 2 / 3 * sum(rest) / len(rest)

if __name__ == "__main__":
    team_path, pol, n, cands = sys.argv[1], sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4])
    label = sys.argv[5] if len(sys.argv) > 5 else ""
    team = json.loads(Path(team_path).read_text(encoding="utf-8"))
    print("opponents:", " ".join(o[:9] for o in CORE))
    for c in cands:
        t0 = time.time()
        s, _ = evaluate(team, pol, CORE, n, "tune", params=c)
        per = " ".join(f"{100*s['per_opponent'][o]['win_rate']:5.1f}" for o in CORE)
        print(f"{100*_score(s):6.2f}  [{per}]  wt={s['avg_win_turns']:.2f} fb={s['total_fallbacks']} "
              f"{json.dumps(c)}  ({time.time()-t0:.0f}s)", flush=True)
        with open("results/sweeps.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(label=label, team=team_path, policy=pol, n=n, params=c,
                                    mean=_score(s), objective="zip" if ZIP else "core", avg_win_turns=s["avg_win_turns"],
                                    fallbacks=s["total_fallbacks"],
                                    per={o: s["per_opponent"][o]["win_rate"] for o in CORE})) + "\n")
