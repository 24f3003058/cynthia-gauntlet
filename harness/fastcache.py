"""Memoisation for the engine's pure damage-estimate helpers (speed only, same results).

The baseline policy and Cynthia spend ~80% of runtime in ai_core.expected_damage /
calculate_damage, which are pure functions of (species, move, stages, burn, crit, roll).
install() wraps them with dict caches inside the *current process only*.
No engine file is modified. tools/verify_fastcache.py checks bit-identical battle logs.
"""
from __future__ import annotations

import engine.ai_core as ai_core
import engine.ai_search as ai_search
from engine.data import Move, Pokemon

_orig_expected = ai_core.expected_damage
_orig_calc = ai_core.calculate_damage
_E: dict = {}
_C: dict = {}
_installed = False


def _species_key(p):
    if isinstance(p, Pokemon):
        return p.identifier
    if isinstance(p, dict):
        s = p.get("species") or p.get("identifier") or p.get("pokemon") or ""
        return s.strip().lower()
    if isinstance(p, str):
        return p.strip().lower()
    return None


def _move_key(m):
    if isinstance(m, Move):
        return m.identifier
    if isinstance(m, str):
        return ("s", m)
    if isinstance(m, dict):
        return ("d", m.get("identifier"), m.get("name"), m.get("type"), m.get("category"), m.get("power"),
                m.get("accuracy"), m.get("priority"), m.get("drain"), m.get("pp"), m.get("crit_rate"))
    if isinstance(m, ai_core.DummyMove):
        return ("D", m.identifier, m.type, m.category, m.power, m.accuracy, m.priority, m.drain, m.crit_rate,
                m.min_hits, m.max_hits)
    return None


def _stages_key(s):
    return tuple(sorted(s.items())) if s else ()


def expected_damage(attacker, move, defender, data=None, config=None, attacker_stages=None,
                    defender_stages=None, attacker_burned=False, attacker_crit_stage=0, level=50):
    a, d, m = _species_key(attacker), _species_key(defender), _move_key(move)
    if a is None or d is None or m is None or config is not None and config is not ai_core.get_mechanics():
        return _orig_expected(attacker, move, defender, data, config, attacker_stages, defender_stages,
                              attacker_burned, attacker_crit_stage, level)
    k = (a, m, d, _stages_key(attacker_stages), _stages_key(defender_stages), bool(attacker_burned),
         attacker_crit_stage, level)
    v = _E.get(k)
    if v is None:
        v = _orig_expected(attacker, move, defender, data, config, attacker_stages, defender_stages,
                           attacker_burned, attacker_crit_stage, level)
        _E[k] = v
    return v


def calculate_damage(attacker, defender, move, type_chart, attacker_stages=None, defender_stages=None,
                     attacker_burned=False, is_crit=False, roll=100, level=50, config=None):
    m = _move_key(move)
    if not (isinstance(attacker, Pokemon) and isinstance(defender, Pokemon)) or m is None \
            or config is not None and config is not ai_core.get_mechanics():
        return _orig_calc(attacker, defender, move, type_chart, attacker_stages, defender_stages,
                          attacker_burned, is_crit, roll, level, config)
    k = (attacker.identifier, defender.identifier, m, _stages_key(attacker_stages), _stages_key(defender_stages),
         bool(attacker_burned), is_crit, roll, level)
    v = _C.get(k)
    if v is None:
        v = _orig_calc(attacker, defender, move, type_chart, attacker_stages, defender_stages,
                       attacker_burned, is_crit, roll, level, config)
        _C[k] = v
    return v


def _jcopy(x, _memo=None):
    """deepcopy for the JSON-like observation dicts that ai_search copies (dict/list/primitives)."""
    t = type(x)
    if t is dict:
        return {k: _jcopy(v) for k, v in x.items()}
    if t is list:
        return [_jcopy(v) for v in x]
    if t in (str, int, float, bool) or x is None:
        return x
    import copy as _copy
    return _copy.deepcopy(x)


class _CopyShim:
    deepcopy = staticmethod(_jcopy)


def install() -> None:
    global _installed
    if _installed:
        return
    ai_search.copy = _CopyShim                     # ai_search only uses copy.deepcopy on observation dicts
    ai_core.expected_damage = expected_damage      # used by compute_matchup / score_legal_move / turns_to_ko
    ai_search.expected_damage = expected_damage    # imported by name into ai_search
    ai_core.calculate_damage = calculate_damage    # used by can_ko and expected_damage's inner loop
    _installed = True
