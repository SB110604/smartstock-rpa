import math

import numpy as np
import pandas as pd
import pytest

from app.ml import classify, forecast, inventory


def test_z_safety_stock_rop_eoq():
    z = inventory.z_value(0.95)
    assert z == pytest.approx(1.6449, abs=1e-3)
    assert inventory.safety_stock(z, sigma_d=4, lead_days=4) == pytest.approx(1.6449 * 4 * 2, rel=1e-3)
    assert inventory.reorder_point(mean_daily=10, lead_days=4, ss=13.16) == pytest.approx(53.16)
    # EOQ = sqrt(2 × 3650 × 500 / (0.20 × 50)) = sqrt(365000) ≈ 604.15
    assert inventory.eoq(3650, 500, 0.2 * 50) == pytest.approx(math.sqrt(365000), rel=1e-6)
    assert inventory.eoq(0, 500, 10) == 0 and inventory.eoq(100, 500, 0) == 0
    assert inventory.safety_stock(z, sigma_d=-1, lead_days=4) == 0


def test_round_to_pack_and_moq():
    assert inventory.round_to_pack(101, 10, 0) == 110
    assert inventory.round_to_pack(100, 10, 0) == 100
    assert inventory.round_to_pack(3, 10, 25) == 25
    assert inventory.round_to_pack(0.2, 0, 1) == 1


def base_kwargs(**kw):
    args = {"mean_daily_lead": 10.0, "mean_daily_year": 10.0, "sigma_daily": 4.0, "lead_days": 4, "review_days": 7,
            "service_level": 0.95, "ordering_cost": 500, "holding_pct": 20, "unit_cost": 50, "on_hand": 18, "on_order": 0,
            "pack_size": 10, "min_order_qty": 10}
    args.update(kw)
    return args


def test_order_quantity_uses_max_of_eoq_and_need():
    c = inventory.order_quantity(**base_kwargs())
    # ROP = 40 + 1.645·4·2 = 53.2 ; need = 53.2 + 70 − 18 = 105.2 ; EOQ ≈ 604 → EOQ wins → rounded to 610
    assert c.should_order and c.reorder_point == pytest.approx(53.16, abs=0.05)
    assert c.need == pytest.approx(105.16, abs=0.05)
    assert c.order_qty == 610
    big = inventory.order_quantity(**base_kwargs(ordering_cost=1, unit_cost=1000))  # tiny EOQ → need wins
    assert big.eoq < big.need and big.order_qty == 110


def test_no_order_above_rop_or_without_demand():
    assert not inventory.order_quantity(**base_kwargs(on_hand=500)).should_order
    zero = inventory.order_quantity(**base_kwargs(mean_daily_lead=0, mean_daily_year=0, sigma_daily=0, on_hand=0))
    assert not zero.should_order and zero.order_qty == 0


def test_perishable_cap_and_correction_factor():
    c = inventory.order_quantity(**base_kwargs(perishable_shelf_days=3, pack_size=6, min_order_qty=6, on_hand=0))
    assert c.perishable_cap == pytest.approx(24)  # 10/day × 3 days × 0.8
    assert c.order_qty == 24  # capped, then rounded to the pack of 6
    up = inventory.order_quantity(**base_kwargs(ordering_cost=1, unit_cost=1000, correction_factor=1.3))
    assert up.raw_qty == pytest.approx(up.need * 1.3) and up.order_qty == 140


def test_reason_text_matches_spec_style():
    c = inventory.order_quantity(**base_kwargs(ordering_cost=1, unit_cost=1000))
    text = inventory.reason_text(c, "units", 110)
    assert text.startswith("Forecast 110 units over next 11 days (lead 4 + review 7).")
    assert "On hand 18, on order 0, safety stock 13." in text and "rounded to pack of 10" in text


def test_mape_ignores_zero_actual_days():
    assert forecast.mape(np.array([10, 0, 20]), np.array([12, 5, 10])) == pytest.approx((0.2 + 0.5) / 2 * 100)
    assert forecast.mape(np.array([0, 0]), np.array([1, 1])) is None
    assert forecast.rmse(np.array([1, 3]), np.array([1, 1])) == pytest.approx(math.sqrt(2))


def test_festival_features_identify_upcoming_festival():
    from datetime import date

    days = pd.date_range("2026-11-01", "2026-11-10")
    flag, days_to, fid = forecast._festival_features(days, [(date(2026, 11, 8), 3)])
    assert list(flag[:2]) == [0, 1] and days_to[7] == 0 and fid[7] == 3 and fid[0] == 0 and fid[-1] == 0


def test_abc_and_xyz():
    a = classify.abc({1: 700, 2: 150, 3: 80, 4: 50, 5: 20})
    assert a == {1: "A", 2: "B", 3: "B", 4: "C", 5: "C"}
    weekly = pd.DataFrame({1: [10, 10, 11, 9], 2: [10, 2, 18, 5], 3: [0, 0, 30, 0], 4: [0, 0, 0, 0]})
    assert classify.xyz(weekly) == {1: "X", 2: "Y", 3: "Z", 4: "Z"}
