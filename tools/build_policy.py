"""Build the self-contained policy.py from policy_src/policy_template.py + public game data.

    PYTHONPATH=. python tools/build_policy.py [template] [out]

Why compact + minified: engine/policy.py's sandbox runs the policy as `python -I -c <source>`.
Windows limits a command line to 32,767 chars (Linux: 128 KiB per argument), so the file must
stay well under ~31 KB or every turn falls back to the baseline.

Embeds only public data shipped with the simulator, as packed strings:
  * base stats + types of fully-evolved / legendary species (cynthia_data/pokemon.csv);
    any other species falls back to generic stats inside the policy
  * damaging moves: type, category, power, accuracy, and non-default priority/crit/hits/drain
  * the 17x17 type chart
  * movesets of the published variant files variants/public.json and variants/policy.json
"""
import ast
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES = ["normal", "fire", "water", "grass", "electric", "ice", "fighting", "poison", "ground", "flying",
         "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel"]
TC = "nfwgeiFpGyPbrhdks"          # one letter per type, same order
MAX_BYTES = 31000
# Hard-coded opponent knowledge (fair-play audit; default public since E14): POLICY_KNOWLEDGE=all (public.json + policy.json),
# public (variants/public.json only: the documented practice variant), none (no opponent team/moveset data).
KNOW = {"all": ("public", "policy"), "public": ("public",), "none": ()}[os.environ.get("POLICY_KNOWLEDGE", "public")]
# one char per guessed move: index = type*4 + (special?2:0) + (strong?1:0); 17*4 = 68 symbols
GA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&*+"


def guess_code(sp):
    """4-char likely-moveset code for species sp (tools/movesets.likely_moves), '' if none."""
    sys.path.insert(0, str(ROOT / "tools"))
    from movesets import likely_moves, tables, eff_power
    moves = tables()[1]
    out = ""
    for m in likely_moves(sp):
        r = moves[m]
        k = TYPES.index(r["type"]) * 4 + (2 if r["category"] == "special" else 0) + (1 if eff_power(r) >= 85 else 0)
        out += GA[k]
    return out


def b36(x, w=2):
    s = ""
    for _ in range(w):
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[x % 36] + s
        x //= 36
    return s


def encode():
    rd = lambda f: list(csv.DictReader(open(ROOT / "cynthia_data" / f, encoding="utf-8")))
    code = dict(zip(TYPES, TC))
    sp = []
    for r in rd("pokemon.csv"):
        if not ((r["fully_evolved"] == "1" and int(r["bst"]) >= 400) or r["is_legendary"] == "1"
                or r["is_mythical"] == "1"):
            continue
        t = code[r["type1"]] + (code[r["type2"]] if r["type2"] else "")
        st = "".join(b36(int(r[k])) for k in ("hp", "attack", "defense", "sp_atk", "sp_def", "speed"))
        g = guess_code(r["identifier"])
        sp.append(f"{r['identifier']},{t}{st}" + (f",{g}" if g else ""))
    mv = []
    for r in rd("moves.csv"):
        if r["category"] == "status":
            continue
        pw = int(float(r["power"])) if r["power"] else 0
        acc = b36(int(float(r["accuracy"]))) if r["accuracy"] else "--"
        ex = (int(r["priority"] or 0), int(r["crit_rate"] or 0), int(float(r["min_hits"] or 1)),
              int(float(r["max_hits"] or 1)), int(r["drain"] or 0))
        s = f"{r['identifier']},{code[r['type']]}{r['category'][0]}{b36(pw)}{acc}"
        if ex != (0, 0, 1, 1, 0):
            s += "," + ".".join(map(str, ex))
        mv.append(s)
    ch = {}
    for r in rd("type_chart.csv"):
        ch[(r["attacking_type"], r["defending_type"])] = {0: "0", 50: "h", 100: "1", 200: "2"}[int(float(r["damage_factor"]))]
    chart = "".join(ch.get((a, d), "1") for a in TYPES for d in TYPES)
    prior = {}
    for v in KNOW:
        for m in json.loads((ROOT / "variants" / f"{v}.json").read_text(encoding="utf-8"))["team"]:
            prior.setdefault(m["species"], m["moves"])
    pub = [[m["species"] for m in json.loads((ROOT / "variants" / f"{v}.json").read_text(encoding="utf-8"))["team"]]
           for v in KNOW]   # the published teams (public files in the zip)
    return ";".join(sp), ";".join(mv), chart, prior, pub


def minify(src):
    """Drop docstrings/comments via an AST round-trip (behaviour-preserving)."""
    t = ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            n.body = n.body[1:] or [ast.Pass()]
    code = ast.unparse(t)
    # ast.unparse indents with 4 spaces and (docstrings removed) leaves no multi-line strings,
    # so 4 leading spaces -> 1 space per level is behaviour-preserving.
    lines = []
    for ln in code.split("\n"):
        n = len(ln) - len(ln.lstrip(" "))
        lines.append(" " * (n // 4) + ln[n:])
    out = "\n".join(lines) + "\n"
    assert ast.dump(ast.parse(out)) == ast.dump(ast.parse(code)), "re-indent changed the program"
    return out


def build(template=ROOT / "policy_src" / "policy_template.py", out=ROOT / "policy_build" / "policy.py",
          header="# Cynthia's Gauntlet policy (built by tools/build_policy.py from policy_src/; see README.md)\n"):
    sp, mv, chart, prior, pub = encode()
    data = (f"_SP = {sp!r}\n_MV = {mv!r}\n_CH = {chart!r}\n_TC = {TC!r}\n_TYPES = {TYPES!r}\n_PRIOR = {prior!r}\n"
            f"_TEAMS = {pub!r}\n_GA = {GA!r}\n")
    src = Path(template).read_text(encoding="utf-8").replace("# @@DATA@@\n", data)
    out_src = header + minify(src)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(out_src, encoding="utf-8", newline="\n")
    n = len(out_src.encode("utf-8"))
    if n > MAX_BYTES:
        raise SystemExit(f"policy too large for the Windows sandbox: {n} bytes > {MAX_BYTES}")
    return out, n


if __name__ == "__main__":
    a = sys.argv[1:]
    print("wrote %s (%d bytes)" % (build(*(Path(x) for x in a)) if a else build()))
