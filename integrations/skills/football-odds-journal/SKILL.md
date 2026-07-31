---
name: football-odds-journal
description: Operate this repository's governed football match workflow. Use when an agent needs to archive a user's match analysis long-form text, live update, correction, result, "复盘：" or postmatch review; extract evidence; prepare an analysis; retrieve cases; validate or lock conclusions; or process match results in AnalysisofFootballOddsProviderData.
---

# Football Odds Journal

1. Open the repository root and read `AI_START_HERE.md` and `AGENTS.md`.
2. Run `scripts/odds-journal.ps1 agent doctor` on Windows or `scripts/odds-journal.sh agent doctor` on macOS.
3. Run `agent changes` when repository data, rules, workflow files, CLI contracts, or a desktop product version changes. Data-only changes rebuild the index; compatible rules do not reinstall this Skill. Never run `agent sync` without explicit lcz approval.
4. When the user sends match long-form text for storage, read `references/journal-ingest.md`. Route one unambiguous fixture to `journal new`, `journal append`, or `journal review`; storage-only work must not add predictions.
5. For extraction-only work, record facts and sources without predictions.
6. For analysis, run `agent start MATCH_PATH`. Stop on failure and follow its `next_actions`.
7. Record a scenario or no-scenario reason, retrieve cases, and treat cases only as comparison candidates.
8. Write the analysis with the active ruleset, cutoff, applied and excluded rule IDs, sources, evidence, counter-evidence, and pass conditions.
9. Run `agent validate-draft MATCH_PATH`, then `agent prepare-lock` before kickoff. Lock only with the immutable candidate receipt; never create one after kickoff.
10. For a review with one final score, call `journal review` directly. Let the CLI audit-lock, finish, and prepare review when allowed; on a blocked lifecycle, report the reason and do not reconstruct prematch choices.
11. After lock, append only live updates. Complete scenario resolutions and evaluation before `review`, then link evidence.

Do not copy football rules into this skill. Load the published rules through the repository CLI so historical versions and hashes remain authoritative.
