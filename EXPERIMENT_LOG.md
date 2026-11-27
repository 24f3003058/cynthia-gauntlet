# Experiment Log — Cynthia's Gauntlet

All numbers are produced by scripts in `tools/`; raw outputs are kept next to them (`tools/*.txt`).
Seeds for Phase-1 measurements: 10,000,000 + i (disjoint from the 0..999 range the shipped tools use).
CI = Wilson 95% interval.

## 2026-11-25 — Phase 1 setup

- Engine obtained from the public site bundle `https://adicodexy.github.io/CynthiaXCustodia/static/engine_bundle.json`
  (snapshot in `_site_snapshot/`). The repo files the user added later are byte-identical for
  `engine/`, `config/`, `variants/`, `cynthia_data/` (`python tools/diff_bundle.py` prints no diffs).
- `ui/` (local server) and `tests/` were missing at first; the user added them at 22:37.
- Throughput: ~2.1 battles/s single process with the baseline policy; ~8–17 battles/s on 12 workers.
  81% of time is spent inside the baseline policy's `ai_core.expected_damage` (cProfile, 5 battles).

### E1 — site default team (lucario/medicham/quagsire/bibarel/staraptor/pikachu), baseline policy, 1000 seeds/variant
`PYTHONPATH=. python tools/quick_eval.py examples/site_default_team.json 1000 public,offensive,defensive,status,speed,policy`
Result: 0.0% on every variant except defensive 0.2% (2/1000). See `tools/phase1_baseline_site_default.txt`.

### E2 — example teams/policies (500 seeds/variant, phase-1 seeds) — `tools/phase1_examples.txt`, `tools/phase1_run1000team.txt`
| team + controller | public | offensive | defensive | status | speed | policy |
|---|---|---|---|---|---|---|
| best_team.json + baseline | 6.2 | 3.4 | 2.8 | 7.4 | 7.2 | 0.2 |
| best_team.json + example_policy | 0.2 | 0.0 | 0.0 | 0.8 | 0.0 | 0.0 |
| best_team.json + best_policy | 0.0 | 0.2 | 2.6 | 0.6 | 0.8 | 0.4 |
| run_1000_eval team + baseline | 46.8 | – | – | – | – | 2.6 |
| run_1000_eval team + best_policy | 85.4 | 87.0 | 81.2 | 85.6 | 84.6 | 31.8 |
0 fallbacks, 0 turn-limit losses everywhere.

## 2026-11-25 — Phase 2: harness

- Organisers' test suite: 137/137 pass (pytest in a scratch venv; system Python untouched).
- `variants_private/` (aggressive.json, patient.json) appeared in the folder. NOT opened, NOT used:
  rulebook/note forbid reading hidden variants. Stand-ins are built from the public spec text instead.
- `harness/fastcache.py`: memoises ai_core.expected_damage / calculate_damage and replaces ai_search's
  deepcopy of JSON-like dicts. `tools/verify_fastcache.py 15`: 360 battles (3 teams x 4 opponents x
  baseline/best_policy) -> 0 mismatching full-log hashes. Throughput ~33 battles/s on 12 cores (baseline policy).
- `harness/evaluate.py`: own copy of the runner loop (requested opponent always used), fallback counting,
  per-turn latency, Wilson CIs, equal-weight mean. Seeds: TUNE = 1,000,000+i, TEST = 900,000,000+i.
- `harness/opponents.py`: CORE (tuning) = public, offensive, defensive + stand-ins si_aggressive, si_patient,
  si_altmoves, si_altteam_a, si_altteam_b, si_giratina. HOLDOUT (final test only) = ho_team_c, ho_params, ho_mixed.
  Also 'policy' (shipped, boss mode) reported separately.

### E3 — run_1000_eval team + baseline, CORE, 100 seeds/opponent (tune seeds)
public 50.0, si_aggressive 46.0, si_patient 30.0, si_altmoves 53.0, si_altteam_a 20.0, si_altteam_b 45.0,
si_giratina 3.0, offensive 38.0, defensive 30.0 -> MEAN 35.0% [32.0, 38.0]; avg win turns 14.1.

## 2026-11-25/26 — Phase 3: policy (`policy_src/policy_template.py` -> `tools/build_policy.py` -> `policy_build/policy.py`)

