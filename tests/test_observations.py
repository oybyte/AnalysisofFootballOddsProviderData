from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from odds_journal.analytics import analytics_status, build_analytics, validate_analytics
from odds_journal.ledger import append_payloads, sha256_json
from odds_journal.markdown import MatchDocument
from odds_journal.models import MarketSnapshot
from odds_journal.observations import (
    MatchDataBundleV1,
    SourceKind,
    TimePrecision,
    backfill_legacy_snapshots,
    conflict_report,
    finish_bundle,
    ingest_bundle,
    market_feature_snapshot,
    observation_status,
    prepare_bundle,
    resolve_market_conflict,
    validate_observations,
)
from odds_journal.services import create_match


TZ = ZoneInfo("Asia/Shanghai")
KICKOFF = datetime(2026, 8, 4, 8, 0, tzinfo=TZ)


def _match(project_root: Path) -> Path:
    return create_match(
        project_root,
        kickoff=KICKOFF,
        timezone="Asia/Shanghai",
        competition_code="competition-u-5301467cd3",
        competition="巴西杯",
        home_team_id="team-u-437644d1fb",
        home_team="巴拉纳竞技",
        away_team_id="vitoria",
        away_team="维多利亚",
        schema_version=2,
    )


def _bundle(bundle_id: str = "parana-vitoria-full") -> MatchDataBundleV1:
    return MatchDataBundleV1.model_validate({
        "schema_version": 1,
        "bundle_id": bundle_id,
        "fixture": {
            "competition_code": "competition-u-5301467cd3",
            "competition": "巴西杯",
            "home_team": "巴拉纳竞技",
            "away_team": "维多利亚",
            "kickoff_at": KICKOFF.isoformat(),
            "timezone": "Asia/Shanghai",
            "venue": "拜沙达竞技场",
            "weather": "微雨 18℃~19℃",
        },
        "market_data": {
            "source_kind": "user_confirmed_text",
            "capture_batch_id": bundle_id,
            "macau_handicap_timeline": [
                {"displayed_at": "07-29 21:03", "home_water": "0.78", "line": "0.5/1", "away_water": "1.00"},
                {"displayed_at": "07-29 22:23", "home_water": "0.76", "line": "0.5/1", "away_water": "1.02"},
                {"displayed_at": "08-02 12:50", "home_water": "0.90", "line": "1", "away_water": "0.88"},
                {"displayed_at": "08-03 10:28", "home_water": "1.02", "line": "1", "away_water": "0.76"},
                {"displayed_at": "08-03 21:26", "home_water": "0.82", "line": "0.5/1", "away_water": "0.96"},
            ],
            "handicap_summary": [{
                "provider_name": "澳*",
                "opening": {"home": "0.78", "line": "0.5/1", "away": "1.00"},
                "current": {"home": "0.80", "line": "0.5/1", "away": "0.96"},
            }],
            "european_odds_summary": [{
                "provider_name": "36*",
                "opening_status": "not_displayed",
                "current": {"home": "1.67", "draw": "3.50", "away": "5.75"},
            }],
            "total_goals_summary": [{
                "provider_name": "澳*",
                "opening": {"over": "0.81", "line": "2/2.5", "under": "0.91"},
                "current": {"over": "0.84", "line": "2", "under": "0.88"},
            }],
            "kelly_summary": [{
                "provider_name": "6家平均",
                "opening": {"home": "0.99", "draw": "0.92", "away": "0.73"},
                "current": {"home": "0.94", "draw": "0.92", "away": "0.91"},
            }],
        },
        "result": {
            "status": "confirmed",
            "halftime_score": "1-0",
            "final_score": "2-0",
            "observed_at": "2026-08-04T10:00:00+08:00",
        },
    })


