"""Income tax for an unmarried employee (lønmodtager) for one income year.

Rules, with sources (see also tests/test_salary.py):
- AM-bidrag: AMBL §§ 1-2. Employer-administered pension (own + employer share) and
  own ATP are kept out of the AM-bidrag base on the salary; the pension company
  withholds AM-bidrag on the pension instead (JV C.A.12.2, A.B.4.1.1.1.4).
- Personlig indkomst: PSL § 3. Skattepligtig indkomst: PSL §§ 1-2.
- Beskæftigelsesfradrag, jobfradrag, ekstra pensionsfradrag: LL §§ 9 J, 9 K, 9 L.
  Ligningsmæssige fradrag, so they reduce only the kommune/kirke base.
- Personfradrag applied as a tax value per tax: PSL §§ 9-12.
- Kompensation for negative nettokapitalindkomst: PSL § 11.
- Brackets: up to 2025 topskat 15 % (old PSL § 7); from 2026 mellemskat, topskat
  and toptopskat (PSL §§ 7, 7 a, 8 as amended by lov nr. 482 af 22/05/2024).
- Skatteloft: PSL § 19. Kommuneskat + bundskat + the capped bracket (topskat up
  to 2025, mellemskat from 2026) may not exceed the loft; the excess percentage
  points are cut from that bracket. Kirkeskat is not part of the sum.

Assumptions (the law does not settle these; we follow svmn.dk's official
2023 example):
- Income amounts and deductions are rounded to whole kroner; taxes are kept
  exact and the total is rounded to øre once.
- ATP (own + employer) counts in the ekstra pensionsfradrag base, less AM-bidrag.

Not covered: married couples (transfers between spouses), unused personfradrag
carried to other taxes, aktieindkomst, ejendomsværdiskat, under-18 and senior rules.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from dk_tax.loader import Figure, Status, load_year

REFORM_YEAR = 2026  # first year with mellemskat/topskat/toptopskat
MARGINAL_STEP = Decimal(1000)  # marginalskat: tax on the next 1.000 kr. of salary

Amount = int | Decimal


class FigureRef(BaseModel):
    """The evidence for one figure used in a calculation."""

    source: str
    verified: date
    status: Status


class SalaryTax(BaseModel):
    """Breakdown of the calculation. Kroner; taxes rounded to øre for display."""

    year: int
    am_bidrag_grundlag: Decimal
    am_bidrag: Decimal
    personlig_indkomst: Decimal
    beskaeftigelsesfradrag: Decimal
    jobfradrag: Decimal
    ekstra_pensionsfradrag: Decimal
    ligningsmaessige_fradrag: Decimal
    skattepligtig_indkomst: Decimal
    kommune_og_kirkeskat: Decimal
    kompensation: Decimal
    bundskat: Decimal
    mellemskat: Decimal
    topskat: Decimal
    toptopskat: Decimal
    indkomstskat: Decimal
    skat_i_alt: Decimal
    """indkomstskat + AM-bidrag on the salary (AM-bidrag on pension is paid from the pension)."""
    til_udbetaling: Decimal
    """Salary paid out: gross_salary - pension_own - atp_own - skat_i_alt."""
    effektiv_skatteprocent: Decimal
    """skat_i_alt as a percentage of gross_salary."""
    marginalskat: Decimal | None = None
    """Percentage of the next 1.000 kr. of gross salary that goes to skat_i_alt (pension unchanged)."""
    all_verified: bool
    """True if every figure used has status 'verified'."""
    sources: dict[str, FigureRef]
    """Figure key -> evidence for every figure the calculation used."""


def _kr(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), ROUND_HALF_UP)


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def _pos(x: Decimal) -> Decimal:
    return max(Decimal(0), x)


class _Figures:
    """Access to one year's figures that records which ones were used."""

    def __init__(self, year: int):
        self._all = load_year(year)
        self.used: dict[str, Figure] = {}

    def __getitem__(self, key: str) -> Figure:
        self.used[key] = self._all[key]
        return self._all[key]

    def value(self, key: str) -> Decimal:
        return self[key].value

    def rate(self, key: str) -> Decimal:
        return self[key].rate()


