# PROGRESS — Cynthia's Gauntlet

_Last updated: 2026-11-25 23:50 IST. Deadline: 2026-11-28 23:59 IST._
Detailed numbers for every experiment: `EXPERIMENT_LOG.md`. Raw outputs: `results/`.

## Current best (valid, saved in `submission/`)

| Item | Value |
|---|---|
| Team | weavile / starmie / gengar / gyarados / swinub / ralts (40/40; E5). Zip-mix score with policy v3: 75.0% (E6) |
| Policy | `submission/policy.py` = `policy_build/policy.py` v3 (27,578 bytes, sha1 `27080742086e…`) |
| Score, team + policy v3 | **79.89%** mean over 9 CORE opponents, n=200/opponent, tune seeds (79.44% at n=400) |
| Score, same team + baseline policy | 35.0% CORE mean (n=100); 46.8% vs public (n=500) |
| Weakest matchups (n=400) | si_giratina 42.0%, si_altteam_a 44.0%, si_altteam_b 65.2% |
| Fallbacks / turn-limit losses | 0 / 0 |
| Avg turns in won battles | 17.9 |
| Team-only fallback | `submission/team_only/team.json`: the same team for now (not yet optimised for the baseline policy) |

Both `team.json` files pass `engine.validator`; `python -m engine.policy --check submission/policy.py` -> valid.
These are **tuning-seed** numbers, not the final unseen-seed test (Phase 5).

## Work completed

1. **Phase 1 – analysis.** Read the PDF rulebook, `docs/*`, the engine, validator, configs and examples. Engine files in the
   folder are byte-identical to the public site bundle (`tools/diff_bundle.py`). Organisers' tests: 137/137 pass.
2. **Phase 2 – harness** (`harness/`): parallel, reproducible evaluation with common random numbers, Wilson 95% CIs,
   fallback counting by reason, per-turn latency; memoisation verified bit-identical (360 battle logs, 0 mismatches);
   ~3–4x faster than stock. Separate seeds (tune 1,000,000+i / test 900,000,000+i) and opponents
   (CORE for tuning, HOLDOUT for final testing).
3. **Phase 3 – policy** (`policy_src/policy_template.py` -> `tools/build_policy.py`): exact Gen-4 damage model
   (0 mismatches vs engine on 20,000 cases), Cynthia move prediction replicating her scoring, duel evaluator over
   turns-to-KO distributions, voluntary switching, per-Pokemon usefulness. 69.2% (best_policy.py) -> 79.4% on the same team.
4. **Phase 4 – team search (in progress).** Analytic screen + staged simulation failed (best 63.8%: the screen rewarded
   cheap fillers). Now running simulation-driven local search from the current best team.

## Rules decision (2026-11-26)

User: **follow everything in `CynthiaXCustodia.zip`** (folder is byte-identical to it). Binding rules = zip docs, not the PDF:
100 hidden battles (34/33/33, public + hidden aggressive + patient), optional policy, README + public GitHub repo, resubmission OK.
The zip's runner gives policy entries the boss `policy` variant instead of public. Measured (E6): policy entry 75.0% vs
team-only 39.2% on that mix -> **submit with policy**. Team now = ralts version (E5). Search now optimises `--objective zip` (E7).

- 2026-11-26 18:00: installed the organisers' new `cynthia_data (1).zip` (learnsets pre-filtered to 201 supported moves;
  validator-only change, battles unaffected; backup in `results/checkpoints/cynthia_data_v1_backup/`). All our teams still validate.

- Policy **v4** submitted (E9): recognises the Giratina team -> CORE 81.11% (v3 80.22), zip objective 66.17% (v3 64.00),
  boss `policy` variant 40.0% (v3 35.5). Boss-damage detection built and verified but OFF (no gain).

- **Area 1 (robustness to different hidden teams), 2026-11-26:** WIDE stand-ins (E10; wd_* tune, wh_* held out,
  wr_* = random moves for fair policy tests). Policy **v5** submitted (E12): guesses likely movesets of unknown
  species -> fair-test mean 71.93% vs 66.57% (v4). Team search `_p4` with `--objective robust` running (E13).
  Open: first-turn latency under heavy machine load (cold start ~250 ms idle, up to ~950 ms when 12 cores busy).

- **2026-11-27:** E14 knowledge audit: policy knowing public.json only = same as public+policy.json (+0.02 [-0.22,+0.26]);
  no knowledge -3.29. User approved -> **submitted** public-only build (`submission/policy.py`, sha1 ec5379a347b4..., build default now `public`).
  E15: Gyarados bite -> stone-edge +0.96 [+0.65,+1.27] (n=1000 x 15 opp) -> **promoted** to `submission/team.json`.
  Idle latency OK (first turn max 302 ms, 0 fallbacks). **Phase 5 done (E16)**, unseen seeds, n=10,000/opp:
  held-out mean 54.4%, tuning opps 72.1% (no seed overfit), expected 100-battle mix 92.5% (public slot) / 75.0% (policy slot).
  README written (`submission/README.md`, solo entry). Repo: `repo/` via `tools/export_repo.py`, remote
  github.com/24f3003058/cynthia-gauntlet (private; make public after submitting). First commit awaiting user OK.