def test_five_exact_nodes_and_same_line_series_are_preserved(project_root: Path) -> None:
    path = _match(project_root)
    bundle = _bundle()
    result = ingest_bundle(
        project_root, bundle, match_path=path,
        received_at=datetime(2026, 8, 3, 22, 0, tzinfo=TZ),
    )
    assert result.observations_added == 13
    feature = market_feature_snapshot(project_root, MatchDocument.load(path).metadata.match_id, KICKOFF)
    macau = next(item for item in feature["series"] if item["provider_id"] == "macau" and item["market"] == "asian_handicap")
    assert macau["line_path"] == [0.75, 0.75, 1.0, 1.0, 0.75]
    same_lines = {item["line"]: item for item in macau["same_line_series"]}
    assert same_lines[0.75]["prices"]["home"] == [0.78, 0.76, 0.82]
    assert same_lines[1.0]["prices"]["home"] == [0.9, 1.02]
    assert feature["time_precision_counts"] == {"exact": 5, "phase_only": 8, "unknown": 0}


def test_duplicate_source_link_conflict_and_equal_value_at_new_time(project_root: Path) -> None:
    path = _match(project_root)
    first = _bundle("batch-one")
    received = datetime(2026, 8, 3, 22, 0, tzinfo=TZ)
    ingest_bundle(project_root, first, match_path=path, received_at=received)

    duplicate = _bundle("batch-two")
    duplicate.market_data.capture_batch_id = "batch-one"
    result = ingest_bundle(project_root, duplicate, match_path=path, received_at=received)
    assert result.observations_added == 0
    assert result.source_links_added > 0

    conflicting = _bundle("batch-conflict")
    conflicting.market_data.macau_handicap_timeline[0].home_water = "0.79"
    conflict_result = ingest_bundle(project_root, conflicting, match_path=path, received_at=received)
    assert conflict_result.conflicts_added == 1
    assert len(conflict_report(project_root, match_id=MatchDocument.load(path).metadata.match_id)) == 1

    later = _bundle("batch-later")
    later.market_data.macau_handicap_timeline = [
        later.market_data.macau_handicap_timeline[0].model_copy(update={"displayed_at": "07-29 21:04"})
    ]
    later.market_data.handicap_summary = []
    later.market_data.european_odds_summary = []
    later.market_data.total_goals_summary = []
    later.market_data.kelly_summary = []
    later_result = ingest_bundle(project_root, later, match_path=path, received_at=received)
    assert later_result.observations_added == 1

    group = conflict_report(project_root, match_id=MatchDocument.load(path).metadata.match_id)[0]
    selected = next(
        item["observation_id"] for item in group["observations"]
        if item["normalized_prices"]["home"] == 0.78
    )
    resolved = resolve_market_conflict(
        project_root,
        conflict_group_id=group["conflict_group_id"],
        status="confirmed_source",
        selected_observation_id=selected,
        reason="原始行哈希与首份材料一致",
        actor="lcz",
    )
    assert resolved["status"] == "confirmed_source"


def test_equal_degraded_endpoints_do_not_claim_full_stability(project_root: Path) -> None:
    path = _match(project_root)
    bundle = _bundle("equal-endpoints")
    bundle.market_data.macau_handicap_timeline = []
    bundle.market_data.handicap_summary[0].current = bundle.market_data.handicap_summary[0].opening.model_copy()
    bundle.market_data.european_odds_summary = []
    bundle.market_data.total_goals_summary = []
    bundle.market_data.kelly_summary = []
    ingest_bundle(
        project_root, bundle, match_path=path,
        received_at=datetime(2026, 8, 3, 22, 0, tzinfo=TZ),
    )
    feature = market_feature_snapshot(project_root, MatchDocument.load(path).metadata.match_id, KICKOFF)
    endpoint = feature["phase_only_series"][0]
    assert endpoint["endpoint_change"] == 0
    assert endpoint["endpoint_values_equal"] is True
    assert endpoint["intermediate_path_status"] == "unknown"
    assert endpoint["stable_throughout"] == "unverified"


