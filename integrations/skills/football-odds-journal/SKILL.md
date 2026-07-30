---
name: football-odds-journal
description: Operate this repository's governed football match workflow. Use when an agent needs to extract match evidence, prepare a match analysis, retrieve comparable cases, validate a prediction draft, lock conclusions, record results, or perform a postmatch review in AnalysisofFootballOddsProviderData.
---

# Football Odds Journal

1. Open the repository root and read `AI_START_HERE.md` and `AGENTS.md`.
2. Run `scripts/odds-journal.ps1 agent doctor` on Windows or `scripts/odds-journal.sh agent doctor` on macOS.
3. For extraction-only work, record facts and sources without predictions.
4. For analysis, run `agent start MATCH_PATH`. Stop on failure and follow its `next_actions`.
5. Record a scenario or no-scenario reason, retrieve cases, and treat cases only as comparison candidates.
6. Write the analysis with the active ruleset, cutoff, applied and excluded rule IDs, sources, evidence, counter-evidence, and pass conditions.
7. Run `agent validate-draft MATCH_PATH` before lock. Never bypass a failed gate.
8. After lock, append only live updates. Use `finish`, `prepare-review`, scenario resolutions, `review`, and evidence linking in order.

Do not copy football rules into this skill. Load the published rules through the repository CLI so historical versions and hashes remain authoritative.
