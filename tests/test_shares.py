"""Aktieindkomst (PSL §§ 4 a, 8 a; ABL §§ 13, 13 A) for one person.

Official arithmetic: JV C.E.3.2.4.1.2 (2026-2), examples 1 and 3, use the 2026 grænse 79.400
(the section is about estates, but the § 8 a split is the same). The rest are hand
calculations from the rules quoted in each test.
"""

from decimal import Decimal

import pytest

from dk_tax.calc.shares import estimate_share_income_tax


def test_jv_example_3_negative_aktieindkomst():
    """JV C.E.3.2.4.1.2, eksempel 3: aktieindkomst -150.000 kr. (2026).
    27 % x 79.400 = 21.438; 42 % x (150.000 - 79.400) = 29.652; negative tax 51.090.
    Credited in the slutskat, at most the slutskat (§ 8 a, stk. 5)."""
    r = estimate_share_income_tax(2026, oevrig_aktieindkomst=-150_000, oevrig_slutskat=100_000)
    assert r.aktieindkomst == -150_000
    assert r.skat == 0
    assert r.negativ_skat == Decimal("51090.00")
    assert r.negativ_skat_anvendt == Decimal("51090.00")
    assert r.negativ_skat_fremfoert_naeste_aar == 0
    assert r.netto == Decimal("-51090.00")
    assert r.all_verified


def test_jv_example_1_arithmetic_above_the_graense():
    """JV C.E.3.2.4.1.2, eksempel 1: a base of 215.000 kr. gives 21.438 + 56.952 = 78.390."""
    r = estimate_share_income_tax(2026, boersnoteret_udbytte_gevinst=215_000)
    assert r.skat == Decimal("78390.00")
    assert {"aktieindkomst_lav_sats", "aktieindkomst_hoej_sats", "aktieindkomst_progressionsgraense"} <= set(r.sources)


def test_skat_skole_example_below_the_graense():
    """skat.dk/skole/investering/aktiehandel: 200 kr. dividend + 1.000 kr. gain = 1.200 kr. at 27 %."""
    r = estimate_share_income_tax(2026, boersnoteret_udbytte_gevinst=1_200)
    assert r.skat == Decimal("324.00")


def test_2027_uses_the_2027_graense():
    """svmn.dk: 89.600 kr. in 2027. 27 % x 89.600 = 24.192; 42 % x 10.400 = 4.368."""
    r = estimate_share_income_tax(2027, boersnoteret_udbytte_gevinst=100_000)
    assert r.progressionsgraense == 89_600
    assert r.skat == Decimal("28560.00")


def test_withheld_udbytteskat_is_credited():
    """§ 8 a, stk. 1-3: 100.000 kr. Danish dividends, 27.000 withheld. Tax 21.438 + 42 % x 20.600
    = 30.090; the withholding is final up to the grænse and credited above it, so 3.090 is left."""
    r = estimate_share_income_tax(2026, boersnoteret_udbytte_gevinst=100_000, udbytteskat_indeholdt=27_000)
    assert r.skat == Decimal("30090.00")
    assert r.netto == Decimal("3090.00")


def test_listed_loss_only_offsets_listed_income_and_carries_forward_as_a_loss():
    """ABL § 13 A (JV C.B.2.2.1.4): the year's loss first, then older losses; the rest is
    carried forward as a loss, not as negative tax. 50.000 - 80.000 - 10.000 -> 0, carry 40.000."""
    r = estimate_share_income_tax(
        2026, boersnoteret_udbytte_gevinst=50_000, boersnoteret_tab=80_000, boersnoteret_tab_fremfoert=10_000
    )
    assert r.aktieindkomst == 0
    assert r.negativ_skat == 0
    assert r.boersnoteret_tab_fremfoert_naeste_aar == 40_000


def test_carried_forward_listed_loss_is_used_up_first_possible_year():
    r = estimate_share_income_tax(
        2026, boersnoteret_udbytte_gevinst=50_000, boersnoteret_tab=20_000, boersnoteret_tab_fremfoert=10_000
    )
    assert r.aktieindkomst == 20_000
    assert r.boersnoteret_tab_fremfoert_naeste_aar == 0


def test_listed_loss_does_not_offset_unlisted_gains():
    """JV C.B.2.2.1.4: a listed loss cannot be set against gains on unlisted shares."""
    r = estimate_share_income_tax(2026, boersnoteret_tab=30_000, oevrig_aktieindkomst=40_000)
    assert r.aktieindkomst == 40_000
    assert r.boersnoteret_tab_fremfoert_naeste_aar == 30_000


def test_unlisted_loss_offsets_listed_gains():
    """ABL § 13, stk. 1, PSL § 4 a, stk. 1, nr. 4: an unlisted loss is part of aktieindkomst."""
    r = estimate_share_income_tax(2026, boersnoteret_udbytte_gevinst=50_000, oevrig_aktieindkomst=-20_000)
    assert r.aktieindkomst == 30_000


def test_negative_tax_beyond_the_slutskat_carries_forward():
    """§ 8 a, stk. 5: 51.090 negative tax, 30.000 slutskat: 30.000 used, 21.090 carried forward."""
    r = estimate_share_income_tax(2026, oevrig_aktieindkomst=-150_000, oevrig_slutskat=30_000)
    assert r.negativ_skat_anvendt == 30_000
    assert r.negativ_skat_fremfoert_naeste_aar == Decimal("21090.00")
    assert not r.slutskat_ukendt


def test_carried_forward_negative_tax_offsets_this_years_share_tax():
    """§ 8 a, stk. 5, 2. pkt.: carried-forward negative tax is credited in later years' slutskat.
    Assumption: the share tax not covered by withheld udbytteskat is part of that slutskat.
    Tax on 100.000 = 30.090, no other slutskat: 30.090 of 40.000 used, 9.910 carried on."""
    r = estimate_share_income_tax(
        2026, boersnoteret_udbytte_gevinst=100_000, negativ_skat_fremfoert=40_000, oevrig_slutskat=0
    )
    assert r.negativ_skat_anvendt == Decimal("30090.00")
    assert r.negativ_skat_fremfoert_naeste_aar == Decimal("9910.00")
    assert r.netto == 0


def test_unknown_slutskat_assumes_the_negative_tax_is_used_and_flags_it():
    r = estimate_share_income_tax(2026, oevrig_aktieindkomst=-150_000)
    assert r.negativ_skat_anvendt == Decimal("51090.00")
    assert r.slutskat_ukendt


def test_amounts_that_cannot_be_negative_are_rejected():
    with pytest.raises(ValueError, match="boersnoteret_tab"):
        estimate_share_income_tax(2026, boersnoteret_tab=-1)