def test_finish_bundle_archives_and_normalizes_without_inventing_lock(project_root: Path) -> None:
    path = _match(project_root)
    bundle = _bundle("finish-bundle")
    bundle_file = project_root / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
    payload = finish_bundle(
        project_root, bundle_file, bundle, match_path=path,
        received_at=datetime(2026, 8, 4, 11, 0, tzinfo=TZ),
    )
    document = MatchDocument.load(path)
    assert str(document.metadata.status) in {"draft", "tracking"}
    assert document.metadata.locked_at is None
    assert document.metadata.settlement is None
    assert payload["result_lifecycle"] == {"status": "archived_only", "reason": "missing_valid_prematch_lock"}
    assert (project_root / payload["archive_path"]).read_bytes() == bundle_file.read_bytes()
    repeated = finish_bundle(
        project_root, bundle_file, bundle, match_path=path,
        received_at=datetime(2026, 8, 4, 11, 0, tzinfo=TZ),
    )
    assert repeated["normalization"]["observations_added"] == 0
    assert validate_observations(project_root) == []


def test_analytics_v3_projects_observation_ledgers(project_root: Path) -> None:
    path = _match(project_root)
    ingest_bundle(
        project_root, _bundle(), match_path=path,
        received_at=datetime(2026, 8, 3, 22, 0, tzinfo=TZ),
    )
    built = build_analytics(project_root)
    assert built["rebuilt"] is True
    assert validate_analytics(project_root) == []
    status = analytics_status(project_root)
    assert status["counts"]["market_observations"] == 13
    assert status["counts"]["match_result_observations"] == 2
    assert status["counts"]["match_result_sources"] == 2
    assert observation_status(project_root, match_id=MatchDocument.load(path).metadata.match_id)["observations"] == 13


def test_legacy_backfill_reuses_same_time_same_value_observations(project_root: Path) -> None:
    path = _match(project_root)
    ingest_bundle(
        project_root, _bundle(), match_path=path,
        received_at=datetime(2026, 8, 3, 22, 0, tzinfo=TZ),
    )
    result = backfill_legacy_snapshots(
        project_root,
        match_id=MatchDocument.load(path).metadata.match_id,
        max_matches=1,
        max_observations=5000,
    )
    assert result["snapshots"] == 5
    assert result["added"] == 0


def test_legacy_static_endpoints_are_phase_only(project_root: Path) -> None:
    path = _match(project_root)
    document = MatchDocument.load(path)
    captured_at = datetime(2026, 8, 3, 20, 0, tzinfo=TZ)
    document.metadata.market_snapshots = [
        MarketSnapshot.model_validate({
            "snapshot_id": "legacy-opening", "market": "total_goals", "phase": "opening",
            "captured_at": captured_at.isoformat(), "provider_id": "macau", "source_ref": "legacy:test/opening",
            "odds_format": "hong_kong", "raw_values": {"line": "2.5", "over_water": "0.80", "under_water": "0.90"},
            "normalized_values": {"line": 2.5, "over_water": 0.8, "under_water": 0.9},
        }),
        MarketSnapshot.model_validate({
            "snapshot_id": "legacy-late", "market": "total_goals", "phase": "late",
            "captured_at": captured_at.isoformat(), "provider_id": "macau", "source_ref": "legacy:test/late",
            "odds_format": "hong_kong", "raw_values": {"line": "2.5", "over_water": "0.90", "under_water": "0.80"},
            "normalized_values": {"line": 2.5, "over_water": 0.9, "under_water": 0.8},
        }),
    ]
    document.save()

    result = backfill_legacy_snapshots(project_root, match_id=document.metadata.match_id, max_matches=1)
    assert result == {"matches": 1, "snapshots": 2, "added": 2}
    status = observation_status(project_root, match_id=document.metadata.match_id)
    assert status["dispositions"]["phase_only"] == 2
    assert conflict_report(project_root, match_id=document.metadata.match_id) == []