def _capped_bracket(
    f: _Figures,
    rate_key: str,
    graense_key: str,
    kapital_bundfradrag_key: str,
    kommuneskat: Decimal,
    personlig_indkomst: Decimal,
    positiv_kapitalindkomst: Decimal,
) -> Decimal:
    """The bracket the skatteloft cuts: topskat up to 2025, mellemskat from 2026.

    Tax on personal income above the threshold, plus a capital part on positive net
    capital income above its own bundfradrag (PSL § 7, stk. 3-4). Each part is cut by
    the percentage points by which kommune + bundskat + this rate exceeds its loft.
    """
    rate = f.value(rate_key)  # percent
    graense = f.value(graense_key)
    kapital = _pos(positiv_kapitalindkomst - f.value(kapital_bundfradrag_key))

    on_personal = _pos(personlig_indkomst - graense)
    on_combined = _pos(personlig_indkomst + kapital - graense)
    on_capital = on_combined - on_personal

    marginal = kommuneskat + f.value("bundskat") + rate
    rate_personal = _pos(rate - _pos(marginal - f.value("skatteloft")))
    rate_capital = _pos(rate - _pos(marginal - f.value("skatteloft_kapitalindkomst")))
    return (on_personal * rate_personal + on_capital * rate_capital) / 100


def estimate_salary_tax(
    year: int,
    gross_salary: Amount,
    *,
    kommuneskat: Amount,
    kirkeskat: Amount = 0,
    atp_full_time: bool = False,
    atp_own: Amount = 0,
    atp_employer: Amount = 0,
    pension_own: Amount = 0,
    pension_employer: Amount = 0,
    private_ratepension: Amount = 0,
    other_personal_income: Amount = 0,
    net_capital_income: Amount = 0,
    other_deductions: Amount = 0,
    within_15_years_of_pension: bool = False,
) -> SalaryTax:
    """Estimate one year's income tax. Rates (kommuneskat, kirkeskat) in percent as printed.

    All amounts are yearly kroner.
    gross_salary: total salary including your own pension share (it is paid out of
      your salary), excluding the employer's share. Bonus and RSU vests count as salary.
    pension_own/pension_employer: contributions to an employer-administered pension.
    private_ratepension: contributions you pay yourself (deducted in personlig indkomst).
    atp_full_time: use the statutory full-time ATP amounts instead of atp_own/atp_employer.
    other_deductions: other ligningsmæssige fradrag (befordring, union dues, ...).
    """
    args = dict(
        kommuneskat=kommuneskat,
        kirkeskat=kirkeskat,
        atp_full_time=atp_full_time,
        atp_own=atp_own,
        atp_employer=atp_employer,
        pension_own=pension_own,
        pension_employer=pension_employer,
        private_ratepension=private_ratepension,
        other_personal_income=other_personal_income,
        net_capital_income=net_capital_income,
        other_deductions=other_deductions,
        within_15_years_of_pension=within_15_years_of_pension,
    )
    result = _compute(year, gross_salary, **args)
    next_step = _compute(year, Decimal(str(gross_salary)) + MARGINAL_STEP, **args)
    marginal = (next_step.skat_i_alt - result.skat_i_alt) / MARGINAL_STEP * 100
    return result.model_copy(update={"marginalskat": _ore(marginal)})


