from institutional_risk_fleet.scenario import load_default_scenario


def test_frozen_scenario_is_deterministic_and_synthetic() -> None:
    first = load_default_scenario()
    second = load_default_scenario()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.synthetic
    assert all(item.synthetic for item in first.evidence)


def test_frozen_event_and_evidence_values() -> None:
    scenario = load_default_scenario()
    assert scenario.event.spread_move_bps == 90.0
    assert scenario.event.portfolio_exposure_usd == 75_000_000.0
    upstream = next(item for item in scenario.evidence if item.id == "evidence-upstream-001")
    filing = next(item for item in scenario.evidence if item.id == "evidence-filing-001")
    assert upstream.facts["fy2025_leverage"].value == 4.1
    assert filing.facts["fy2025_leverage"].value == 3.8


def test_frozen_provenance_ids_are_unique() -> None:
    scenario = load_default_scenario()
    ids = [scenario.event.id]
    ids.extend(item.id for item in scenario.positions)
    ids.extend(item.id for item in scenario.evidence)
    assert len(ids) == len(set(ids))