Constraint found: engine/policy.py's sandbox runs `python -I -c <whole source>`; Windows caps a command line at
32,767 chars, so a 66 KB first build failed `--check` with WinError 206 (every turn would fall back to baseline).
The build now packs data into strings, strips docstrings via AST, re-indents to 1 space (AST-equality asserted)
and refuses to write > 31,000 bytes. Current size 27,578 bytes.

Checks: decoded tables == CSVs (266/249 species, 297 moves, 110 chart entries, 0 mismatches);
policy damage formula == engine.damage.calculate_damage on 20,000 random (attacker, defender, move, crit, roll): 0 mismatches.

All on run1000 team, CORE opponents, tune seeds (same seeds for every row => paired comparisons):
| version | n/opp | mean | notes |
|---|---|---|---|
| examples/best_policy.py | 200 | 69.22 | reference |
| v1 exact-damage duel evaluator | 200 | 73.94 | max turn 529 ms (too slow) |
| v2 + caches + 6-bucket first-turn compression | 200 | 75.56 | max turn ~117 ms, 114 battles/s |
| v2, voluntary switching OFF | 200 | 38.83 | switching is essential |
| v2, use_prior OFF | 200 | 70.28 | public movesets as prior help |
| v2 (defaults) | 400 | 76.75 | |
| v2 switch_margin 0, alpha 2 | 400 | 77.75 | plateau: all param combos 76.4–77.8 |
| v3 + per-Pokemon usefulness (beta 0.5) | 400 | **79.44** | per opp: 93.8 93.5 94.0 96.5 44.0 65.2 42.0 91.8 94.2; max turn 127 ms |
| v3 beta 1.0 / alpha1+beta1 / alpha1+beta2 | 400 | 79.36 / 78.33 / 79.19 | |
Defaults now alpha 2, switch_margin 0, beta 0.5. Raw lines in results/sweeps.jsonl. 0 fallbacks in every run.

## 2026-11-26 — Phase 4: team search

### E4 — analytic screen + staged simulation (`tools/team_search.py screen|simulate`)
Screen: 443 species with >= 4 usable moves, 589 movesets, 1v1 matrix vs 21 CORE pool Pokemon, annealing on
mean(0.6*best + 0.4*second answer). Top screened teams were Slaking + 1-2 strong + cheap fillers.
Simulation (policy v3, CORE, tune seeds): best of 30 at n=60/opp 61.85%; stage n=200: best 63.83%
(starmie lapras gliscor alakazam starly makuhita). All far below run1000 team (79.44%) -> the screen's
"two good answers" fitness rewards fillers that simply die. Stopped; switched to simulation-driven local search.

## 2026-11-26 — Rules: follow CynthiaXCustodia.zip (user decision)

The user directed: follow everything in `CynthiaXCustodia.zip`. Folder == zip (35,578 files, 0 diffs, 0 missing).
So the zip docs (`docs/rulebook.txt`, `NOTE_TO_PARTICIPANTS.md`, `SIMULATOR_SPEC.md`) are binding, not the PDF:
100 hidden battles 34/33/33 over public + 2 hidden variants (aggressive, patient); optional policy.py; README.md
(strategy, policy, who did what) + public GitHub repo matching the upload; resubmission allowed; tie-break fewer win turns.
The zip's runner (`engine/runner.py:81`) plays the `policy` (boss) variant instead of public for policy entries.

### E5 — local search _p1 (CORE objective), 80 iters + resume seed 2
Accepted: pichu->ralts (80.11), ralts moveset (80.22 vs 79.89 at n=200). Promoted to submission/team.json
(old team: results/checkpoints/submission_team_pichu_v1.json).

### E6 — zip-mix evaluation, n=300/opp, tune seeds (results/zipmix_*.json)
| entry | public slot | si_aggressive | si_patient | mean |
|---|---|---|---|---|
| pichu team + policy v3 (public->policy) | 34.7 | 93.3 | 94.7 | 74.22 |
| ralts team + policy v3 (public->policy) | 36.3 | 93.7 | 95.0 | 75.00 |
| pichu team, baseline (public) | 44.7 | 41.3 | 28.7 | 38.22 |
| ralts team, baseline (public) | 45.7 | 43.3 | 28.7 | 39.22 |
Decision: submit WITH policy. Biggest lever now = the `policy` variant (~36%).

