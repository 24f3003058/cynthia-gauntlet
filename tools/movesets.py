"""Heuristic "likely moveset" of a species from public data (cynthia_data/*.csv, supported learnsets only).

likely_moves(sp)            -> best STAB attack per own type, then greedy super-effective coverage (each coverage
                               move needs >= 45% of the species' best move value), up to 4 moves.
ranked_moves(sp)            -> all usable damaging moves, best first: [(value, move, type)]
Used by tools/make_wide.py (invented stand-in teams) and tools/build_policy.py (the policy's guess for
unrevealed moves of species it has no published moveset for).
"""
import csv
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "cynthia_data"


def _rows(name):
    with open(D / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(None)
def tables():
    poke = {r["identifier"]: r for r in _rows("pokemon.csv")}
    moves = {r["identifier"]: r for r in _rows("moves.csv")}
    learn = {}
    for r in _rows("learnsets.csv"):
        learn.setdefault(r["pokemon"], set()).add(r["move"])
    uns = json.loads((ROOT / "config" / "unsupported_moves.json").read_text(encoding="utf-8"))
    uns = set(uns if isinstance(uns, list) else uns.get("moves", []))
    chart = {(r["attacking_type"], r["defending_type"]): float(r["damage_factor"]) / 100.0
             for r in _rows("type_chart.csv")}
    return poke, moves, learn, uns, chart


def types_of(sp):
    poke = tables()[0]
    r = poke[sp]
    return [t for t in (r["type1"], r["type2"]) if t]


def eff_power(r):
    pw = float(r["power"] or 0)
    if int(float(r["max_hits"] or 1)) > 1:
        pw *= 3 if r["min_hits"] != r["max_hits"] else int(float(r["max_hits"]))
    return pw * float(r["accuracy"] or 100) / 100.0


def ranked_moves(sp):
    poke, moves, learn, uns, _ = tables()
    st = types_of(sp)
    phys, spec = float(poke[sp]["attack"]), float(poke[sp]["sp_atk"])
    out = []
    for m in learn.get(sp, ()):
        r = moves.get(m)
        if not r or m in uns or r["needs_special_handling"] not in ("0", "", "False"):
            continue
        if float(r["power"] or 0) <= 0 or r["category"] not in ("physical", "special"):
            continue
        stat = phys if r["category"] == "physical" else spec
        out.append((eff_power(r) * (1.5 if r["type"] in st else 1.0) * stat, m, r["type"]))
    out.sort(reverse=True)
    return out


def likely_moves(sp):
    _, moves, _, _, chart = tables()
    types_all = sorted({a for a, _ in chart})
    st = types_of(sp)
    cand = ranked_moves(sp)
    pick, ptype = [], set()
    for v, m, t in cand:
        if t in st and t not in ptype:
            pick.append(m)
            ptype.add(t)
    se = lambda t: {d for d in types_all if chart.get((t, d), 1) > 1}
    while len(pick) < 4 and cand:
        hit = set().union(*(se(moves[m]["type"]) for m in pick)) if pick else set()
        floor = 0.45 * cand[0][0]
        best = max((c for c in cand if c[1] not in pick and c[2] not in ptype and c[0] >= floor),
                   key=lambda c: (len(se(c[2]) - hit), c[0]), default=None)
        if best is None:
            best = next((c for c in cand if c[1] not in pick), None)
            if best is None:
                break
        pick.append(best[1])
        ptype.add(best[2])
    return pick[:4]
