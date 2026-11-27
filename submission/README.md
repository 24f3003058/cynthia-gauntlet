# Cynthia's Gauntlet — our submission

**Files:** `team.json` (6 Pokémon, 40/40 points) and `policy.py` (custom battle policy, 29,335 bytes).
Both are produced by the tooling in this repository; nothing in the simulator or evaluator is modified.

The submitted files are in `submission/`. This repository holds **only our own code**: the organisers' simulator
(`engine/`, `cynthia_data/`, `variants/`, …) is not included or modified.

---

## 1. How to run

Python 3.10+ (tested on 3.14), standard library only.

**Setup.** Copy this repository's folders (`submission/`, `harness/`, `policy_src/`, `policy_build/`, `tools/`,
`results/`) into the root of the organisers' simulator folder. Keep the simulator's own `README.md`; nothing of
theirs is overwritten. Then run from that root:

```bash
# Validate the team (6 Pokémon, <= 40 points, 4 supported moves each)
PYTHONPATH=. python -c "import json; from engine import validator as v; d=v.load_all(); t=json.load(open('submission/team.json')); print(v.validate_team(t, d), v.calculate_team_cost(t, d))"

# Check the policy in the organisers' sandbox (forbidden imports, legal actions, latency)
PYTHONPATH=. python -m engine.policy --check submission/policy.py

# Evaluate: win rate with Wilson 95% CIs, fallbacks, latency (parallel, reproducible seeds)
PYTHONPATH=. python -m harness.evaluate --team submission/team.json --policy submission/policy.py --n 400

# Paired comparison of two entries on identical seeds (what we used for every decision)
PYTHONPATH=. python tools/compare.py --entries A=submission/team.json:submission/policy.py,B=submission/team.json:baseline \
    --opponents public,offensive,defensive --n 1000 --seed-base 900000000
```

On Windows PowerShell, set `$env:PYTHONPATH="."` and drop the `PYTHONPATH=.` prefix.

`policy.py` is **generated**. Edit `policy_src/policy_template.py`, then run `PYTHONPATH=. python tools/build_policy.py`,
which embeds compact public game data and refuses outputs over 31,000 bytes. The sandbox passes the policy source on the
command line, and Windows caps that at 32,767 characters.

---

## 2. Team

| Slot | Pokémon | Moves |
|---|---|---|
| 1 (lead) | Weavile | Ice Punch, Night Slash, Brick Break, Aerial Ace |
| 2 | Starmie | Surf, Thunderbolt, Ice Beam, Psychic |
| 3 | Gengar | Shadow Ball, Thunderbolt, Energy Ball, Focus Blast |
| 4 | Gyarados | Waterfall, Ice Fang, Earthquake, Stone Edge |
| 5 | Swinub | Ice Shard, Earthquake, Ice Beam, Take Down |
| 6 | Ralts | Shadow Sneak, Psychic, Thunderbolt, Magical Leaf |

