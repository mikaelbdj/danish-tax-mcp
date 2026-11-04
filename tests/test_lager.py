"""Lagerbeskatning of investeringsselskaber for a person (ABL §§ 19 B, 19 C, 23, stk. 2 and 8).

Hand calculations from the law: § 23, stk. 8 makes the lagerprincip mandatory for
investeringsselskaber; stk. 2 defines it (end value - start value, with the purchase price
for what was bought and the sale price for what was sold in the year). JV C.B.4.3.2
(2026-2): § 19 B gains and losses are aktieindkomst, losses deductible without limitation;
§ 19 C (obligationsbaserede) is kapitalindkomst (PSL § 4 a, stk. 2).
"""

from decimal import Decimal

import pytest

from dk_tax.calc.lager import Fund, estimate_lager_gains


def fund(**kw):
    return Fund(**{"name": "Fund", "aktiebaseret": True, **kw})


def test_held_all_year():
    r = estimate_lager_gains(2026, [fund(value_start=100_000, value_end=120_000)])
    assert r.funds[0].gevinst == 20_000


def test_bought_in_the_year_uses_the_purchase_price():
    """§ 23, stk. 2, 3. pkt.: anskaffelsessummen instead of the start value."""
    r = estimate_lager_gains(2026, [fund(purchases=50_000, value_end=55_000)])
    assert r.funds[0].gevinst == 5_000


def test_sold_in_the_year_uses_the_sale_price():
    """§ 23, stk. 2, 4. pkt.: afståelsessummen instead of the end value."""
    r = estimate_lager_gains(2026, [fund(value_start=80_000, sales=90_000)])
    assert r.funds[0].gevinst == 10_000


def test_ledger_formula_equals_the_law_lot_by_lot():
    """One fund: a lot held all year (100 -> 110), a lot bought (50 -> 52) and a lot sold
    (start 30, sold for 33). Lot by lot: 10 + 2 + 3 = 15. Ledger: end 162 + sales 33 -
    start 130 - purchases 50 = 15."""
    r = estimate_lager_gains(2026, [fund(value_start=130, value_end=162, purchases=50, sales=33)])
    assert r.funds[0].gevinst == 15


def test_aktiebaseret_and_obligationsbaseret_are_split():
    r = estimate_lager_gains(
        2026,
        [
            fund(name="ETF A", value_start=100_000, value_end=130_000),
            fund(name="ETF B", value_start=50_000, value_end=40_000),
            fund(name="Bond fund", aktiebaseret=False, value_start=60_000, value_end=62_000),
        ],
    )
    assert r.aktieindkomst == 20_000  # 30.000 - 10.000: § 19 B gains and losses net
    assert r.kapitalindkomst == 2_000
    assert r.til_estimate_share_income_tax == {"boersnoteret_udbytte_gevinst": Decimal(20_000)}
    assert r.til_net_capital_income == 2_000


def test_net_aktiebaseret_loss_is_unrestricted():
    """JV C.B.4.3.2: losses on § 19 B funds are deducted 'uden begrænsninger', so a net loss
    goes to oevrig_aktieindkomst (it can give negative tax), not to the restricted
    boersnoteret_tab for listed shares (ABL § 13 A)."""
    r = estimate_lager_gains(2026, [fund(value_start=100_000, value_end=70_000)])
    assert r.aktieindkomst == -30_000
    assert r.til_estimate_share_income_tax == {"oevrig_aktieindkomst": Decimal(-30_000)}


def test_negative_amounts_are_rejected():
    with pytest.raises(ValueError, match="value_end"):
        estimate_lager_gains(2026, [fund(value_end=-1)])
