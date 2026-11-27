"""Phase 4 team search: cheap analytic screen -> staged battle simulation -> local search.

PYTHONPATH=. python tools/team_search.py screen   [--restarts 40]           -> results/screen.json
PYTHONPATH=. python tools/team_search.py simulate [--top 30] [--policy P]   -> results/sim_stage*.json
PYTHONPATH=. python tools/team_search.py local    --start TEAM.json [--iters 60] [--policy P|baseline]

Screen (no battles): for every legal species, greedy 4-move coverage set vs the CORE opponent pool,
1v1 win probabilities from the policy's own duel model (exact damage distributions, speed, priority,
Cynthia's move choice), then simulated annealing over 40-point teams maximising
mean over opponents of mean over their Pokemon of (0.6*best answer + 0.4*second-best answer).
Simulation/local search use harness.evaluate on CORE with tune seeds (common random numbers).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import time
from multiprocessing import Pool
from pathlib import Path

from engine.data import load_all, get_unsupported_moves
from harness.opponents import CORE, WIDE_RAND, WIDE_TUNE, config_path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "policy_build" / "policy.py"


def load_policy_module(path=POLICY):
    spec = importlib.util.spec_from_file_location("polmod", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def opponent_pool():
    """{(species, moves tuple): weight} — each CORE opponent team has total weight 1."""
    pool = {}
    for o in CORE:
        team = json.loads(Path(config_path(o)).read_text(encoding="utf-8"))["team"]
        for m in team:
            k = (m["species"], tuple(m["moves"]))
            pool[k] = pool.get(k, 0.0) + 1.0 / (len(team) * len(CORE))
    return pool


def candidates(data, pm, pool):
    """Per legal species: up to 2 movesets (greedy coverage; greedy with best priority move)."""
    U = get_unsupported_moves()
    out = {}
    foes = [(pm._foe(sp), w) for (sp, _), w in pool.items()]
    for sp, p in data.pokemon.items():
        if not p.is_default_form or p.is_legendary or p.is_mythical:
            continue
        cost = data.costs.get(sp, 99)
        if cost > 40:
            continue
        X = mon_dict(pm, p)
        mvs = [m for m in data.learnsets.get(sp, ()) if m not in U and m in pm._MOVES
               and (pm._MOVES[m][2] > 0 or m in pm._FIXED or m in pm._OHKO)]
        if len(mvs) < 4:
            continue
        val = {m: [min(1.0, pm._mean(pm._single(X, F, m, pm._MOVES[m])) / F["hp"]) for F, _ in foes] for m in mvs}
        ws = [w for _, w in foes]

        def greedy(start):
            chosen = list(start)
            while len(chosen) < 4:
                best, bs = None, -1
                for m in mvs:
                    if m in chosen:
                        continue
                    s = sum(w * max(val[c][i] for c in chosen + [m]) for i, w in enumerate(ws))
                    if s > bs:
                        best, bs = m, s
                chosen.append(best)
            return tuple(chosen)

        sets = [greedy([])]
        pri = [m for m in mvs if pm._MOVES[m][4] > 0]
        if pri:
            bp = max(pri, key=lambda m: sum(w * val[m][i] for i, w in enumerate(ws)))
            if bp not in sets[0]:
                sets.append(greedy([bp]))
        out[sp] = dict(cost=cost, sets=sets)
    return out


def mon_dict(pm, p):
    st = lambda b: (2 * b + 31) * 50 // 100 + 5
    return {"types": tuple(t for t in (p.type1, p.type2) if t), "hp": (2 * p.hp + 31) * 50 // 100 + 60,
            "atk": st(p.attack), "def": st(p.defense), "spa": st(p.sp_atk), "spd": st(p.sp_def),
            "spe": st(p.speed), "key": ("me", p.identifier)}


def matchup(data, pm, cands, pool):
    """M[(species, set_idx)] = list of P(win 1v1 from full HP) vs each pool member."""
    foes = list(pool.items())
    M = {}
    for sp, c in cands.items():
        X = mon_dict(pm, data.pokemon[sp])
        for i, s in enumerate(c["sets"]):
            xm = [(m, pm._MOVES[m]) for m in s]
            row = []
            for (fsp, fmoves), _ in foes:
                F = pm._foe(fsp)
                fm = [(m, pm._MOVES[m]) for m in fmoves if m in pm._MOVES]
                row.append(pm._duel_from_raw(X, xm, X["hp"], F, fm, F["hp"], ())[1])
            M[(sp, i)] = row
    return M, [w for _, w in foes]


def team_score(team, M, ws):
    rows = [M[k] for k in team]
    s = 0.0
    for j, w in enumerate(ws):
        col = sorted((r[j] for r in rows), reverse=True)
        s += w * (0.6 * col[0] + 0.4 * col[1])
    return s


def anneal(cands, M, ws, restarts=40, steps=6000, seed=0, budget=40):
    rng = random.Random(seed)
    keys = [(sp, i) for sp, c in cands.items() for i in range(len(c["sets"]))]
    cost = {k: cands[k[0]]["cost"] for k in keys}
    found = {}
    for r in range(restarts):
        team = []
        while len(team) < 6:
            k = rng.choice(keys)
            if k[0] not in {t[0] for t in team} and sum(cost[t] for t in team) + cost[k] <= budget - (5 - len(team)):
                team.append(k)
        cur = team_score(team, M, ws)
        T0 = 0.02
        for it in range(steps):
            T = T0 * (1 - it / steps) + 1e-4
            new = list(team)
            new[rng.randrange(6)] = rng.choice(keys)
            if len({t[0] for t in new}) < 6 or sum(cost[t] for t in new) > budget:
                continue
            s = team_score(new, M, ws)
            if s >= cur or rng.random() < math.exp((s - cur) / T):
                team, cur = new, s
        key = tuple(sorted(team))
        found[key] = cur
    return sorted(found.items(), key=lambda kv: -kv[1])


def to_team(keys, cands, M=None, ws=None):
    """team.json list; lead = member with the best average matchup."""
    mem = list(keys)
    if M is not None:
        mem.sort(key=lambda k: -sum(w * v for w, v in zip(ws, M[k])))
    return [{"species": sp, "moves": list(cands[sp]["sets"][i])} for sp, i in mem]


# ---------------------------------------------------------------- simulation helpers
def make_pool(policy):
    from harness.evaluate import _init
    return Pool(os.cpu_count(), initializer=_init, initargs=(None if policy == "baseline" else policy, True))


OBJECTIVE = "core"   # set from --objective


def sim(pool, team, n, policy):
    """core: equal-weight mean over CORE.
    zip: what the zip's runner would score for a policy entry -- 1/3 the 'policy' (boss) variant that replaces
    public, 2/3 the mean of the non-public CORE stand-ins (proxy for the two hidden variants)."""
    from harness.evaluate import evaluate
    pol = None if policy == "baseline" else policy
    if OBJECTIVE == "core":
        s, _ = evaluate(team, pol, CORE, n, "tune", pool=pool)
        return s
    core_np = [o for o in CORE if o != "public"]
    wide = WIDE_RAND if OBJECTIVE == "robust" else []   # random-move teams: no bias toward the policy guess
    opps = ["policy"] + core_np + wide
    s, _ = evaluate(team, pol, opps, n, "tune", pool=pool)
    po = s["per_opponent"]
    m = lambda xs: sum(po[o]["win_rate"] for o in xs) / len(xs)
    if OBJECTIVE == "robust":   # 1/3 boss variant, 1/3 non-public CORE, 1/3 WIDE tuning teams
        s["mean_win_rate"] = (po["policy"]["win_rate"] + m(core_np) + m(wide)) / 3
    else:
        s["mean_win_rate"] = po["policy"]["win_rate"] / 3 + 2 / 3 * m(core_np)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["screen", "simulate", "local"])
    ap.add_argument("--restarts", type=int, default=40)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--policy", default=str(POLICY))
    ap.add_argument("--start", default=None)
    ap.add_argument("--iters", type=int, default=60)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--tag", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--objective", choices=["core", "zip", "robust"], default="core")
    a = ap.parse_args()
    global OBJECTIVE
    OBJECTIVE = a.objective
    Path("results").mkdir(exist_ok=True)

    if a.cmd == "screen":
        t0 = time.time()
        data, pm = load_all(), load_policy_module()
        pool = opponent_pool()
        cands = candidates(data, pm, pool)
        print(f"{len(cands)} species with >=4 usable moves ({time.time()-t0:.0f}s)", flush=True)
        M, ws = matchup(data, pm, cands, pool)
        print(f"matchup matrix {len(M)} x {len(ws)} ({time.time()-t0:.0f}s)", flush=True)
        best = anneal(cands, M, ws, restarts=a.restarts)
        out = [dict(score=s, team=to_team(k, cands, M, ws), cost=sum(cands[sp]["cost"] for sp, _ in k))
               for k, s in best]
        Path("results/screen.json").write_text(json.dumps(out, indent=1))
        Path("results/candidates.json").write_text(json.dumps({sp: dict(cost=c["cost"], sets=c["sets"])
                                                               for sp, c in cands.items()}))
        for r in out[:10]:
            print(f"{r['score']:.4f} cost {r['cost']} " + " ".join(m["species"] for m in r["team"]))
        print(f"done ({time.time()-t0:.0f}s)")

    elif a.cmd == "simulate":
        screen = json.loads(Path("results/screen.json").read_text())[: a.top]
        stages = [(a.n, len(screen)), (200, 8), (400, 3)]
        teams = [r["team"] for r in screen]
        with make_pool(a.policy) as pool:
            for n, keep in stages:
                res = []
                for t in teams[:keep]:
                    s = sim(pool, t, n, a.policy)
                    res.append((s["mean_win_rate"], s["avg_win_turns"] or 0, t, s))
                    print(f"n={n} {100*s['mean_win_rate']:6.2f} wt={s['avg_win_turns'] or 0:5.2f} "
                          + " ".join(m["species"] for m in t), flush=True)
                res.sort(key=lambda x: (-x[0], x[1]))
                teams = [r[2] for r in res]
                Path(f"results/sim_stage_n{n}{a.tag}.json").write_text(json.dumps(
                    [dict(mean=r[0], wt=r[1], team=r[2], per={o: r[3]["per_opponent"][o]["win_rate"] for o in CORE})
                     for r in res], indent=1))

    elif a.cmd == "local":
        cands = json.loads(Path("results/candidates.json").read_text())
        team = json.loads(Path(a.start).read_text())
        team = team["pokemon"] if isinstance(team, dict) else team
        rng = random.Random(a.seed)
        data = load_all()
        cost = lambda t: sum(data.costs[m["species"]] for m in t)
        strong = [sp for sp, c in cands.items()
                  if data.pokemon[sp].bst >= 450 or c["cost"] <= 3]
        n2 = max(a.n, 200)
        with make_pool(a.policy) as pool:
            bv = sim(pool, team, a.n, a.policy)["mean_win_rate"]          # screening score
            bv2 = sim(pool, team, n2, a.policy)["mean_win_rate"]          # confirmation score
            print(f"start n={a.n}: {100*bv:.2f}  n={n2}: {100*bv2:.2f}  " + " ".join(m["species"] for m in team),
                  flush=True)
            for it in range(a.iters):
                new = [dict(m) for m in team]
                r = rng.random()
                if r < 0.15:  # change lead
                    j = rng.randrange(1, 6)
                    new[0], new[j] = new[j], new[0]
                    what = f"lead {new[0]['species']}"
                elif r < 0.35:  # alternative moveset of a member
                    j = rng.randrange(6)
                    sets = cands.get(new[j]["species"], {}).get("sets", [])
                    alt = [s for s in sets if list(s) != new[j]["moves"]]
                    if not alt:
                        continue
                    new[j]["moves"] = list(rng.choice(alt))
                    what = f"moves {new[j]['species']}"
                else:  # swap a member for another species that fits the budget
                    j = rng.randrange(6)
                    have = {m["species"] for m in new}
                    room = 40 - cost(new) + data.costs[new[j]["species"]]
                    opts = [sp for sp in strong if sp not in have and cands[sp]["cost"] <= room]
                    if not opts:
                        continue
                    sp = rng.choice(opts)
                    new[j] = {"species": sp, "moves": list(cands[sp]["sets"][0])}
                    what = f"swap {team[j]['species']}->{sp}"
                v = sim(pool, new, a.n, a.policy)["mean_win_rate"]
                line = f"it{it:3d} n={a.n} {100*v:6.2f} vs {100*bv:6.2f}  {what}"
                if v > bv - 0.01:   # promising -> confirm on n2 seeds against the current best
                    v2 = sim(pool, new, n2, a.policy)["mean_win_rate"]
                    ok = v2 > bv2
                    line += f"  | n={n2} {100*v2:6.2f} vs {100*bv2:6.2f} {'ACCEPT' if ok else ''}"
                    if ok:
                        team, bv, bv2 = new, v, v2
                        Path(f"results/local_best{a.tag}.json").write_text(json.dumps(team, indent=1))
                print(line, flush=True)
                with open(f"results/local_log{a.tag}.txt", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            print(f"final n={n2} {100*bv2:.2f} " + json.dumps(team))


if __name__ == "__main__":
    main()
