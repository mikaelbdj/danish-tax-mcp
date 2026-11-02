"""Skattekort and monthly payslip for an employee, from a forskudsopgørelse.

Rules, with sources:
- Trækprocent (indeholdelsesprocent): BEK nr 1094 af 10/09/2025 § 6 (income year 2026):
  kommune + kirke + bundskat, plus mellemskat (after skatteloft), topskat and toptopskat,
  each without personfradrag, as a percentage of personlig indkomst (mellemskat: plus
  positive net capital income above its bundgrænse). Components above 0 only.
- Rounded up to a whole percent and capped: KSL-bekendtgørelsen (BEK nr 839 af 24/06/2025) § 12.
- Fradrag: KSL-bekendtgørelsen § 9: A-indkomst - forskudsskat x 100 / unrounded trækprocent,
  0 if negative. Forskudsskat excludes AM-bidrag withheld on A-income (§ 9, stk. 2).
- Monthly fradrag: proportional share of the yearly fradrag (KSL § 48, stk. 3).
- A-skat per payslip: trækprocent x (A-income after own pension, own ATP and AM-bidrag
  - månedsfradrag): KSL §§ 46, 48; eIndkomst felt 13 definition.
- Shares (RSU, LL § 16) are B-income: no withholding by the employer (skat.dk, 'Skat af
  aktieløn og medarbejderaktier'); if entered in the forskudsopgørelse they raise the
  forskudsskat and so shrink the fradrag.

Assumptions (not settled by current official text; from SKAT's pre-reform guide
'Beregning af personlige indkomstskatter', F.3.3.1-F.3.3.3):
- Each trækprocent component and the forskudsskat x 100 / % quotient are truncated to 2 decimals.
- The monthly fradrag is yearly fradrag / 12, truncated to whole kroner.
- No carry-forward of unused monthly fradrag; a bonus month gets one month's fradrag.
- Pension is paid on the monthly salary only, unless bonus_has_pension.
Payslip amounts are exact (no payroll rounding to 10 kr. as in JV A.B.4.1.1.2.6).
"""

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal

from pydantic import BaseModel

from dk_tax.calc.salary import REFORM_YEAR, FigureRef, estimate_salary_tax
from dk_tax.loader import load_year

Amount = int | Decimal


class MonthPayslip(BaseModel):
    gross: Decimal
    pension_own: Decimal
    atp_own: Decimal
    am_bidrag: Decimal
    a_skat: Decimal
    til_udbetaling: Decimal


class YearEnd(BaseModel):
    withheld: Decimal
    """AM-bidrag and A-skat withheld during the year, plus any B-skat on the forskudsopgørelse."""
    actual_tax: Decimal
    """The year's real tax (skat_i_alt) with all income, whether or not it was in the forskud."""
    restskat: Decimal
    """actual_tax - withheld: positive means tax to pay after the year, negative overskydende skat."""


class Payslip(BaseModel):
    year: int
    traekprocent: int
    traekprocent_uafrundet: Decimal
    fradrag_aar: Decimal
    maanedsfradrag: Decimal
    a_indkomst_aar: Decimal
    """Expected A-income after own pension, own ATP and AM-bidrag (the § 9 base)."""
    forskudsskat: Decimal
    """Expected tax excluding AM-bidrag on A-income."""
    b_skat_aar: Decimal
    """Forskudsskat the trækprocent cannot cover (paid as B-skat instalments)."""
    normal_month: MonthPayslip
    bonus_month: MonthPayslip | None
    year_end: YearEnd
    all_verified: bool
    sources: dict[str, FigureRef]


def _trunc2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_DOWN)


def bracket_component(tax: Decimal, base: Decimal) -> Decimal:
    """A bracket tax as percentage points of its base, truncated to 2 decimals."""
    return _trunc2(tax * 100 / base) if base > 0 else Decimal(0)


def round_up_traekprocent(unrounded: Decimal) -> int:
    return int(unrounded.quantize(Decimal(1), ROUND_CEILING))


def skattekort_fradrag(a_indkomst: Decimal, forskudsskat: Decimal, traekprocent_uafrundet: Decimal) -> Decimal:
    """KSL-bekendtgørelsen § 9: the yearly fradrag on the skattekort (may be negative; caller clamps)."""
    return a_indkomst - _trunc2(forskudsskat * 100 / traekprocent_uafrundet)


def maanedsfradrag(fradrag_aar: Decimal) -> Decimal:
    return (fradrag_aar / 12).quantize(Decimal(1), ROUND_DOWN)


