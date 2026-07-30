---
name: football-odds-journal
description: Operate this repository's governed football match workflow. Use when an agent needs to archive a user's match analysis long-form text, live update, result or review; extract match evidence; prepare an analysis; retrieve cases; validate or lock conclusions; record results; or perform a postmatch review in AnalysisofFootballOddsProviderData.
---

# Football Odds Journal

1. Open the repository root and read `AI_START_HERE.md` and `AGENTS.md`.
2. Run `scripts/odds-journal.ps1 agent doctor` on Windows or `scripts/odds-journal.sh agent doctor` on macOS.
3. Run `agent changes` when repository data, rules, workflow files, CLI contracts, or a desktop product version changes. Data-only changes rebuild the index; compatible rules do not reinstall this Skill. Never run `agent sync` without explicit lcz approval.
4. When the user sends match long-form text for storage, read `references/journal-ingest.md`. Classify intent and segments, preserve the source, and use `journal ingest`; storage-only work must not add predictions.
5. For extraction-only work, record facts and sources without predictions.
6. For analysis, run `agent start MATCH_PATH`. Stop on failure and follow its `next_actions`.
7. Record a scenario or no-scenario reason, retrieve cases, and treat cases only as comparison candidates.
8. Write the analysis with the active ruleset, cutoff, applied and excluded rule IDs, sources, evidence, counter-evidence, and pass conditions.
9. Run `agent validate-draft MATCH_PATH` before lock. Never bypass a failed gate.
10. After lock, append only live updates. Use `finish`, `prepare-review`, scenario resolutions, `review`, and evidence linking in order.

Do not copy football rules into this skill. Load the published rules through the repository CLI so historical versions and hashes remain authoritative.