def test_legacy_backfill_append_only_corrects_static_exact_events(project_root: Path) -> None:
    path = _match(project_root)
    document = MatchDocument.load(path)
    captured_at = datetime(2026, 8, 3, 20, 0, tzinfo=TZ)
    document.metadata.market_snapshots = [
        MarketSnapshot.model_validate({
            "snapshot_id": "legacy-opening", "market": "total_goals", "phase": "opening",
            "captured_at": captured_at.isoformat(), "provider_id": "macau", "source_ref": "legacy:test/opening",
            "odds_format": "hong_kong", "raw_values": {"line": "2.5", "over_water": "0.80", "under_water": "0.90"},
            "normalized_values": {"line": 2.5, "over_water": 0.8, "under_water": 0.9},
        }),
        MarketSnapshot.model_validate({
            "snapshot_id": "legacy-late", "market": "total_goals", "phase": "late",
            "captured_at": captured_at.isoformat(), "provider_id": "macau", "source_ref": "legacy:test/late",
            "odds_format": "hong_kong", "raw_values": {"line": "2.5", "over_water": "0.90", "under_water": "0.80"},
            "normalized_values": {"line": 2.5, "over_water": 0.9, "under_water": 0.8},
        }),
    ]
    document.save()
    payloads = []
    for phase, snapshot_id, source_ref, over, under in (
        ("opening", "legacy-opening", "legacy:test/opening", 0.8, 0.9),
        ("late", "legacy-late", "legacy:test/late", 0.9, 0.8),
    ):
        payloads.append({
            "schema_version": 1, "event_type": "recorded", "observation_id": f"bad-exact-{phase}",
            "match_id": document.metadata.match_id, "source_kind": SourceKind.LEGACY_SNAPSHOT.value,
            "source_ref": source_ref, "source_sha256": sha256_json([source_ref, snapshot_id]),
            "source_line_start": None, "source_line_end": None, "received_at": captured_at.isoformat(),
            "source_captured_at": captured_at.isoformat(), "time_precision": TimePrecision.EXACT.value,
            "observed_at": captured_at.isoformat(), "phase_hint": phase, "display_status": None,
            "capture_batch_id": f"legacy-{document.metadata.match_id}", "sequence_no": None,
            "provider_id": "macau", "provider_name_raw": "macau", "market": "total_goals",
            "market_scope": "full_time", "quote_role": "main_line", "odds_format": "hong_kong",
            "raw_values": {"line": "2.5", "over_water": str(over), "under_water": str(under)},
            "normalized_line": 2.5, "normalized_prices": {"over": over, "under": under},
            "availability_status": "available", "normalization_eligible": True, "prediction_eligible": True,
            "retrospective_validation_eligible": "ineligible", "ineligibility_reasons": [],
            "possible_duplicate_of": None, "conflict_group_id": None, "conflict_status": None,
        })
    ledger = project_root / "knowledge/market-observations/events.jsonl"
    append_payloads(
        ledger, payloads, recorded_at=captured_at, actor="migration",
        event_id_factory=lambda item, _: f"market-observation:{item['observation_id']}",
    )

    result = backfill_legacy_snapshots(project_root, match_id=document.metadata.match_id, max_matches=1)
    assert result == {"matches": 1, "snapshots": 2, "added": 2}
    assert observation_status(project_root, match_id=document.metadata.match_id)["dispositions"]["phase_only"] == 2
    assert conflict_report(project_root, match_id=document.metadata.match_id) == []
    assert backfill_legacy_snapshots(project_root, match_id=document.metadata.match_id, max_matches=1)["added"] == 0


def test_legacy_backfill_preserves_incomplete_snapshot_as_ineligible_coverage(project_root: Path) -> None:
    path = _match(project_root)
    document = MatchDocument.load(path)
    document.metadata.market_snapshots = [MarketSnapshot.model_validate({
        "snapshot_id": "legacy-incomplete", "market": "asian_handicap", "phase": "opening",
        "captured_at": "2026-08-03T20:00:00+08:00", "provider_id": "macau", "source_ref": "legacy:test/incomplete",
        "odds_format": "hong_kong", "raw_values": {"line": "0.5", "home_water": "0.80"},
        "normalized_values": {"home_line": 0.5, "home_water": 0.8},
    })]
    document.save()

    backfill_legacy_snapshots(project_root, match_id=document.metadata.match_id, max_matches=1)
    events = (project_root / "knowledge/market-observations/events.jsonl").read_text(encoding="utf-8")
    assert "legacy_snapshot_missing_normalized_prices:away" in events
    status = observation_status(project_root, match_id=document.metadata.match_id)
    assert status["dispositions"]["prediction_ineligible"] == 1
