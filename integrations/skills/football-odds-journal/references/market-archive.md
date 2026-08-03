# Market Screenshot Archive

Use this procedure for user-provided football odds screenshots. This is extraction and archiving only: do not give a direction, prediction, weighted conclusion, or score scenario.

1. Transcribe screenshots to `MarketArchiveDraftV1`. Keep the home side first and away side second. Default `market_scope` is `full_time`; default timezone is `Asia/Shanghai`.
2. Use one row for each verified provider/market/phase. Required raw keys are:
   - Asian handicap: `home_water`, `line`, `away_water`.
   - European odds and Kelly: `home_win`, `draw`, `away_win`.
   - Total goals: `over_water`, `line`, `under_water`.
3. Use `opening` and `late` for initial/current overview rows. A detailed Macau handicap timeline is `macau_timeline`, not ordinary provider rows. Its displayed times must be exact; the CLI maps earliest, middle, latest to `opening`, `mid`, `late`.
4. Use individual provider IDs for individual Kelly rows. Use `kelly-aggregate-max`, `kelly-aggregate-min`, and `kelly-aggregate-6avg` for maximum, minimum, and average rows. They are aggregates, not bookmakers.
5. Put unreadable values, unavailable markets, missing screenshots, or ambiguous dates in `missing_items`; do not fill them by inference. `source_screenshot` must equal an attached original filename.
6. Run `odds-journal journal market-archive preview --file DRAFT.yml` first. The command is read-only. Present its Markdown output to the user.
7. Only after an explicit archive request in the current user message, run:

```powershell
odds-journal journal market-archive archive --file DRAFT.yml --attachment SCREENSHOT.png --json
```

The result reports the journal target, attachment-hash mapping, snapshot count, and fields not converted to snapshots.

Minimal draft shape:

```yaml
schema_version: 1
fixture:
  competition: 芬兰超级联赛
  home_team: 塞伊奈约基
  away_team: 赫尔辛基
  kickoff_at: 2026-08-04T00:00:00+08:00
captured_at: 2026-08-03T13:13:06+08:00
screenshots: [handicap.png]
rows:
  - market: asian_handicap
    provider_id: bet365
    provider_name: 36*
    phase: opening
    raw_values: {home_water: "0.88", line: "-0/0.5", away_water: "0.93"}
    source_screenshot: handicap.png
    row_ordinal: 1
```