### E7 — local search _p2, `--objective zip` (1/3 policy variant + 2/3 mean of non-public CORE), seed 3 (running)

## 2026-11-26 18:00 — organisers' updated cynthia_data.zip ("cynthia_data (1).zip")
Only learnsets.csv + DATA_NOTES.md differ (costs, moves, pokemon, type_chart identical). learnsets pre-filtered to the
201 simulator-supported moves: 29,451 -> 10,001 rows, 466 -> 201 moves, 0 rows added; ditto/smeargle/unown/wobbuffet/wynaut
have no moves left. Only engine/validator.py reads learnsets -> battles, Cynthia and the policy build are unaffected.
Installed into cynthia_data/ (old files: results/checkpoints/cynthia_data_v1_backup/). submission team, team_only team,
pichu team, all search candidate sets still valid. pytest not re-run (scratch venv creation failed).

### E7 result — local search _p2 (--objective zip), 79 iters, seed 3
Start 64.00 (n=200). One accept: gengar moves -> shadow-ball/energy-ball/focus-blast/ice-punch, 64.17 (+0.17, noise).
Not promoted. Team search has plateaued; next lever is the policy.
(zip objective = 1/3 policy-variant + 2/3 mean of 8 non-public CORE stand-ins.)

### E8 — policy parameter sweep on the zip objective (`SWEEP_OBJECTIVE=zip tools/sweep.py`, n=200), running

### E8 result — policy v3 parameter sweep, zip objective, n=200 (results/sweep_zip_p1.out)
defaults 64.00 | alpha1 61.79 | alpha3 61.62 | beta0 62.58 | beta1 62.83 | switch_margin .3 62.62 | -.2 49.92 |
unknown_power 110 63.04 | use_prior off 56.33. Defaults stay; parameter tuning exhausted.

### E9 — policy v4 (policy_src/policy_template.py; frozen copy results/checkpoints/policy_v4_*.py)
Two changes, both using only `state`:
1. Expected unrevealed foes: was "public team if everything seen is in it"; now "members common to every published
   team (variants/public.json, variants/policy.json) consistent with what has been seen" (_TEAMS from the build).
2. `_detect_boss`: infers the engine's boss multipliers (foe x1.15, ours x0.85) from exact damage events.
   Verified vs engine truth (crc32(seed)%10<3): 58/58 boss battles detected (by decision ~1.7), 0/200 false positives.
   But on 119 boss battles: 13 wins with it vs 15 without (14 outcomes flip both ways) -> no gain. Default OFF.
   (A first check reported 2/58: a test-script artefact -- the module-level _BOSS flag was left on after the battle.)
Results (same team, tune seeds, n=200):
| | zip objective | policy var | si_giratina | CORE mean |
|---|---|---|---|---|
| v3 | 64.00 | 35.5 | 43.0 | 80.22 |
| v4 | 66.17 | 40.0 | 52.0 | 81.11 |
v4 promoted to submission/policy.py (28,868 bytes, sha1 5363a62d8b02..., --check valid). v3 kept as
results/checkpoints/policy_v3_submitted.py.

## 2026-11-26 — Area 1: robustness to hidden variants with different teams