**Why this team.** In this simulator, status moves, stat stages, flinch and healing are never applied, so every battle
is a pure damage race: HP, speed, priority, accuracy, critical hits and switching. The team is built for that race:
- fast, hard-hitting attackers;
- Ice coverage on four members (Ice is 4x effective on Cynthia's Garchomp);
- priority moves (Ice Shard, Shadow Sneak) to finish weakened foes;
- broad type coverage so no single opponent walls the team.

Two cheap members (Swinub, Ralts) free up budget for the four strong ones.

**How it was chosen.** Choices were made by simulation, not by hand:
1. An analytic screen came first. It favoured cheap filler Pokémon and peaked at 63.8%, so we dropped it.
2. We then ran simulation-driven local search: swap a member, change moves or change the lead. Each candidate was
   screened on 60 battles per opponent, re-tested on 200 and accepted only if it improved.
3. The final change, Gyarados Bite → Stone Edge, was confirmed in a paired test: +0.96 points (95% CI +0.65 to +1.27)
   over 15 opponents × 1,000 battles.

Changes that only reordered moves were rejected, because they shift the random number sequence without making the team
better.

---

## 3. What the policy does

`choose_move(state)` uses only the `state` it is given plus embedded **public** game data (species stats, move data,
type chart, learnset-derived guesses, and Cynthia's published practice team `variants/public.json`). No imports, no file
or network access, no RNG inspection.

1. **Exact damage model.** The policy reproduces the engine's Gen-4 damage formula integer step by integer step: all
   16 damage rolls, STAB, type effectiveness, critical-hit stages, multi-hit distributions, fixed-damage and OHKO moves,
   recoil and drain. It matched the engine on 20,000 of 20,000 test cases.
2. **Duel evaluator.** For every legal option it estimates the expected change in *material* over the resulting
   one-on-one duel. Options are each move, each voluntary switch and each forced replacement; material is
   alive Pokémon × α plus remaining HP fraction. The estimate comes from turns-to-KO distributions built from the full
   damage-roll distribution, with speed order, priority and accuracy, modelled up to 8 turns ahead.
3. **Opponent prediction.** It predicts Cynthia's next move by replicating her move-scoring rule, so it knows when
   staying in is dangerous.
4. **Unknown opponents.** It starts from Cynthia's published movesets and drops them as soon as the battle
   contradicts them. For a species without a published set, it guesses a likely moveset: the best same-type move plus
   super-effective coverage, from the public learnsets. Unrevealed moves are filled in from that guess.
5. **Switching and usefulness.** A voluntary switch is made only if it beats the best attack. Replacements are weighed
   by how useful each Pokémon still is against the foes expected to remain.

**Fair play.** We tested whether knowing more than the public team helps. A build that also hard-coded the shipped
`policy` variant's team scored the same as the public-only build: +0.02 points, CI −0.22 to +0.26, over 15 opponents ×
1,000 battles. So we submit the **public-only** build. A build with no opponent data was 3.3 points worse. The files in
`variants_private/` were never opened or used.

**Robustness.** There were 0 fallbacks in every evaluation, and no battles lost to the 200-turn limit. Latency was
measured in the organisers' sandbox with a fresh process per battle, so every first turn is a cold start. The first
turn took a median of 190 ms (max 302 ms); later turns took a median of 5 ms. The limit is 1 second per turn.

---

## 4. How we evaluated

- **Harness** (`harness/`): a parallel, reproducible battle runner. Every entry in a comparison plays the same seeds
  (common random numbers). Results come with Wilson 95% confidence intervals and fallbacks counted by reason. It is
  verified bit-identical to the stock engine (`tools/verify_fastcache.py`).
- **Separate seeds:** tuning seeds start at 1,000,000. The final test uses seeds starting at 900,000,000, which were
  never used while tuning.
- **Stand-in opponents** were built from the public description of the hidden variants. We did not read those files.
  - aggressive and patient play styles;
  - alternative movesets;
  - three alternative teams;
  - ten invented archetype teams;
  - a separate held-out set (`ho_*`, `wh_*`) used only for the final test.
- Every result, including rejected ideas, is recorded in `EXPERIMENT_LOG.md`, with raw outputs in `results/`.

---

## 5. Final test (unseen seeds, 10,000 battles per opponent)

Seeds 900,000,000–900,009,999 were never used for tuning. There were 0 fallbacks and 0 turn-limit losses in all
230,000 battles. Raw outputs: `results/final_A_holdout_n10000.txt` and `results/final_B_n10000.txt`.

| Opponent | Win rate (95% CI ±0.5–1.0) |
|---|---|
| `public` (Cynthia's practice variant) | 92.4% |
| Aggressive / patient stand-ins (`si_aggressive`, `si_patient`) | 92.9% / 92.4% |
| Shipped `offensive` / `defensive` variants | 92.5% / 90.2% |
| Alternative movesets (`si_altmoves`) | 93.6% |
| Alternative teams (`si_altteam_a`, `si_altteam_b`, `si_giratina`) | 70.0% / 79.9% / 51.2% |
| `policy` variant (Giratina team, boss mode on 30% of seeds) | 40.9% |
| Random-moveset archetype teams (`wr_*`, mean of 6) | 63.0% |
| **Held-out** opponents, never used for tuning (`ho_*`, `wh_*`, mean of 7) | **54.4%** |

**Expected result on the official 100-battle mix** (34 public / 33 aggressive / 33 patient), using our stand-ins for
the hidden variants:
- **92.5%** if the public slot plays the `public` variant;
- **75.0%** if the runner swaps in the `policy` variant for entries that submit a policy, as the stock local runner does.

**Known weaknesses.** The team is tuned to Cynthia's own species. It wins about 92% against Cynthia-like teams but
much less against very different ones: held-out Fire 14%, Ice/Rock 18%, bulky 35%, and the boss-mode Giratina team 41%.

**Stone Edge on Gyarados** was confirmed on the held-out opponents: +1.67 points over Bite (95% CI +1.45 to +1.88),
paired over 70,000 battles.

---

## 6. Who did what

Solo entry: one person did everything (analysis, harness, policy, team search, evaluation, write-up), with
help from Claude Code (an AI coding assistant). All design decisions and the submission are the author's.

## 7. Credits

Simulator, data, rulebook and baseline policy: the Cynthia's Gauntlet organisers. Game data derives from public
Pokémon data in `cynthia_data/`. Our code: `harness/`, `policy_src/`, `tools/` (build, search, compare, timing), and the
files in `submission/`.
