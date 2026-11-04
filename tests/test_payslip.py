"""Payslip (skattekort) calculator.

The official worked examples are pre-reform (2012/2013), so they test the two
skattekort formulas in isolation; 2026 behaviour is tested through invariants.
"""

from decimal import Decimal

import pytest

from dk_tax.calc.payslip import (
    bracket_component,
    estimate_payslip,
    maanedsfradrag,
    round_up_traekprocent,
    skattekort_fradrag,
)

AARHUS = Decimal("24.52")


def test_traekprocent_example_f02():
    """SKAT, Beregning af personlige indkomstskatter 2013, F.3.3.1, Eksempel F-02:
    bundskat 5,83 + sundhedsbidrag 6,00 + kommune 23,70 + kirke 0,62 = 36,15;
    topskat after skatteloft 6.647 x 100 / (460.000 + 10.000) = 1,41; 37,56 -> 38 %.
    """
    unrounded = Decimal("36.15") + bracket_component(Decimal(6647), Decimal(470_000))
    assert unrounded == Decimal("37.56")
    assert round_up_traekprocent(unrounded) == 38


def test_fradrag_example_f04():
    """SKAT, Beregning af personlige indkomstskatter 2012, F.3.3.3, Eksempel F-04:
    fradrag = 414.000 - (169.625,18 - 36.000) x 100 / 37,15 = 54.309,08; 4.525 per month.
    """
    fradrag = skattekort_fradrag(Decimal(414_000), Decimal("133625.18"), Decimal("37.15"))
    assert fradrag == Decimal("54309.08")
    assert maanedsfradrag(fradrag) == 4525


def test_2026_salary_only_withholding_matches_annual_tax():
    """With salary as the only income, a year of withholding equals the year's tax except for
    the over-withholding from rounding the trækprocent up: (rounded - unrounded) % of
    (A-income - fradrag). KSL-bekendtgørelsen §§ 9, 12."""
    p = estimate_payslip(2026, 60_000, kommuneskat=AARHUS, pension_own_pct=4, pension_employer_pct=8)
    expected_over = (p.traekprocent - p.traekprocent_uafrundet) / 100 * (p.a_indkomst_aar - p.fradrag_aar)
    assert p.year_end.restskat <= 0
    assert abs(-p.year_end.restskat - expected_over) < 50  # monthly fradrag is truncated to whole kroner


def test_normal_month_payslip_lines_add_up():
    p = estimate_payslip(2026, 60_000, kommuneskat=AARHUS, pension_own_pct=4, pension_employer_pct=8)
    m = p.normal_month
    assert m.pension_own == Decimal("2400.00")
    assert m.atp_own == 99
    assert m.am_bidrag == Decimal("0.08") * (60_000 - 2_400 - 99)
    assert m.a_skat == p.traekprocent / Decimal(100) * (60_000 - 2_400 - 99 - m.am_bidrag - p.maanedsfradrag)
    assert m.til_udbetaling == 60_000 - m.pension_own - m.atp_own - m.am_bidrag - m.a_skat


def test_bonus_left_out_of_forskud_gives_more_restskat():
    args = {"kommuneskat": AARHUS, "pension_own_pct": 4, "pension_employer_pct": 8, "bonus": 120_000}
    included = estimate_payslip(2026, 60_000, include_bonus_in_forskud=True, **args)
    left_out = estimate_payslip(2026, 60_000, include_bonus_in_forskud=False, **args)
    assert left_out.traekprocent <= included.traekprocent
    assert left_out.normal_month.til_udbetaling >= included.normal_month.til_udbetaling
    assert left_out.year_end.restskat > included.year_end.restskat