### E10 — WIDE stand-ins (tools/make_wide.py -> harness/wide_teams.json; registered in harness/opponents.py)
10 invented archetype teams, moves auto-picked from the new supported learnsets (best STAB + coverage with >=45%
of the best move's value). Tuning: wd_water, wd_dragons, wd_special, wd_steel, wd_legends, wd_toxic.
Held out (final test only): wh_fire, wh_bulky, wh_sinnoh, wh_icerock.
Current submission (ralts team + policy v4), n=200, tune seeds (results/wide_tune_v4.json):
water 13.5 | dragons 80.0 | special 21.5 | steel 26.5 | legends 46.5 | toxic 65.5 -> MEAN 42.25%.
=> the team is specialised to Cynthia's known species.

### E11 — local search _p3, `--objective robust` = (policy variant + mean non-public CORE + mean WIDE_TUNE)/3,
start = submission team, seed 4, 120 iters (running; results/local_run_p3.out, local_best_p3.json)

### E11 (stopped at it 30/120) — accepts: weavile aerial-ace -> quick-attack (54.18 vs 53.83, n=200),
starmie move ORDER only (56.65) -> order change is not a real improvement (RNG/tie-break luck); reverted in p4 start.

### E12 — policy v5: likely-moveset guess for species without a published moveset
tools/movesets.py (shared with make_wide): best STAB per own type + greedy SE coverage (>=45% of best value).
Build stores 4 chars per species (type*4 + special*2 + strong; strong = eff. power >= 85 -> 100 else 75);
248 species. _opp_moves fills unrevealed moves from it (types not yet seen), coverage power x guess_cov.
Boss-detect code removed (was off, no gain). Size 29,499 bytes. Idle cold-start first turn 240-315 ms (v3 250-280).
Under full 12-core load both v3 and v5 hit 470-950 ms -> note: first-turn timeout risk on a loaded machine.
Fair test (moves of wr_* drawn at random, so the guess is not graded on its own heuristic), n=200, 15 opponents
(policy + 8 non-public CORE + 6 wr_*), ralts team:
| guess | mean | altteam_a | altteam_b | wr_water | wr_special | wr_steel | wr_legends | wr_toxic |
|---|---|---|---|---|---|---|---|---|
| off (=v4) | 66.57 | 42.0 | 66.0 | 40.5 | 31.0 | 43.0 | 23.0 | 88.5 |
| cov 1.0 | 68.73 | 56.5 | 70.5 | 49.0 | 47.5 | 55.0 | 19.5 | 68.5 |
| cov 0.85 | **71.93** | 57.0 | 79.5 | 66.0 | 48.5 | 52.5 | 22.0 | 89.5 |
| cov 0.75 | 71.03 | 58.0 | 80.0 | 66.0 | 41.5 | 45.0 | 23.5 | 88.0 |
| cov 0.65 / 0.5 / 0.25 | 69.33 / 67.03 / 66.50 | | | | | | | |
Known-team opponents identical (published movesets used). v5 (guess_cov 0.85) promoted to submission/policy.py.

### E13 — local search _p4: robust objective now uses WIDE_RAND (wr_*) instead of wd_*, policy frozen
results/checkpoints/policy_v5_build.py, start = p3 best with starmie order restored, seed 5, 120 iters (running)

### E13 (stopped at it 38/120: the process died with BrokenPipe, 2026-11-26 ~19:13)
Accepts (n=200, robust objective): starmie moves 62.26 | gyarados moves 62.82 | weavile moves 64.81 (start 59.87).
Diff of results/local_best_p4.json vs submission/team.json: starmie and weavile = move ORDER only (not a real change,
see E11); the only real change is gyarados bite -> stone-edge. Not promoted yet: needs a paired test at n>=1000.

### E14 — fair-play knowledge audit (tools/compare.py, policy_build/audit/v5_{all,public,none}.py, ralts team)
all = public.json + policy.json movesets hard-coded; public = public.json only; none = no opponent data.
15 opponents (policy + 8 non-public CORE + 6 wr_*), n=1000, seeds 700,000,000+. First run (19:07) died with
MemoryError (12 workers + the p4 search). Re-run 2026-11-27 with --workers 6 (new compare.py flag).

### E15 — Gyarados bite vs stone-edge (submission team otherwise unchanged; results/checkpoints/team_gyarados_stoneedge.json)
Paired compare.py, policy v5, same 15 opponents/seeds as E14, n=1000, --workers 4, run in parallel with E14
(WSL shut down to free ~2.7 GB: commit charge was 23.5/24.7 GB; each worker ~530 MB).
E14 result (n=1000/opp, seeds 700,000,000+, results/audit_15opp_n1000.{txt,json}):
| knowledge | MEAN 15 opp | excl policy | policy var | si_giratina | offensive |
|---|---|---|---|---|---|
| all (public+policy.json) | 71.63 | 73.81 | 41.1 | 52.6 | 93.0 |
| public.json only | 71.65 (diff +0.02 [-0.22,+0.26]) | 73.86 | 40.6 | 52.8 | 93.1 |
| none | 68.33 (diff -3.29 [-3.80,-2.78]) | 70.89 | 32.5 | 44.9 | 82.7 |
=> hard-coding policy.json gives NO measurable gain; public.json knowledge is worth ~3.3 points. 0 fallbacks all.
Max policy ms: all 524, public 989 (that run overlapped the start of E15 -> machine load), none 288.
E15 result (n=1000/opp, seeds 700,000,000+, results/gyarados_stoneedge_n1000.{txt,json}):
bite 71.63 -> stone-edge 72.59, paired diff +0.96 [+0.65,+1.27] (excl policy +1.02 [+0.69,+1.36]).
Gains only where it matters: si_altteam_a +7.7 [+4.6,+10.8], wr_water +6.7 [+4.3,+9.1]; every other opponent within +-0.5.
0 fallbacks; max policy ms 201/173 (idle-ish machine). 'bite' reproduces E14 'all' exactly (71.63) -> harness consistent.
Caveat: both gaining opponents were in the p4 search objective (different seeds); confirm on HOLDOUT/wh_* in Phase 5.
PROMOTED: submission/team.json = stone-edge team (validator OK, cost 40/40). Old team: results/checkpoints/submission_team_ralts_bite.json.

### 2026-11-27 — public-only policy submitted (user decision after E14)
tools/build_policy.py default POLICY_KNOWLEDGE changed all -> public; rebuild is byte-identical to the audited
policy_build/audit/v5_public.py. submission/policy.py = that build (29,335 bytes, sha1 ec5379a347b4...), --check valid.
Previous (all-knowledge) policy kept as results/checkpoints/policy_v5_all_submitted.py.
Idle latency, organisers' sandbox, fresh process per battle, 60 battles (tools/turn_timing.py):
first turn median 190 / p99 235 / max 302 ms; later turns median 5 / max 119 ms; 0 fallbacks, 0 turns > 500 ms.
=> the 989 ms in E14 was machine load (E15 starting), not the policy.

### E16 — Phase 5 final test (unseen seeds 900,000,000+, n=10,000/opp, --workers 8)
Entries: final = submission (stone-edge team + public-only policy); bite = results/checkpoints/submission_team_ralts_bite.json + same policy.
Part A: HOLDOUT ho_team_c, ho_params, ho_mixed + WIDE_HOLD wh_fire, wh_bulky, wh_sinnoh, wh_icerock (never used for tuning).
  Note: wh_* movesets were auto-picked by tools/movesets.py, the same heuristic as the policy's moveset guess -> optimistic.
Part B: policy, public + 8 non-public CORE + 6 wr_* (tuning opponents, unseen seeds).
E16 Part A result (results/final_A_holdout_n10000.{txt,json}), final vs bite (paired, n=10,000/opp):
ho_team_c 46.0 vs 43.9 | ho_params 92.2 vs 92.2 | ho_mixed 96.2 vs 97.3 | wh_fire 14.3 vs 13.9 | wh_bulky 35.3 vs 35.6 |
wh_sinnoh 78.3 vs 71.0 | wh_icerock 18.3 vs 15.1 | MEAN 54.38 vs 52.71: stone-edge +1.67 [+1.45,+1.88] -> confirmed on held-out.
0 fallbacks, 0 turn-limit losses; max policy ms 778 (8 workers busy). Weak spots: wh_fire 14%, wh_icerock 18%, wh_bulky 35%.
Part B: final entry only (stone-edge settled), 16 opponents, n=10,000.
E16 Part B result (results/final_B_n10000.{txt,json}), final entry, n=10,000/opp, seeds 900,000,000+:
policy 40.9 | public 92.4 | si_aggressive 92.9 | si_patient 92.4 | si_altmoves 93.6 | si_altteam_a 70.0 | si_altteam_b 79.9 |
si_giratina 51.2 | offensive 92.5 | defensive 90.2 | wr_water 65.5 | wr_dragons 99.2 | wr_special 48.1 | wr_steel 52.5 |
wr_toxic 88.5 | wr_legends 24.2. 15-opp mean (excl public) 72.11 vs 72.59 on seeds 700M (E15) -> no overfitting to seeds.
Expected 100-battle mix (34/33/33): 92.54% if public slot = public variant; 75.03% if it is the policy variant.
0 fallbacks, 0 turn-limit losses; max policy ms 916 with 8 workers busy (idle max 302 ms, see 2026-11-27 entry).
