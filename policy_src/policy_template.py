"""Cynthia's Gauntlet battle policy.

Exact Gen-4 damage model (same integer steps as engine/damage.py) + duel evaluator.
In this simulator every legal move is a pure damage move (status, stat stages, flinch and healing
are never applied by engine/battle.py), so a battle is a damage race decided by HP, speed,
priority, accuracy, crits and switching. For every option (each move, each switch, each forced
replacement) we estimate the expected change in "material" (alive Pokemon + HP fraction) over the
resulting 1v1 duel, using turns-to-KO distributions built from the full damage-roll distribution.

Uses only `state` plus embedded public game data. No imports, no I/O.
"""

# @@DATA@@


def _decode():
    tmap = dict(zip(_TC, _TYPES))
    species, guess = {}, {}
    for rec in _SP.split(";"):
        name, rest, *g = rec.split(",")
        if g:   # likely moveset: one char per move = type*4 + special*2 + strong
            guess[name] = [(_TYPES[k // 4], "special" if k & 2 else "physical", 100 if k & 1 else 75)
                           for k in (_GA.index(c) for c in g[0])]
        nt = len(rest) - 12  # 1 or 2 type letters, then 6 stats x 2 base-36 chars
        ts = [tmap[c] for c in rest[:nt]]
        st = [int(rest[nt + 2 * i:nt + 2 * i + 2], 36) for i in range(6)]
        species[name] = (ts[0], ts[1] if nt == 2 else None, st[0], st[1], st[2], st[3], st[4], st[5])
    moves = {}
    for rec in _MV.split(";"):
        parts = rec.split(",")
        name, body = parts[0], parts[1]
        ex = [int(x) for x in parts[2].split(".")] if len(parts) > 2 else [0, 0, 1, 1, 0]
        acc = None if body[4:6] == "--" else int(body[4:6], 36)
        cat = "physical" if body[1] == "p" else "special"
        moves[name] = (tmap[body[0]], cat, int(body[2:4], 36), acc, ex[0], ex[1], ex[2], ex[3], ex[4], 0)
    chart = {}
    n = len(_TYPES)
    for i, a in enumerate(_TYPES):
        for j, d in enumerate(_TYPES):
            c = _CH[i * n + j]
            if c != "1":
                chart[(a, d)] = {"0": 0.0, "h": 0.5, "2": 2.0}[c]
    return species, moves, chart, guess


_SPECIES, _MOVES, _CHART, _GUESS = _decode()

P = {
    "alpha": 2.0,           # value of a Pokemon being alive, in units of one full HP bar
    "switch_margin": 0.0,   # a voluntary switch must beat the best attack by this much
    "K": 8,                 # turns modelled per duel
    "unknown_power": 90,    # power assumed for an unrevealed STAB move
    "use_prior": True,      # use the published public-variant movesets until contradicted
    "voluntary_switch": True,
    "buckets": 6,
    "guess_cov": 0.85,      # power scale for guessed non-STAB (coverage) moves
    "guess": True,          # fill unrevealed foe moves from a likely moveset (types/power from public learnsets)
    "beta": 0.5,            # weight of a Pokemon's usefulness vs the expected remaining foes           # damage-distribution buckets used for the first-turn evaluation
}
DEBUG_RAISE = False         # harness sets True so internal errors are counted, not hidden

_FIXED = {"sonic-boom": 20, "dragon-rage": 40, "seismic-toss": 50, "night-shade": 50}
_OHKO = {"guillotine", "horn-drill", "fissure", "sheer-cold"}
_HITS = ((2, 0.375), (3, 0.375), (4, 0.125), (5, 0.125))
_CRIT = (0.0625, 0.125, 0.25, 1.0 / 3.0, 0.5)
_C = {}                     # caches (persist across turns/battles in one process)


# ------------------------------------------------------------------ data helpers
def _stat(b, hp=False):
    v = (2 * b + 31) * 50 // 100
    return v + 60 if hp else v + 5


def _opp_info(sp):
    k = ("opp", sp)
    if k not in _C:
        s = _SPECIES.get(sp)
        if s is None:
            s = ("normal", None, 80, 80, 80, 80, 80, 80)
        t1, t2, hp, a, d, sa, sd, spe = s
        _C[k] = {"types": tuple(t for t in (t1, t2) if t), "hp": _stat(hp, True), "atk": _stat(a),
                 "def": _stat(d), "spa": _stat(sa), "spd": _stat(sd), "spe": _stat(spe)}
    return _C[k]


def _eff(mt, types):
    m = 1.0
    for t in types:
        m *= _CHART.get((mt, t), 1.0)
    return m


def _mv(mid):
    return _MOVES.get(mid)


# ------------------------------------------------------------------ damage model
def _hit(A, D, mv, crit, roll):
    """One hit, mirrors engine/damage.calculate_damage (no stages/burn: never set by the engine)."""
    mtype, cat, power = mv[0], mv[1], mv[2]
    eff = _eff(mtype, D["types"])
    if eff <= 0 or power <= 0:
        return 0
    if cat == "physical":
        a, d = A["atk"], D["def"]
    else:
        a, d = A["spa"], D["spd"]
    x = (22 * power * a // max(1, d)) // 50 + 2
    if crit:
        x *= 2
    x = x * roll // 100
    if mtype in A["types"]:
        x = x * 3 // 2
    return int(x * eff)


def _single(A, D, mid, mv):
    """Distribution {damage: prob} of one use of a move (accuracy, crit, rolls, multi-hit)."""
    key = ("s", A["key"], D["key"], mid)
    r = _C.get(key)
    if r is not None:
        return r
    acc = 1.0 if mv[3] is None else mv[3] / 100.0
    dist = {}
    if mid in _OHKO:
        acc = 0.3 if _eff(mv[0], D["types"]) > 0 else 0.0
        dist[D["hp"]] = acc
    elif mid in _FIXED:
        dmg = _FIXED[mid] if _eff(mv[0], D["types"]) > 0 else 0
        dist[dmg] = acc
    else:
        pc = _CRIT[min(4, mv[5])]
        one = {}
        for roll in range(85, 101):
            v = _hit(A, D, mv, False, roll)
            one[v] = one.get(v, 0.0) + (1 - pc) / 16.0
            v = _hit(A, D, mv, True, roll)
            one[v] = one.get(v, 0.0) + pc / 16.0
        mn, mx = mv[6], mv[7]
        if mx <= 1:
            hits = ((1, 1.0),)
        elif mn == mx:
            hits = ((mn, 1.0),)
        else:
            hits = _HITS
        cap = D["hp"]
        cur, n0 = {0: 1.0}, 0
        for n, pn in hits:
            while n0 < n:
                cur = _conv(cur, one, cap)
                n0 += 1
            for v, p in cur.items():
                dist[v] = dist.get(v, 0.0) + p * pn * acc
    if acc < 1.0:
        dist[0] = dist.get(0, 0.0) + (1.0 - acc)
    r = {}
    for v, p in dist.items():
        v = min(v, D["hp"])
        r[v] = r.get(v, 0.0) + p
    _C[key] = r
    return r


def _conv(a, b, cap):
    out = {}
    for x, p in a.items():
        for y, q in b.items():
            v = x + y
            if v > cap:
                v = cap
            out[v] = out.get(v, 0.0) + p * q
    return out


def _mean(dist):
    k = ("m", id(dist))
    r = _C.get(k)
    if r is None:
        r = _C[k] = sum(v * p for v, p in dist.items())
    return r


def _compress(dist, thr, nb):
    """Merge a damage distribution into <= nb buckets (+1 for 'reaches thr', kept exact).
    Representative value = probability-weighted mean (floored), so KO/no-KO splits are preserved."""
    k = ("c", id(dist), thr, nb)
    r = _C.get(k)
    if r is not None:
        return r
    ko = sum(p for v, p in dist.items() if v >= thr)
    rest = sorted((v, p) for v, p in dist.items() if v < thr and p > 0)
    tot = sum(p for _, p in rest)
    out = {}
    if rest:
        step, acc, bucket = tot / nb, 0.0, []
        for v, p in rest:
            bucket.append((v, p))
            acc += p
            if acc >= step * 0.999:
                bp = sum(q for _, q in bucket)
                bv = int(sum(x * q for x, q in bucket) / bp)
                out[bv] = out.get(bv, 0.0) + bp
                bucket, acc = [], 0.0
        if bucket:
            bp = sum(q for _, q in bucket)
            bv = int(sum(x * q for x, q in bucket) / bp)
            out[bv] = out.get(bv, 0.0) + bp
    if ko > 0:
        out[thr] = out.get(thr, 0.0) + ko
    _C[k] = out
    return out


def _tails(A, D, mid, mv):
    """tails[k][h] = P(damage after k+1 uses >= h), h in 0..maxHP."""
    key = ("t", A["key"], D["key"], mid, P["K"])
    r = _C.get(key)
    if r is not None:
        return r
    one = _single(A, D, mid, mv)
    cap = D["hp"]
    r, cur = [], {0: 1.0}
    for _ in range(P["K"]):
        cur = _conv(cur, one, cap)
        arr = [0.0] * (cap + 2)
        for v, p in cur.items():
            arr[v] += p
        acc = 0.0
        for h in range(cap, -1, -1):
            acc += arr[h]
            arr[h] = acc
        r.append(arr)
    _C[key] = r
    return r


# ------------------------------------------------------------------ duel
def _duel(hA, maxA, tA, mA, hO, maxO, tO, mO, a_first, vA=None):
    """(delta material, P(A wins)) if A (hp hA, tails tA vs O, mean dmg mA) duels O to the end.
    a_first: probability A acts first each turn. vA: value of A being alive (default alpha)."""
    al = P["alpha"]
    if vA is None:
        vA = al
    key = ("du", id(tA), id(tO), hA, hO, a_first, vA)
    r = _C.get(key)
    if r is not None:
        return r
    K = P["K"]
    PA = [0.0] + [tA[k][hO] for k in range(K)]
    PO = [0.0] + [tO[k][hA] for k in range(K)]
    total = pwin = 0.0
    for first, w in ((True, a_first), (False, 1.0 - a_first)):
        if w <= 0:
            continue
        pw = hw = pl = hl = 0.0
        for k in range(1, K + 1):
            pa = PA[k] - PA[k - 1]
            if pa > 0:
                s = 1.0 - (PO[k - 1] if first else PO[k])
                pw += pa * s
                hw += pa * s * ((k - 1) if first else k)
            po = PO[k] - PO[k - 1]
            if po > 0:
                s = 1.0 - (PA[k] if first else PA[k - 1])
                pl += po * s
                hl += po * s * (k if first else (k - 1))
        v = 0.0
        if pw > 0:
            lostA = min(hA - 1, mA * hw / pw) if hA > 1 else 0
            v += pw * (al + hO / maxO - lostA / maxA)
        if pl > 0:
            lostO = min(hO - 1, mO * hl / pl) if hO > 1 else 0
            v += pl * (-(vA + hA / maxA) + lostO / maxO)
        total += w * v
        pwin += w * pw
    r = _C[key] = (total, pwin)
    return r


def _val(A):
    """Value of our Pokemon A being alive: alpha + beta * usefulness vs expected remaining foes."""
    return P["alpha"] + P["beta"] * _USE.get(A["key"], 0.0)


_USE = {}


# ------------------------------------------------------------------ opponent model
def _opp_moves(opp, info):
    sp = opp.get("species", "")
    known = [m for m in (opp.get("known_moves") or []) if m in _MOVES]
    prior = _PRIOR.get(sp)
    if P["use_prior"] and prior and all(k in prior for k in known):
        ms = [(m, _MOVES[m]) for m in prior if m in _MOVES]
        if ms:
            return ms
    ms = [(m, _MOVES[m]) for m in known]
    if P["guess"]:   # likely moveset (public learnset heuristic) for types not yet revealed
        for t, c, pw in _GUESS.get(sp, ()):
            if len(ms) < 4 and t not in {mv[0] for _, mv in ms}:
                if t not in info["types"]:   # coverage is less certain than STAB
                    pw = int(pw * P["guess_cov"])
                ms.append(("~" + t + c[0], (t, c, pw, 100, 0, 0, 1, 1, 0, 10)))
    if len(ms) < 4:
        cat = "physical" if info["atk"] >= info["spa"] else "special"
        have = {mv[0] for _, mv in ms if mv[0] in info["types"]}
        for t in info["types"]:
            if t not in have:
                ms.append(("~" + t, (t, cat, P["unknown_power"], 100, 0, 0, 1, 1, 0, 10)))
    return ms


def _exp_dmg(A, D, mid, mv):
    return _mean(_single(A, D, mid, mv))


def _predict(O, ms, X, x_hp, x_known, o_hp):
    """Replicates engine.ai_core.score_legal_move (Cynthia's move choice), aggression 1."""
    if not ms:
        return None
    faster = O["spe"] > X["spe"]
    slower = O["spe"] < X["spe"]
    danger = o_hp <= O["hp"] * 0.25
    if not danger:
        for mid in x_known:
            mv = _mv(mid)
            if mv and _min_dmg(X, O, mid, mv) >= o_hp:
                danger = True
                break
    best, bs = None, -1e9
    for mid, mv in ms:
        acc = 1.0 if mv[3] is None else mv[3] / 100.0
        prio = mv[4]
        E = _exp_dmg(O, X, mid, mv)
        if _min_dmg(O, X, mid, mv) >= x_hp:
            s = 2.0 + acc
            if prio > 0 or faster:
                s += 0.5
            if slower and danger and prio > 0:
                s += 2.0
            if mv[8] < 0:
                s -= 0.30
        elif E >= x_hp:
            s = 1.2 + 0.6 * acc
            if prio > 0 and slower and danger:
                s += 1.5
        else:
            s = min(E, x_hp) / x_hp * acc
            if prio > 0:
                s += 0.5 if (slower and danger) else 0.05
        if s > bs:
            best, bs = (mid, mv), s
    return best


def _min_dmg(A, D, mid, mv):
    if mid in _FIXED:
        return _FIXED[mid] if _eff(mv[0], D["types"]) > 0 else 0
    if mid in _OHKO:
        return 0
    return _hit(A, D, mv, False, 85) * max(1, mv[6])


# ------------------------------------------------------------------ evaluation
def _mon(d):
    st = d.get("stats") or {}
    t = tuple(d.get("types") or ())
    return {"types": t, "hp": d.get("max_hp") or st.get("hp", 100), "atk": st.get("atk", 100),
            "def": st.get("def", 100), "spa": st.get("spa", 100), "spd": st.get("spd", 100),
            "spe": st.get("spe", 100), "key": ("me", d.get("species"))}


def _order(pa, sa, po, so):
    if pa != po:
        return 1.0 if pa > po else 0.0
    if sa != so:
        return 1.0 if sa > so else 0.0
    return 0.5


def _sustained(A, D, moves, hD):
    k = ("su", A["key"], D["key"], hD, tuple(m for m, _ in moves))
    r = _C.get(k, 0)
    if r == 0:
        r = _C[k] = _sustained_raw(A, D, moves, hD)
    return r


def _sustained_raw(A, D, moves, hD):
    best, bm = None, -1.0
    for mid, mv in moves:
        m = sum(min(v, hD) * p for v, p in _single(A, D, mid, mv).items())
        if m > bm:
            best, bm = (mid, mv), m
    return best


def _duel_from(A, a_moves, hA, O, o_moves, hO, X_known):
    """Free duel A vs O from (hA, hO): A uses its best sustained move, O its predicted move."""
    key = ("df", A["key"], hA, O["key"], hO, X_known, tuple(m for m, _ in a_moves), tuple(m for m, _ in o_moves),
           _val(A))
    r = _C.get(key)
    if r is None:
        r = _C[key] = _duel_from_raw(A, a_moves, hA, O, o_moves, hO, X_known)[0]
    return r


def _duel_from_raw(A, a_moves, hA, O, o_moves, hO, X_known):
    sa = _sustained(A, O, a_moves, hO)
    po = _predict(O, o_moves, A, hA, X_known, hO)
    if sa is None or po is None:
        return (0.0, 0.5)
    tA, tO = _tails(A, O, sa[0], sa[1]), _tails(O, A, po[0], po[1])
    mO = _mean(_single(O, A, po[0], po[1]))
    mA = _mean(_single(A, O, sa[0], sa[1]))
    af = _order(sa[1][4], A["spe"], po[1][4], O["spe"])
    return _duel(hA, A["hp"], tA, mA, hO, O["hp"], tO, mO, af, _val(A))


def _eval_attack(A, a_moves, hA, mid, mv, O, o_moves, hO, pred, X_known):
    al, vA = P["alpha"], _val(A)
    dA = _compress(_single(A, O, mid, mv), hO, P["buckets"])
    dO = _compress(_single(O, A, pred[0], pred[1]), hA, P["buckets"])
    af = _order(mv[4], A["spe"], pred[1][4], O["spe"])
    total = 0.0
    for first, w in ((True, af), (False, 1.0 - af)):
        if w <= 0:
            continue
        for d, pd in dA.items():
            for e, pe in dO.items():
                pr = pd * pe * w
                if pr <= 0:
                    continue
                if first:
                    if d >= hO:
                        v = al + hO / O["hp"]
                    elif e >= hA:
                        v = -(vA + hA / A["hp"]) + d / O["hp"]
                    else:
                        v = d / O["hp"] - e / A["hp"] + _duel_from(A, a_moves, hA - e, O, o_moves, hO - d, X_known)
                else:
                    if e >= hA:
                        v = -(vA + hA / A["hp"])
                    elif d >= hO:
                        v = al + hO / O["hp"] - e / A["hp"]
                    else:
                        v = d / O["hp"] - e / A["hp"] + _duel_from(A, a_moves, hA - e, O, o_moves, hO - d, X_known)
                total += pr * v
    return total


def _eval_switch_in(B, b_moves, hB, O, o_moves, hO, incoming):
    """B switches in and (if incoming is given) eats that move first, then duels O."""
    vB = _val(B)
    if incoming is None:
        return _duel_from(B, b_moves, hB, O, o_moves, hO, ())
    total = 0.0
    for e, pe in _compress(_single(O, B, incoming[0], incoming[1]), hB, P["buckets"]).items():
        if e >= hB:
            total += pe * -(vB + hB / B["hp"])
        else:
            total += pe * (-e / B["hp"] + _duel_from(B, b_moves, hB - e, O, o_moves, hO, ()))
    return total


def _foe(sp):
    k = ("foe", sp)
    r = _C.get(k)
    if r is None:
        r = dict(_opp_info(sp))
        r["key"] = ("opp", sp)
        _C[k] = r
    return r


def _update_use(state, cur, my_mons):
    """_USE[our key] = mean P(win 1v1 at current HP) vs the foes we still expect to face
    (seen & alive & not active, plus unrevealed public-team members if everything seen so far
    belongs to the public team)."""
    _USE.clear()
    if P["beta"] == 0:
        return
    seen, fainted, known = [], set(), {}
    for ev in state.get("battle_history") or ():
        if ev.get("side") != "b" or not ev.get("pokemon"):
            continue
        sp = ev["pokemon"]
        if sp not in seen:
            seen.append(sp)
        t = ev.get("type")
        if t == "faint":
            fainted.add(sp)
        elif t == "move_used":
            known.setdefault(sp, set()).add(ev.get("move"))
    if cur not in seen:
        seen.append(cur)
    left = max(0, (state.get("opponent_remaining_count") or 1) - 1)
    R = [x for x in seen if x not in fainted and x != cur]
    fits = [t for t in _TEAMS if all(x in t for x in seen)]
    if fits:   # unrevealed members common to every published team consistent with what we have seen
        R += [x for x in fits[0] if x not in seen and all(x in t for t in fits)]
    R = R[:left]
    if not R:
        return
    for X, xm, hX in my_mons:
        tot = 0.0
        for r in R:
            F = _foe(r)
            fm = _opp_moves({"species": r, "known_moves": sorted(known.get(r, ()))}, F)
            tot += _duel_from_raw(X, xm, hX, F, fm, F["hp"], ())[1]
        _USE[X["key"]] = tot / len(R)


def _my_moves(d):
    out = []
    for m in d.get("moves") or []:
        mid = m.get("identifier")
        mv = _MOVES.get(mid)
        if mv is not None and (m.get("pp") or 0) > 0:
            out.append((mid, mv))
    return out


def _known_mine(state, species):
    ks = set()
    for ev in state.get("battle_history") or ():
        if ev.get("type") == "move_used" and ev.get("side") == "a" and ev.get("pokemon") == species:
            ks.add(ev.get("move"))
    return tuple(sorted(ks))


def _choose(state):
    legal = state.get("legal_actions") or []
    if not legal:
        return {"action": "struggle"}
    moves_legal = [a for a in legal if a.get("action") == "move"]
    switches = [a for a in legal if a.get("action") == "switch"]
    if any(a.get("action") == "struggle" for a in legal):
        return {"action": "struggle"}

    opp = state.get("opponent_active") or {}
    O = _foe(opp.get("species", ""))
    hO = max(1, int(round(O["hp"] * (opp.get("hp_percent", 100.0)) / 100.0)))
    o_moves = _opp_moves(opp, O)
    bench = {b.get("index"): b for b in state.get("bench") or []}
    mine = [(_mon(b), _my_moves(b), b.get("current_hp", 1)) for b in bench.values() if not b.get("fainted")]
    act0 = state.get("active_pokemon") or {}
    if act0 and (act0.get("current_hp") or 0) > 0:
        mine.append((_mon(act0), _my_moves(act0), act0.get("current_hp", 1)))
    _update_use(state, opp.get("species", ""), mine)

    if not moves_legal:  # forced replacement: free switch-in
        best, bv = switches[0], -1e9
        for a in switches:
            b = bench.get(a.get("index"))
            if not b:
                continue
            B = _mon(b)
            v = _eval_switch_in(B, _my_moves(b), b.get("current_hp", 1), O, o_moves, hO, None)
            if v > bv:
                best, bv = a, v
        return best

    act = state.get("active_pokemon") or {}
    A = _mon(act)
    hA = act.get("current_hp", 1)
    a_moves_all = _my_moves(act)
    known = _known_mine(state, act.get("species"))
    pred = _predict(O, o_moves, A, hA, known, hO)
    if pred is None:
        return moves_legal[0]
    idx = {m.get("identifier"): i for i, m in enumerate(act.get("moves") or [])}

    best, bv = moves_legal[0], -1e9
    for a in moves_legal:
        m = (act.get("moves") or [])[a["index"]]
        mid = m.get("identifier")
        mv = _MOVES.get(mid)
        if mv is None:
            continue
        v = _eval_attack(A, a_moves_all, hA, mid, mv, O, o_moves, hO, pred, known)
        if v > bv:
            best, bv = a, v

    if P["voluntary_switch"] and switches:
        for a in switches:
            b = bench.get(a.get("index"))
            if not b:
                continue
            B = _mon(b)
            v = _eval_switch_in(B, _my_moves(b), b.get("current_hp", 1), O, o_moves, hO, pred)
            # keep A's material: the attack option risks A, the switch option does not
            v -= P["switch_margin"]
            if v > bv:
                best, bv = a, v
    return best


def choose_move(state):
    try:
        return _choose(state)
    except Exception:
        if DEBUG_RAISE:
            raise
        legal = state.get("legal_actions") or []
        for a in legal:
            if a.get("action") in ("move", "struggle"):
                return a
        return legal[0] if legal else {"action": "struggle"}