def estimate_payslip(
    year: int,
    monthly_salary: Amount,
    *,
    kommuneskat: Amount,
    kirkeskat: Amount = 0,
    pension_own_pct: Amount = 0,
    pension_employer_pct: Amount = 0,
    bonus: Amount = 0,
    bonus_has_pension: bool = False,
    share_compensation: Amount = 0,
    include_bonus_in_forskud: bool = True,
    include_shares_in_forskud: bool = True,
    atp_full_time: bool = True,
    net_capital_income: Amount = 0,
    other_deductions: Amount = 0,
    within_15_years_of_pension: bool = False,
) -> Payslip:
    """Skattekort, a normal month's and a bonus month's payslip, and the year-end result.

    monthly_salary includes the employee's own pension share. Pension percentages are of
    monthly_salary. bonus is paid in one month. share_compensation is the year's RSU vest value.
    The include_* flags say what is entered in the forskudsopgørelse; the year-end result
    always uses all income.
    """
    if year < REFORM_YEAR:
        raise ValueError(f"Payslip rules are implemented from income year {REFORM_YEAR}")
    D = lambda x: Decimal(str(x))  # noqa: E731
    figures = load_year(year)
    salary, bonus_ = D(monthly_salary), D(bonus)
    own_pct, emp_pct = D(pension_own_pct) / 100, D(pension_employer_pct) / 100
    pensionable_bonus = bonus_ if bonus_has_pension else Decimal(0)

    def year_tax(with_bonus: bool, with_shares: bool):
        b = bonus_ if with_bonus else Decimal(0)
        pb = pensionable_bonus if with_bonus else Decimal(0)
        return estimate_salary_tax(
            year,
            12 * salary + b,
            kommuneskat=kommuneskat,
            kirkeskat=kirkeskat,
            atp_full_time=atp_full_time,
            pension_own=own_pct * (12 * salary + pb),
            pension_employer=emp_pct * (12 * salary + pb),
            share_compensation=share_compensation if with_shares else 0,
            net_capital_income=net_capital_income,
            other_deductions=other_deductions,
            within_15_years_of_pension=within_15_years_of_pension,
        )

    forskud = year_tax(include_bonus_in_forskud, include_shares_in_forskud)
    actual = year_tax(True, True)

    # Trækprocent (BEK 1094/2025 § 6)
    used = ["bundskat", "mellemskat_kapitalindkomst_bundfradrag", "skatteloft", "topskat"]
    pi = forskud.personlig_indkomst
    kapital_over = max(Decimal(0), D(net_capital_income) - figures["mellemskat_kapitalindkomst_bundfradrag"].value)
    components = [
        D(kommuneskat) + D(kirkeskat) + figures["bundskat"].value,
        bracket_component(forskud.mellemskat, pi + kapital_over),
        bracket_component(forskud.topskat, pi),
        bracket_component(forskud.toptopskat, pi),
    ]
    unrounded = sum(c for c in components if c > 0)
    traek = round_up_traekprocent(unrounded)

    # Fradrag (KSL-bek. § 9) and, if it would be negative, a higher percentage up to the cap (§ 12)
    a_aar = forskud.am_bidrag_grundlag - forskud.am_bidrag
    forskudsskat = forskud.skat_i_alt - forskud.am_bidrag
    fradrag = skattekort_fradrag(a_aar, forskudsskat, unrounded)
    b_skat = Decimal(0)
    if fradrag < 0:
        fradrag = Decimal(0)
        cap = figures["skatteloft"].value + figures["topskat"].value + D(kirkeskat)
        needed = round_up_traekprocent(forskudsskat * 100 / a_aar) if a_aar > 0 else traek
        traek = min(max(traek, needed), int(cap.quantize(Decimal(1), ROUND_FLOOR)))
        b_skat = max(Decimal(0), forskudsskat - traek * a_aar / 100)
    m_fradrag = maanedsfradrag(fradrag)

    # Payslips
    am_rate = figures["am_bidrag"].rate()
    atp = figures["atp_loenmodtager_maaned"].value if atp_full_time else Decimal(0)
    if atp_full_time:
        used.append("atp_loenmodtager_maaned")

    def month(gross: Decimal, pensionable: Decimal) -> MonthPayslip:
        pension = own_pct * pensionable
        am = am_rate * (gross - pension - atp)
        a_skat = Decimal(traek) / 100 * max(Decimal(0), gross - pension - atp - am - m_fradrag)
        return MonthPayslip(
            gross=gross,
            pension_own=pension,
            atp_own=atp,
            am_bidrag=am,
            a_skat=a_skat,
            til_udbetaling=gross - pension - atp - am - a_skat,
        )

    normal = month(salary, salary)
    bonus_month = month(salary + bonus_, salary + pensionable_bonus) if bonus_ else None
    withheld_months = [normal] * (11 if bonus_month else 12) + ([bonus_month] if bonus_month else [])
    withheld = sum((m.am_bidrag + m.a_skat for m in withheld_months), Decimal(0)) + b_skat

    sources = {**forskud.sources, **actual.sources}
    for key in used:
        f = figures[key]
        sources[key] = FigureRef(source=f.source, verified=f.verified, status=f.status)
    return Payslip(
        year=year,
        traekprocent=traek,
        traekprocent_uafrundet=unrounded,
        fradrag_aar=fradrag,
        maanedsfradrag=m_fradrag,
        a_indkomst_aar=a_aar,
        forskudsskat=forskudsskat,
        b_skat_aar=b_skat,
        normal_month=normal,
        bonus_month=bonus_month,
        year_end=YearEnd(withheld=withheld, actual_tax=actual.skat_i_alt, restskat=actual.skat_i_alt - withheld),
        all_verified=all(ref.status == "verified" for ref in sources.values()),
        sources=sources,
    )