def test_shares_in_forskud_lower_normal_pay_and_avoid_restskat():
    """RSUs are B-income (no employer withholding). In the forskudsopgørelse they raise the
    forskudsskat, which shrinks the fradrag (KSL-bekendtgørelsen § 9) and lowers normal pay."""
    args = {"kommuneskat": AARHUS, "pension_own_pct": 4, "pension_employer_pct": 8, "share_compensation": 200_000}
    included = estimate_payslip(2026, 60_000, include_shares_in_forskud=True, **args)
    left_out = estimate_payslip(2026, 60_000, include_shares_in_forskud=False, **args)
    assert included.maanedsfradrag < left_out.maanedsfradrag
    assert included.normal_month.til_udbetaling < left_out.normal_month.til_udbetaling
    # 200.000 kr. of shares uses up the whole fradrag, so the percentage is raised (§ 12) to the
    # next whole percent that covers the forskudsskat: settled during the year, over-withholding
    # at most 1 percentage point of the A-income.
    assert included.fradrag_aar == 0 and included.traekprocent > left_out.traekprocent
    assert -included.a_indkomst_aar / 100 < included.year_end.restskat <= 0
    assert left_out.year_end.restskat > 90_000  # roughly the tax on 200.000 kr. of shares


def test_pre_reform_years_are_rejected():
    with pytest.raises(ValueError, match="2026"):
        estimate_payslip(2025, 60_000, kommuneskat=AARHUS)


def test_withhold_to_cover_shares_barely_touch_normal_pay():
    """Employer keeps back shares to cover tax at vest (withhold-to-cover). The vest is then
    A-income taxed in shares, so cash months change only through the skattekort. With the
    shares in the forskudsopgørelse, § 9 backs the fradrag out so that the year's withholding
    equals the year's tax: the marginal tax on the shares shows up as a smaller fradrag on
    the salary, and only the rounding-up over-withholding remains."""
    args = {"kommuneskat": AARHUS, "pension_own_pct": 4, "pension_employer_pct": 8, "share_compensation": 200_000}
    b_income = estimate_payslip(2026, 60_000, **args)  # share_withholding="none"
    cover = estimate_payslip(2026, 60_000, share_withholding="traekprocent", **args)
    no_shares = estimate_payslip(2026, 60_000, kommuneskat=AARHUS, pension_own_pct=4, pension_employer_pct=8)

    assert cover.normal_month.til_udbetaling > b_income.normal_month.til_udbetaling
    assert no_shares.normal_month.til_udbetaling - cover.normal_month.til_udbetaling < 1_500
    vest = cover.share_vest
    assert vest.per_vest == 50_000  # 200.000 over 4 quarterly vests
    assert vest.am_bidrag == 4_000
    assert vest.a_skat == cover.traekprocent / Decimal(100) * (50_000 - 4_000)
    assert cover.maanedsfradrag < no_shares.maanedsfradrag
    assert -cover.a_indkomst_aar / 100 < cover.year_end.restskat <= 0

    # Left out of the forskudsopgørelse, the vest is withheld at a trækprocent that knows
    # nothing about it, below the marginal rate: restskat remains.
    hidden = estimate_payslip(2026, 60_000, share_withholding="traekprocent", include_shares_in_forskud=False, **args)
    assert 0 < hidden.year_end.restskat < 200_000 * Decimal("0.20")


def test_withhold_to_cover_at_a_fixed_high_rate_leaves_less_restskat():
    args = {"kommuneskat": AARHUS, "pension_own_pct": 4, "pension_employer_pct": 8, "share_compensation": 200_000}
    at_traek = estimate_payslip(2026, 60_000, share_withholding="traekprocent", **args)
    at_56 = estimate_payslip(2026, 60_000, share_withholding="fixed", share_withholding_rate=56, **args)
    assert at_56.year_end.restskat < at_traek.year_end.restskat


def test_fixed_withholding_needs_a_rate():
    with pytest.raises(ValueError, match="share_withholding_rate"):
        estimate_payslip(2026, 60_000, kommuneskat=AARHUS, share_compensation=1, share_withholding="fixed")


def test_quarterly_bonus_same_year_total_as_one_payment():
    """A bonus split over 4 payments: each bonus month gets a quarter, and since every month's
    fradrag is used by the salary, the year's withholding is unchanged."""
    args = {"kommuneskat": AARHUS, "pension_own_pct": 4, "pension_employer_pct": 8, "bonus": 125_000}
    once = estimate_payslip(2026, 80_000, **args)
    quarterly = estimate_payslip(2026, 80_000, bonus_payments=4, **args)
    assert quarterly.bonus_month.gross == 80_000 + Decimal(125_000) / 4
    assert quarterly.year_end.withheld == once.year_end.withheld
    assert quarterly.normal_month == once.normal_month