## Key findings (verified in code or by measurement)

- **Rules conflict.** PDF rulebook: team.json only, no policy, 1000 battles per variant, one final submission, ties split
  prize. `docs/rulebook.txt` / participant note / spec: optional policy.py + GitHub repo + README, **100 battles total**
  (34/33/33), resubmission allowed, tie-break = fewer avg turns in wins. Unresolved — ask the organisers.
- **Engine applies no status, stat stages, flinch, confusion or healing**, although the rulebook says it does; all status
  moves are on the unsupported list, so battles are pure damage races. Only drain/recoil, multi-hit, crits, accuracy,
  priority and PP matter.
- **The stock runner silently swaps `public` for the `policy` variant when a custom policy is given**
  (`engine/runner.py:81`): Giratina + boss mode on 30% of seeds (Cynthia x1.15 damage, player x0.85).
  run1000 team + best_policy: 85.4% vs public but 31.8% vs `policy`. If the official evaluator uses this runner,
  submitting a policy faces a harder opponent. **Must be clarified with the organisers.**
- **Policy size limit:** the sandbox runs `python -I -c <source>`; Windows caps the command line at 32,767 chars.
  A 66 KB policy fails `--check` (every turn would fall back). The build refuses > 31,000 bytes.
- **Baseline policy bug:** its lookahead models every opponent as 100 HP regardless of `hp_percent`.
- **Data:** Extreme Speed has priority +2 (Gen 5 value; Gen 4 is +1). Cynthia's public Roserade knows Extrasensory
  (not in its learnset), the `policy` variant's Giratina uses Shadow Force (unsupported) as a plain 120-power hit.
- **Simultaneous last faint:** the side whose Pokemon fainted first loses (a recoil KO with your last Pokemon wins).
- **`variants_private/` (aggressive.json, patient.json) is in the folder.** Never opened or used: the note forbids reading
  hidden variants. Stand-ins are built from the spec's public description instead.

## Commands

```bash
# from the project root  (Git Bash; PowerShell: $env:PYTHONPATH="."; python ...)
PYTHONPATH=. python tools/build_policy.py                      # template -> policy_build/policy.py (size-checked)
PYTHONPATH=. python -m engine.policy --check policy_build/policy.py
PYTHONPATH=. python -m harness.evaluate --team submission/team.json --policy submission/policy.py --n 400
PYTHONPATH=. python -m harness.evaluate --team submission/team.json --n 200          # baseline policy
PYTHONPATH=. python -m harness.evaluate --team T.json --policy P.py --opponents ho_team_c,ho_params,ho_mixed --seeds test --n 10000  # final test only
PYTHONPATH=. python tools/sweep.py TEAM.json POLICY.py 400 '[{}, {"beta": 1.0}]'    # policy parameter sweep
PYTHONPATH=. python tools/team_search.py local --start TEAM.json --iters 80 --n 60 --tag _p1   # team local search
PYTHONPATH=. python tools/verify_fastcache.py 15               # cache == stock engine check
```

## Search checkpoints (all under `results/`)

| File | Contents |
|---|---|
| `sweeps.jsonl` | every policy-parameter sweep result (params, mean, per-opponent) |
| `p3_v1_*.json`, `p3_v2_buckets.json` | policy v1/v2 vs best_policy evaluations |
| `candidates.json`, `screen.json` | per-species movesets; analytic-screen ranking (top annealed teams) |
| `sim_stage_n60.json` | stage-1 battle results of the 30 screened teams |
| `checkpoints/simulate_stage1_and_partial_stage2.txt` | full simulate output incl. the partial n=200 stage |
| `local_log_p1.txt`, `local_run_p1.out` | local search: one line per iteration (appended live) |
| `local_best_p1.json` | best team found by local search (written on every accepted change; absent = start team still best) |
| `checkpoints/local_p1_start_team.json` | the local search start team |
| `checkpoints/policy_v3_template.py`, `policy_v3_build.py` | frozen copy of policy v3 (the submitted one) |
| `checkpoints/phase1_*.txt` | Phase-1 measurements |

`tools/team_search.py local` takes `--seed` (default 1); the 2026-11-26 resume used `--seed 2` so it does not repeat iterations 0-7.
To resume the local search after an interruption: start again with
`--start results/local_best_p1.json` if it exists, else `--start results/checkpoints/local_p1_start_team.json`.

## Next steps

1. Finish local search `_p1` (running); then try a few hand-picked teams aimed at the weak matchups
   (Giratina team, Togekiss/Glaceon team).
2. Co-optimise: re-tune policy parameters (alpha, beta, switch_margin) on the new team, then one more team pass.
3. Team-only track: local search with the **baseline** policy for `submission/team_only/team.json`.
4. Phase 5: >= 10,000 unseen-seed battles per opponent (CORE + HOLDOUT + `policy`) for the finalists.
5. Write README.md (strategy, policy behaviour, who did what, credits); final validator + `--check`.
6. Ask the organisers: which rulebook applies, and which variant a policy submission plays against.