def _compute(
    year: int,
    gross_salary: Amount,
    *,
    kommuneskat: Amount,
    kirkeskat: Amount,
    atp_full_time: bool,
    atp_own: Amount,
    atp_employer: Amount,
    pension_own: Amount,
    pension_employer: Amount,
    private_ratepension: Amount,
    other_personal_income: Amount,
    net_capital_income: Amount,
    other_deductions: Amount,
    within_15_years_of_pension: bool,
) -> SalaryTax:
    D = lambda x: Decimal(str(x))  # noqa: E731
    f = _Figures(year)
    if atp_full_time:  # full-time monthly-paid employee, figures are per month
        atp_own = f.value("atp_loenmodtager_maaned") * 12
        atp_employer = f.value("atp_arbejdsgiver_maaned") * 12
    kommune, kirke = D(kommuneskat), D(kirkeskat)
    nki = D(net_capital_income)
    atp = D(atp_own) + D(atp_employer)
    pension = D(pension_own) + D(pension_employer)

    # AM-bidrag and personlig indkomst
    am_grundlag = D(gross_salary) - D(atp_own) - D(pension_own)
    am_bidrag = _kr(am_grundlag * f.rate("am_bidrag"))
    personlig = am_grundlag - am_bidrag + D(other_personal_income) - D(private_ratepension)

    # Ligningsmæssige fradrag
    besk_grundlag = am_grundlag + atp + pension
    besk = _kr(min(besk_grundlag * f.rate("beskaeftigelsesfradrag"), f.value("beskaeftigelsesfradrag_max")))
    job = _kr(
        min(_pos(besk_grundlag - f.value("jobfradrag_bundgraense")) * f.rate("jobfradrag"), f.value("jobfradrag_max"))
    )
    am_paa_pension = _kr((atp + pension) * f.rate("am_bidrag"))
    ep_grundlag = min(atp + pension - am_paa_pension + D(private_ratepension), f.value("ekstra_pensionsfradrag_max_grundlag"))
    ep_rate = f.rate("ekstra_pensionsfradrag_15aar" if within_15_years_of_pension else "ekstra_pensionsfradrag")
    ekstra = _kr(ep_grundlag * ep_rate)
    ligningsmaessige = besk + job + ekstra + D(other_deductions)
    skattepligtig = personlig + nki - ligningsmaessige

    # Kommune- og kirkeskat, bundskat, kompensation
    personfradrag = f.value("personfradrag")
    kk_rate = (kommune + kirke) / 100
    kommune_kirke = _pos(skattepligtig * kk_rate - personfradrag * kk_rate)
    bund_rate = f.rate("bundskat")
    bundskat = _pos((personlig + _pos(nki)) * bund_rate - personfradrag * bund_rate)
    kompensation = min(_pos(-nki), f.value("negativ_kapitalindkomst_kompensation_graense")) * f.rate(
        "negativ_kapitalindkomst_kompensation"
    )

    # Brackets
    zero = Decimal(0)
    if year < REFORM_YEAR:
        mellemskat, toptopskat = zero, zero
        topskat = _capped_bracket(
            f, "topskat", "topskat_graense", "topskat_kapitalindkomst_bundfradrag", kommune, personlig, _pos(nki)
        )
    else:
        mellemskat = _capped_bracket(
            f, "mellemskat", "mellemskat_graense", "mellemskat_kapitalindkomst_bundfradrag", kommune, personlig, _pos(nki)
        )
        topskat = _pos(personlig - f.value("topskat_graense")) * f.rate("topskat")
        toptopskat = _pos(personlig - f.value("toptopskat_graense")) * f.rate("toptopskat")

    indkomstskat = kommune_kirke - kompensation + bundskat + mellemskat + topskat + toptopskat
    skat_i_alt = _ore(indkomstskat + am_bidrag)
    gross = D(gross_salary)
    return SalaryTax(
        year=year,
        am_bidrag_grundlag=am_grundlag,
        am_bidrag=am_bidrag,
        personlig_indkomst=personlig,
        beskaeftigelsesfradrag=besk,
        jobfradrag=job,
        ekstra_pensionsfradrag=ekstra,
        ligningsmaessige_fradrag=ligningsmaessige,
        skattepligtig_indkomst=skattepligtig,
        kommune_og_kirkeskat=_ore(kommune_kirke),
        kompensation=_ore(kompensation),
        bundskat=_ore(bundskat),
        mellemskat=_ore(mellemskat),
        topskat=_ore(topskat),
        toptopskat=_ore(toptopskat),
        indkomstskat=_ore(indkomstskat),
        skat_i_alt=skat_i_alt,
        til_udbetaling=_ore(gross - D(pension_own) - D(atp_own) - skat_i_alt),
        effektiv_skatteprocent=_ore(skat_i_alt / gross * 100) if gross else Decimal(0),
        all_verified=all(fig.status == "verified" for fig in f.used.values()),
        sources={
            key: FigureRef(source=fig.source, verified=fig.verified, status=fig.status) for key, fig in f.used.items()
        },
    )
