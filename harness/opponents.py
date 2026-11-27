"""Opponent registry: shipped public variants + stand-ins for the two hidden variants.

Hidden-variant files (variants_private/) are deliberately NOT used. Stand-ins are built only
from public information:
  * SIMULATOR_SPEC.md §9 describes the hidden variants as `aggressive` ("never switches,
    favours big hits") and `patient` ("switches readily, favours status"), and says they may
    use a different team.
  * engine/ai_config.py documents the styles `aggressive` and `patient`.
Assumptions per stand-in are stated in STANDINS[...]["why"].
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDIN_DIR = Path(__file__).resolve().parent / "standins"

PUBLIC_TEAM = json.loads((ROOT / "variants" / "public.json").read_text(encoding="utf-8"))["team"]
_BASE = {k: v for k, v in json.loads((ROOT / "variants" / "public.json").read_text(encoding="utf-8")).items()
         if k not in ("variant", "team")}

ALT_MOVES_TEAM = [
    {"species": "spiritomb", "moves": ["shadow-ball", "dark-pulse", "psychic", "ominous-wind"]},
    {"species": "roserade", "moves": ["energy-ball", "sludge-bomb", "shadow-ball", "extrasensory"]},
    {"species": "gastrodon", "moves": ["earth-power", "surf", "ice-beam", "sludge-bomb"]},
    {"species": "lucario", "moves": ["aura-sphere", "shadow-ball", "flash-cannon", "extreme-speed"]},
    {"species": "milotic", "moves": ["surf", "ice-beam", "dragon-pulse", "aqua-tail"]},
    {"species": "garchomp", "moves": ["earthquake", "dragon-claw", "fire-fang", "crunch"]},
]
ALT_TEAM_A = [  # Cynthia-flavoured but different species (her Platinum/HGSS rematch pool)
    {"species": "togekiss", "moves": ["air-slash", "aura-sphere", "flamethrower", "shadow-ball"]},
    {"species": "spiritomb", "moves": ["dark-pulse", "shadow-ball", "silver-wind", "psychic"]},
    {"species": "glaceon", "moves": ["ice-beam", "shadow-ball", "water-pulse", "signal-beam"]},
    {"species": "lucario", "moves": ["aura-sphere", "dragon-pulse", "flash-cannon", "extreme-speed"]},
    {"species": "milotic", "moves": ["hydro-pump", "surf", "ice-beam", "dragon-pulse"]},
    {"species": "garchomp", "moves": ["earthquake", "dragon-claw", "stone-edge", "brick-break"]},
]
ALT_TEAM_B = [  # generic strong Gen 4 team, very different type profile
    {"species": "tyranitar", "moves": ["stone-edge", "crunch", "earthquake", "ice-punch"]},
    {"species": "salamence", "moves": ["dragon-claw", "earthquake", "flamethrower", "aerial-ace"]},
    {"species": "metagross", "moves": ["meteor-mash", "earthquake", "zen-headbutt", "bullet-punch"]},
    {"species": "starmie", "moves": ["surf", "thunderbolt", "ice-beam", "psychic"]},
    {"species": "infernape", "moves": ["flamethrower", "mach-punch", "brick-break", "thunder-punch"]},
    {"species": "gengar", "moves": ["shadow-ball", "thunderbolt", "focus-blast", "sludge-bomb"]},
]
GIRATINA_TEAM = json.loads((ROOT / "variants" / "policy.json").read_text(encoding="utf-8"))["team"]

STANDINS = {
    "si_aggressive": dict(team=PUBLIC_TEAM, style="aggressive", aggression=1.8, priority_weight=1.3,
                          why="spec §9 'aggressive': never switches, favours big hits; public team"),
    "si_patient": dict(team=PUBLIC_TEAM, style="patient", switch_cooldown=1, danger_threshold=0.45,
                       weak_offense_threshold=0.6, aggression=0.7, status_weight=1.8,
                       why="spec §9 'patient': switches readily; public team"),
    "si_altmoves": dict(team=ALT_MOVES_TEAM, why="same species, different coverage moves"),
    "si_altteam_a": dict(team=ALT_TEAM_A, style="patient", switch_cooldown=2, danger_threshold=0.5,
                         why="different team (Togekiss/Glaceon in), switch-happy"),
    "si_altteam_b": dict(team=ALT_TEAM_B, style="aggressive", aggression=1.5,
                         why="completely different strong team, never switches"),
    "si_giratina": dict(team=GIRATINA_TEAM,
                        why="public AI with the shipped Giratina team but WITHOUT boss-mode damage edge"),
}

# Held-out opponents: used ONLY for final testing (Phase 5), never for tuning.
HOLDOUT_TEAM_C = [
    {"species": "rhyperior", "moves": ["earthquake", "stone-edge", "megahorn", "ice-punch"]},
    {"species": "gallade", "moves": ["psycho-cut", "leaf-blade", "night-slash", "brick-break"]},
    {"species": "porygon-z", "moves": ["tri-attack", "thunderbolt", "ice-beam", "dark-pulse"]},
    {"species": "scizor", "moves": ["x-scissor", "bullet-punch", "night-slash", "aerial-ace"]},
    {"species": "lapras", "moves": ["surf", "ice-beam", "thunderbolt", "psychic"]},
    {"species": "heracross", "moves": ["megahorn", "brick-break", "stone-edge", "night-slash"]},
]
HOLDOUT_MIXED = PUBLIC_TEAM[:3] + [
    {"species": "magnezone", "moves": ["thunderbolt", "flash-cannon", "discharge", "signal-beam"]},
    {"species": "garchomp", "moves": ["earthquake", "dragon-claw", "stone-edge", "brick-break"]},
    {"species": "togekiss", "moves": ["air-slash", "aura-sphere", "flamethrower", "shadow-ball"]},
]
HOLDOUTS = {
    "ho_team_c": dict(team=HOLDOUT_TEAM_C, style="balanced", why="held-out: unseen team, default AI"),
    "ho_params": dict(team=PUBLIC_TEAM, style="speed", aggression=1.2, danger_threshold=0.7, switch_cooldown=4,
                      priority_weight=1.6, weak_offense_threshold=0.3, why="held-out: public team, unseen params"),
    "ho_mixed": dict(team=HOLDOUT_MIXED, style="patient", switch_cooldown=2, danger_threshold=0.5,
                     why="held-out: half public / half new team, switch-happy"),
}
STANDINS.update(HOLDOUTS)
HOLDOUT = list(HOLDOUTS)

# WIDE stand-ins (tools/make_wide.py -> harness/wide_teams.json): invented teams in different archetypes, for
# robustness to hidden variants that use a different team. wd_* = tuning, wh_* = held out for final testing.
_WIDE_FILE = Path(__file__).resolve().parent / "wide_teams.json"
_WIDE = json.loads(_WIDE_FILE.read_text(encoding="utf-8")) if _WIDE_FILE.is_file() else {}
for _n, _w in _WIDE.items():
    STANDINS[_n] = dict(team=_w["team"], style=_w["style"], why=f"WIDE stand-in ({_w['split']}): invented team")
_RAND_FILE = Path(__file__).resolve().parent / "wide_rand.json"
_RAND = json.loads(_RAND_FILE.read_text(encoding="utf-8")) if _RAND_FILE.is_file() else {}
for _n, _w in _RAND.items():   # wr_*: wd_* species with random moves (fair test of the policy's moveset guess)
    STANDINS[_n] = dict(team=_w["team"], style=_w["style"], why="WIDE stand-in, random moves")
_WIDE.update(_RAND)
WIDE_RAND = list(_RAND)
WIDE_TUNE = [n for n, w in _WIDE.items() if w["split"] == "tune"]
WIDE_HOLD = [n for n, w in _WIDE.items() if w["split"] == "holdout"]

SHIPPED = ["public", "offensive", "defensive", "status", "speed", "policy"]
# Default opponent set for tuning/testing (weights equal). 'policy' kept separate: it is only
# what the stock local runner uses when a custom policy is supplied.
CORE = ["public", "si_aggressive", "si_patient", "si_altmoves", "si_altteam_a", "si_altteam_b", "si_giratina",
        "offensive", "defensive"]


def write_standins() -> None:
    STANDIN_DIR.mkdir(exist_ok=True)
    for name, spec in STANDINS.items():
        cfg = dict(_BASE)
        cfg.update({k: v for k, v in spec.items() if k not in ("team", "why")})
        cfg["variant"] = name
        cfg["team"] = spec["team"]
        cfg["lead_order"] = [0, 1, 2, 3, 4, 5]
        cfg["shuffle_lead"] = True
        cfg["_assumption"] = spec["why"]
        (STANDIN_DIR / f"{name}.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")


def config_path(name: str) -> Path:
    if name in SHIPPED:
        return ROOT / "variants" / f"{name}.json"
    p = STANDIN_DIR / f"{name}.json"
    if not p.is_file():
        write_standins()
    return p


if __name__ == "__main__":
    write_standins()
    print("wrote", sorted(p.name for p in STANDIN_DIR.glob("*.json")))
