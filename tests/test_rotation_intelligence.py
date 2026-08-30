from rotation_intelligence import build_rotation_intelligence, classify_divergence


def test_no_exact_flow_never_promotes_distribution_trap():
    out = classify_divergence(82, 35, flow_20d=None)
    assert out["state"] == "PRICE_INTERNAL_DIVERGENCE"
    assert out["confidence"] == "PARTIAL"
    assert out["state"] != "DISTRIBUTION_TRAP"


def test_exact_negative_flow_can_confirm_distribution_trap():
    out = classify_divergence(82, 35, flow_20d=-4_200_000_000, internal_complete=True)
    assert out["state"] == "DISTRIBUTION_TRAP"
    assert out["confidence"] == "FULL"


def test_exact_outflow_with_strong_internal_is_redemption_divergence():
    out = classify_divergence(74, 76, flow_20d=-623_000_000, internal_complete=True)
    assert out["state"] == "REDEMPTION_DIVERGENCE"


def test_exact_inflow_before_price_is_hidden_accumulation():
    out = classify_divergence(48, 72, flow_20d=878_000_000, internal_complete=True)
    assert out["state"] == "HIDDEN_ACCUMULATION"


def test_volume_quality_is_never_mislabelled_as_exact_etf_flow():
    details = {
        f"A{i}": {
            "sec": "Healthcare",
            "rs189": 90,
            "rs": 88,
            "v50": 1,
            "dma21": 0.03,
            "uvdv20": 1.8,
        }
        for i in range(4)
    }
    state = build_rotation_intelligence(details)
    assert state["fund_flow"]["status"] == "DATA_REQUIRED"
    assert state["groups"][0]["fund_flow"]["status"] == "DATA_REQUIRED"
    assert state["groups"][0]["fund_flow"]["flow_20d"] is None
    assert state["groups"][0]["fund_flow"]["volume_is_not_flow"] is True


def test_exact_flow_requires_explicit_exact_flag_and_normalizes_by_aum():
    details = {
        f"A{i}": {"sec": "Healthcare", "rs189": 90, "rs": 88, "v50": 1, "dma21": 0.03}
        for i in range(4)
    }
    not_exact = build_rotation_intelligence(
        details,
        exact_flows={"Healthcare": {"flow_20d": 100, "aum": 1000}},
    )
    assert not_exact["fund_flow"]["status"] == "DATA_REQUIRED"

    exact = build_rotation_intelligence(
        details,
        exact_flows={"Healthcare": {"flow_1d": 20, "flow_5d": 50, "flow_20d": 100,
                                      "aum": 1000, "source": "fixture", "exact": True}},
    )
    group = exact["groups"][0]
    assert group["fund_flow"]["status"] == "EXACT"
    assert group["fund_flow"]["flow_20d_pct_aum"] == 10.0
    assert exact["fund_flow"]["status"] == "EXACT"
