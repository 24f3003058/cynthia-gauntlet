"""Generate the WIDE stand-in opponent teams (area 1: robustness to hidden variants with different teams).

The note says hidden variants "may use different teams and behaviour". These teams are invented from public data
only (species archetypes picked by hand; moves chosen automatically from each species' supported Gen-4 learnset in
cynthia_data/learnsets.csv: best STAB attacks + greedy super-effective coverage). Nothing from variants_private/.

PYTHONPATH=. python tools/make_wide.py      -> writes harness/wide_teams.json
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "cynthia_data"

# name: (species, AI style, tuning|holdout)
TEAMS = {
    "wd_water":   (["kingdra", "empoleon", "swampert", "vaporeon", "starmie", "ludicolo"], "aggressive", "tune"),
    "wd_dragons": (["salamence", "dragonite", "flygon", "rhyperior", "tyranitar", "gliscor"], "patient", "tune"),
    "wd_special": (["alakazam", "gengar", "porygon-z", "magnezone", "espeon", "jolteon"], "balanced", "tune"),
    "wd_steel":   (["metagross", "scizor", "lucario", "machamp", "heracross", "infernape"], "aggressive", "tune"),
    "wd_legends": (["heatran", "latios", "cresselia", "azelf", "uxie", "raikou"], "patient", "tune"),
    "wd_toxic":   (["roserade", "venusaur", "yanmega", "tangrowth", "crobat", "toxicroak"], "balanced", "tune"),
    "wh_fire":    (["infernape", "arcanine", "magmortar", "electivire", "luxray", "rapidash"], "aggressive", "holdout"),
    "wh_bulky":   (["blissey", "snorlax", "skarmory", "bronzong", "hippowdon", "milotic"], "patient", "holdout"),
    "wh_sinnoh":  (["togekiss", "glaceon", "garchomp", "lucario", "spiritomb", "gastrodon"], "balanced", "holdout"),
    "wh_icerock": (["mamoswine", "weavile", "glaceon", "aerodactyl", "tyranitar", "abomasnow"], "aggressive", "holdout"),
}


def rows(name):
    with open(D / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    poke = {r["identifier"] if "identifier" in r else r[next(iter(r))]: r for r in rows("pokemon.csv")}
    moves = {r["identifier"]: r for r in rows("moves.csv")}
    learn = {}
    for r in rows("learnsets.csv"):
        learn.setdefault(r["pokemon"], set()).add(r["move"])
    unsupported = json.loads((ROOT / "config" / "unsupported_moves.json").read_text(encoding="utf-8"))
    unsupported = set(unsupported if isinstance(unsupported, list) else unsupported.get("moves", []))
    chart = {}
    for r in rows("type_chart.csv"):
        chart[(r["attacking_type"], r["defending_type"])] = float(r["damage_factor"]) / 100.0
    types_all = sorted({a for a, _ in chart})
    tcol = [c for c in next(iter(poke.values())) if "type" in c.lower()]

    def ptypes(sp):
        r = poke[sp]
        return [r[c] for c in tcol if r.get(c)]

    out = {}
    for name, (team, style, split) in TEAMS.items():
        mons = []
        for sp in team:
            assert sp in poke, f"unknown species {sp}"
            st = ptypes(sp)
            phys = float(poke[sp].get("attack") or poke[sp].get("atk") or 0)
            spec = float(poke[sp].get("special_attack") or poke[sp].get("sp_atk") or poke[sp].get("spa") or 0)
            cand = []
            for m in learn.get(sp, ()):
                r = moves.get(m)
                if not r or m in unsupported or r["needs_special_handling"] not in ("0", "", "False"):
                    continue
                pw = float(r["power"] or 0)
                if pw <= 0 or r["category"] not in ("physical", "special"):
                    continue
                if int(float(r["max_hits"] or 1)) > 1:
                    pw *= 3
                acc = float(r["accuracy"] or 100) / 100.0
                stat = phys if r["category"] == "physical" else spec
                v = pw * acc * (1.5 if r["type"] in st else 1.0) * stat
                cand.append((v, m, r["type"]))
            cand.sort(reverse=True)
            pick, ptype = [], set()
            for v, m, t in cand:                       # best attack of each STAB type
                if t in st and t not in ptype:
                    pick.append(m); ptype.add(t)
            while len(pick) < 4 and cand:              # greedy coverage: most new super-effective targets, then value
                hit = {d for m in pick for d in types_all if chart.get((moves[m]["type"], d), 1) > 1}
                floor = 0.45 * cand[0][0]               # coverage moves must be reasonably strong
                best = max((c for c in cand if c[1] not in pick and c[2] not in ptype and c[0] >= floor),
                           key=lambda c: (len({d for d in types_all if chart.get((c[2], d), 1) > 1} - hit), c[0]),
                           default=None)
                if best is None:
                    best = next((c for c in cand if c[1] not in pick), None)
                    if best is None:
                        break
                pick.append(best[1]); ptype.add(best[2])
            mons.append({"species": sp, "moves": pick[:4]})
        out[name] = dict(team=mons, style=style, split=split)
        print(f"{name:11s} {style:10s} {split:7s} " + "  ".join(f"{m['species']}:{'/'.join(m['moves'])}" for m in mons))
    (ROOT / "harness" / "wide_teams.json").write_text(json.dumps(out, indent=1), encoding="utf-8")




def make_random(seed=7):
    """wr_*: same species/styles as the wd_* tuning teams but moves drawn at random from each species' top-8
    damaging moves (>= 1 STAB). Used to judge the policy's moveset guess fairly (the guess uses the same
    heuristic that picked the wd_* moves). Writes harness/wide_rand.json and only the wr_* stand-in files."""
    import random
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from movesets import ranked_moves, types_of
    rng = random.Random(seed)
    out = {}
    for name, (team, style, split) in TEAMS.items():
        if split != "tune":
            continue
        mons = []
        for sp in team:
            top = ranked_moves(sp)[:8]
            st = types_of(sp)
            while True:
                pick = rng.sample(top, min(4, len(top)))
                if any(t in st for _, _, t in pick):
                    break
            mons.append({"species": sp, "moves": [m for _, m, _ in pick]})
        out["wr_" + name[3:]] = dict(team=mons, style=style, split="tune-rand")
    (ROOT / "harness" / "wide_rand.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for n, w in out.items():
        print(n, "  ".join(f"{m['species']}:{'/'.join(m['moves'])}" for m in w["team"]))
    return out


if __name__ == "__main__":
    import sys
    make_random() if sys.argv[1:] == ["random"] else main()
