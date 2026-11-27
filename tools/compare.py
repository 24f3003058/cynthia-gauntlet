"""Paired comparison of several (team, policy) entries on IDENTICAL seeds and opponents.

PYTHONPATH=. python tools/compare.py --entries A=TEAM.json:POLICY.py,B=TEAM.json:baseline --opponents o1,o2 \
    --n 1000 --seed-base 700000000 [--exclude wr_legends] [--out results/x.json]

For each opponent: win rate + Wilson 95% CI per entry; paired difference vs the FIRST entry with a 95% CI
(normal approximation on the per-seed differences). Equal-weight mean over opponents (+ CI), optionally also
excluding some opponents. Does NOT call harness.evaluate.evaluate (which rewrites every stand-in file); opponent
config files must already exist (harness/standins/*.json or variants/*.json).
"""
import argparse
import json
import math
import os
import time
from multiprocessing import Pool
from pathlib import Path

from harness.evaluate import _init, _task, wilson


def run(team, policy, opponents, n, base, workers=None):
    pol = None if policy == "baseline" else policy
    tasks = [(team, base + i, o) for o in opponents for i in range(n)]
    with Pool(workers or os.cpu_count(), initializer=_init, initargs=(pol, True, None)) as p:
        res = p.map(_task, tasks, chunksize=8)
    return {(r["opp"], r["seed"]): r for r in res}


def summarise(res, opponents, n, base):
    out = {}
    for o in opponents:
        rs = [res[(o, base + i)] for i in range(n)]
        k = sum(r["win"] for r in rs)
        wt = [r["turns"] for r in rs if r["win"]]
        fb = sum(len(r["fallbacks"]) for r in rs)
        out[o] = dict(win=k / n, ci=wilson(k, n), avg_win_turns=(sum(wt) / len(wt)) if wt else None,
                      fallbacks=fb, turn_limit=sum(r["end"] == "turn_limit" for r in rs),
                      max_ms=max(r["max_ms"] for r in rs))
    return out


def paired(ra, rb, opponents, n, base):
    """mean and 95% CI of (b - a) per opponent and for the equal-weight mean."""
    per, var_sum = {}, 0.0
    for o in opponents:
        d = [int(rb[(o, base + i)]["win"]) - int(ra[(o, base + i)]["win"]) for i in range(n)]
        m = sum(d) / n
        v = sum((x - m) ** 2 for x in d) / (n - 1) if n > 1 else 0.0
        h = 1.96 * math.sqrt(v / n)
        per[o] = (m, m - h, m + h)
        var_sum += v / n
    k = len(opponents)
    mm = sum(p[0] for p in per.values()) / k
    hh = 1.96 * math.sqrt(var_sum) / k
    return per, (mm, mm - hh, mm + hh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", required=True)
    ap.add_argument("--opponents", required=True)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed-base", type=int, required=True)
    ap.add_argument("--exclude", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    opps = a.opponents.split(",")
    excl = [x for x in a.exclude.split(",") if x]
    entries = []
    for e in a.entries.split(","):
        label, rest = e.split("=", 1)
        team_path, pol = rest.split(":", 1)
        entries.append((label, team_path, pol))
    raw, summ = {}, {}
    for label, team_path, pol in entries:
        t0 = time.time()
        team = json.loads(Path(team_path).read_text(encoding="utf-8"))
        raw[label] = run(team, pol, opps, a.n, a.seed_base, a.workers)
        summ[label] = summarise(raw[label], opps, a.n, a.seed_base)
        print(f"ran {label} ({len(raw[label])} battles, {time.time()-t0:.0f}s)", flush=True)
    labels = [e[0] for e in entries]
    ref = labels[0]
    print(f"\nseeds {a.seed_base}..{a.seed_base + a.n - 1}, {a.n} battles/opponent, identical for every entry")
    print(f"{'opponent':14}" + "".join(f"{l:>22}" for l in labels) +
          "".join(f"{'diff ' + l + '-' + ref:>26}" for l in labels[1:]))
    report = dict(seed_base=a.seed_base, n=a.n, opponents=opps, entries=entries, per={}, means={}, diffs={})
    for o in opps:
        row = f"{o:14}"
        for l in labels:
            s = summ[l][o]
            row += f"   {100*s['win']:5.1f} [{100*s['ci'][0]:4.1f},{100*s['ci'][1]:4.1f}]"
        for l in labels[1:]:
            per, _ = paired(raw[ref], raw[l], [o], a.n, a.seed_base)
            m, lo, hi = per[o]
            flag = " *" if lo > 0 else (" -" if hi < 0 else "  ")
            row += f"    {100*m:+5.1f} [{100*lo:+5.1f},{100*hi:+5.1f}]{flag}"
        print(row)
    for subset_name, subset in (("ALL", opps), (f"excl {','.join(excl)}", [o for o in opps if o not in excl])):
        if subset_name.startswith("excl") and not excl:
            continue
        row = f"{'MEAN ' + subset_name:14}"
        for l in labels:
            k = len(subset)
            m = sum(summ[l][o]["win"] for o in subset) / k
            v = sum(summ[l][o]["win"] * (1 - summ[l][o]["win"]) / a.n for o in subset) / k ** 2
            row += f"   {100*m:5.2f} [{100*(m-1.96*math.sqrt(v)):4.1f},{100*(m+1.96*math.sqrt(v)):4.1f}]"
            report["means"][f"{l}|{subset_name}"] = m
        for l in labels[1:]:
            _, (m, lo, hi) = paired(raw[ref], raw[l], subset, a.n, a.seed_base)
            flag = " *" if lo > 0 else (" -" if hi < 0 else "  ")
            row += f"    {100*m:+5.2f} [{100*lo:+5.2f},{100*hi:+5.2f}]{flag}"
            report["diffs"][f"{l}-{ref}|{subset_name}"] = (m, lo, hi)
        print(row)
    for l in labels:
        fb = sum(summ[l][o]["fallbacks"] for o in opps)
        tl = sum(summ[l][o]["turn_limit"] for o in opps)
        wts = [summ[l][o]["avg_win_turns"] for o in opps if summ[l][o]["avg_win_turns"]]
        print(f"{l}: fallbacks {fb}, turn-limit losses {tl}, mean avg-win-turns "
              f"{sum(wts)/len(wts):.2f}, max policy ms {max(summ[l][o]['max_ms'] for o in opps):.0f}")
    print("(* = difference > 0 at 95%, - = < 0 at 95%)")
    report["per"] = summ
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
