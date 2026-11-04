"""Income tax for an unmarried employee (lønmodtager) for one income year.

Rules, with sources (see also tests/test_salary.py):
- AM-bidrag: AMBL §§ 1-2. Employer-administered pension (own + employer share) and
  own ATP are kept out of the AM-bidrag base on the salary; the pension company
  withholds AM-bidrag on the pension instead (JV C.A.12.2, A.B.4.1.1.1.4).
- Personlig indkomst: PSL § 3. Skattepligtig indkomst: PSL §§ 1-2.
- Beskæftigelsesfradrag, jobfradrag, ekstra pensionsfradrag: LL §§ 9 J, 9 K, 9 L.
  Ligningsmæssige fradrag, so they reduce only the kommune/kirke base.
- Credits, each reducing taxes to at most 0: an underskud (negative skattepligtig
  indkomst) at the kommune + kirke rate against the state taxes (PSL § 13, stk. 1); then the
  skatteværdi of personfradrag against its own tax, the bundskat value on down the state
  brackets (§ 9), and what is left against the other taxes (§ 12, stk. 2); then the
  nedslag for negative nettokapitalindkomst (§ 11). Unused amounts are reported.
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

Not covered: married couples (transfers between spouses), negative personlig indkomst
(§ 13, stk. 3), underskud carried forward from earlier years, aktieindkomst,
ejendomsværdiskat, under-18 and senior rules.
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from dk_tax.calc.figures import FigureRef, Figures

REFORM_YEAR = 2026  # first year with mellemskat/topskat/toptopskat
MARGINAL_STEP = Decimal(1000)  # marginalskat: tax on the next 1.000 kr. of salary

Amount = int | Decimal


class SalaryTax(BaseModel):
    """Breakdown of the calculation. Kroner; taxes rounded to øre for display."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # field docstrings -> outputSchema

    year: int
    am_bidrag_grundlag: Decimal
    am_bidrag: Decimal
    am_bidrag_aktieloen: Decimal = Decimal(0)
    """AM-bidrag on share_compensation (B-income: not withheld by the employer)."""
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
    uudnyttet_personfradrag_vaerdi: Decimal = Decimal(0)
    """Skatteværdi of personfradrag left after all own taxes (PSL §§ 9, 12). Lost for a single
    person; a spouse living with them at year end can use it (§ 10, stk. 2)."""
    uudnyttet_kompensation: Decimal = Decimal(0)
    """§ 11 nedslag for negative nettokapitalindkomst left after all own taxes. Lost for a
    single person; goes to a spouse (§ 11, stk. 4)."""
    underskud_til_fremfoersel: Decimal = Decimal(0)
    """Negative skattepligtig indkomst not used against this year's state taxes (§ 13, stk. 1);
    carried forward to next year's skattepligtig indkomst."""
    skat_i_alt: Decimal
    """indkomstskat + AM-bidrag on salary and shares (AM-bidrag on pension is paid from the pension)."""
    til_udbetaling: Decimal
    """Cash after tax: gross_salary - pension_own - atp_own - skat_i_alt (shares themselves not counted)."""
    effektiv_skatteprocent: Decimal
    """skat_i_alt as a percentage of gross_salary + share_compensation."""
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


STATE_TAXES = ["bundskat", "mellemskat", "topskat", "toptopskat"]  # order of PSL §§ 9 and 13


def _credit(taxes: dict[str, Decimal], amount: Decimal, order: list[str]) -> Decimal:
    """Reduce taxes in order by amount, none below 0. Returns what could not be used."""
    for key in order:
        used = min(amount, taxes[key])
        taxes[key] -= used
        amount -= used
    return amount


def _capped_bracket(
    f: Figures,
    rate_key: str,
    graense_key: str,
    kapital_bundfradrag: Decimal,
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
    kapital = _pos(positiv_kapitalindkomst - kapital_bundfradrag)

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
    share_compensation: Amount = 0,
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
    share_compensation: value of shares received as pay (RSU vests, LL § 16) at market
      value on the vesting date. B-income: 8 % AM-bidrag, then personlig indkomst; the
      employer withholds nothing (skat.dk, 'Skat af aktieløn og medarbejderaktier').
    atp_full_time: use the statutory full-time ATP amounts instead of atp_own/atp_employer.
    other_deductions: other ligningsmæssige fradrag (befordring, union dues, ...).
    """
    args = {
        "kommuneskat": kommuneskat,
        "kirkeskat": kirkeskat,
        "atp_full_time": atp_full_time,
        "atp_own": atp_own,
        "atp_employer": atp_employer,
        "pension_own": pension_own,
        "pension_employer": pension_employer,
        "private_ratepension": private_ratepension,
        "other_personal_income": other_personal_income,
        "share_compensation": share_compensation,
        "net_capital_income": net_capital_income,
        "other_deductions": other_deductions,
        "within_15_years_of_pension": within_15_years_of_pension,
    }
    result = _compute(year, gross_salary, **args)
    next_step = _compute(year, Decimal(str(gross_salary)) + MARGINAL_STEP, **args)
    marginal = (next_step.skat_i_alt - result.skat_i_alt) / MARGINAL_STEP * 100
    return result.model_copy(update={"marginalskat": _ore(marginal)})


def _compute(year: int, gross_salary: Amount, **kwargs) -> SalaryTax:
    p = _Person(year, gross_salary, **kwargs)
    p.gross_taxes()
    p.underskud()
    p.personfradrag()
    p.nedslag()
    return p.result()


class _Person:
    """One person's calculation, in steps, so a couple can exchange amounts between them.

    Single: gross_taxes, underskud, personfradrag, nedslag, result. A couple (calc/couple.py)
    passes joint bases to gross_taxes and moves unused amounts between the steps.
    """

    def __init__(
        self,
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
        share_compensation: Amount = 0,
        net_capital_income: Amount = 0,
        other_deductions: Amount = 0,
        within_15_years_of_pension: bool = False,
    ):
        D = lambda x: Decimal(str(x))  # noqa: E731
        self.year = year
        self.f = f = Figures(year)
        if atp_full_time:  # full-time monthly-paid employee, figures are per month
            atp_own = f.value("atp_loenmodtager_maaned") * 12
            atp_employer = f.value("atp_arbejdsgiver_maaned") * 12
        self.kommune, kirke = D(kommuneskat), D(kirkeskat)
        self.nki = D(net_capital_income)
        atp = D(atp_own) + D(atp_employer)
        pension = D(pension_own) + D(pension_employer)
        self.gross = D(gross_salary)
        self.cash_deductions = D(pension_own) + D(atp_own)
        self.share_compensation = D(share_compensation)

        # AM-bidrag and personlig indkomst
        self.am_grundlag = self.gross - D(atp_own) - D(pension_own)
        self.am_bidrag = _kr(self.am_grundlag * f.rate("am_bidrag"))
        # Shares are B-income: AM-bidrag (AMBL § 2, stk. 2), but outside the beskæftigelsesfradrag base.
        self.am_aktieloen = _kr(self.share_compensation * f.rate("am_bidrag"))
        self.personlig = (
            self.am_grundlag
            - self.am_bidrag
            + self.share_compensation
            - self.am_aktieloen
            + D(other_personal_income)
            - D(private_ratepension)
        )

        # Ligningsmæssige fradrag
        besk_grundlag = self.am_grundlag + atp + pension
        self.besk = _kr(min(besk_grundlag * f.rate("beskaeftigelsesfradrag"), f.value("beskaeftigelsesfradrag_max")))
        self.job = _kr(
            min(
                _pos(besk_grundlag - f.value("jobfradrag_bundgraense")) * f.rate("jobfradrag"),
                f.value("jobfradrag_max"),
            )
        )
        am_paa_pension = _kr((atp + pension) * f.rate("am_bidrag"))
        ep_grundlag = min(
            atp + pension - am_paa_pension + D(private_ratepension), f.value("ekstra_pensionsfradrag_max_grundlag")
        )
        ep_rate = f.rate("ekstra_pensionsfradrag_15aar" if within_15_years_of_pension else "ekstra_pensionsfradrag")
        self.ekstra = _kr(ep_grundlag * ep_rate)
        self.ligningsmaessige = self.besk + self.job + self.ekstra + D(other_deductions)
        self.skattepligtig = self.personlig + self.nki - self.ligningsmaessige

        self.kk_rate = (self.kommune + kirke) / 100
        self.bund_rate = f.rate("bundskat")
        self.underskud_rest = Decimal(0)  # kroner
        self.personfradrag_rest = Decimal(0)  # skatteværdi
        self.nedslag_rest = Decimal(0)
        self.kompensation = Decimal(0)

    @property
    def capped(self) -> tuple[str, str, str]:
        """Rate, grænse and capital bundfradrag keys of the bracket with a capital part."""
        if self.year < REFORM_YEAR:
            return "topskat", "topskat_graense", "topskat_kapitalindkomst_bundfradrag"
        return "mellemskat", "mellemskat_graense", "mellemskat_kapitalindkomst_bundfradrag"

    def capped_bracket(self, positiv_kapital: Decimal, kapital_bundfradrag: Decimal | None = None) -> Decimal:
        rate_key, graense_key, bundfradrag_key = self.capped
        if kapital_bundfradrag is None:
            kapital_bundfradrag = self.f.value(bundfradrag_key)
        return _capped_bracket(
            self.f, rate_key, graense_key, kapital_bundfradrag, self.kommune, self.personlig, positiv_kapital
        )

    def gross_taxes(
        self,
        *,
        bund_kapital: Decimal | None = None,
        capped_bracket: Decimal | None = None,
        underskud_modtaget: Decimal = Decimal(0),
    ) -> None:
        """Taxes before credits. A couple passes the positive kapitalindkomst for bundskat
        after netting (§ 6, stk. 3), the capped bracket computed jointly (§ 7, stk. 5-12),
        and a spouse's underskud deducted in this person's skattepligtig indkomst (§ 13, stk. 2)."""
        f = self.f
        self.underskud_modtaget = underskud_modtaget
        self.skattepligtig_efter = self.skattepligtig - underskud_modtaget
        bund_kapital = _pos(self.nki) if bund_kapital is None else bund_kapital
        if capped_bracket is None:
            capped_bracket = self.capped_bracket(_pos(self.nki))
        zero = Decimal(0)
        self.taxes = {
            "kommune_kirke": _pos(self.skattepligtig_efter) * self.kk_rate,
            "bundskat": _pos(self.personlig + bund_kapital) * self.bund_rate,
            "mellemskat": zero,
            "topskat": zero,
            "toptopskat": zero,
        }
        if self.year < REFORM_YEAR:
            self.taxes["topskat"] = capped_bracket
        else:
            self.taxes["mellemskat"] = capped_bracket
            self.taxes["topskat"] = _pos(self.personlig - f.value("topskat_graense")) * f.rate("topskat")
            self.taxes["toptopskat"] = _pos(self.personlig - f.value("toptopskat_graense")) * f.rate("toptopskat")

    def underskud(self) -> None:
        """§ 13, stk. 1: an underskud, valued at the kommune + kirke rate, reduces the state taxes."""
        rest = _credit(self.taxes, _pos(-self.skattepligtig_efter) * self.kk_rate, STATE_TAXES)
        self.underskud_rest = rest / self.kk_rate if self.kk_rate else _pos(-self.skattepligtig_efter)

    def underskud_value_from_spouse(self, value: Decimal) -> Decimal:
        """§ 13, stk. 2, 2. pkt.: the skatteværdi of a spouse's remaining underskud against
        this person's state taxes. Returns the value left."""
        return _credit(self.taxes, value, STATE_TAXES)

    def personfradrag(self) -> None:
        """§ 9: skatteværdi of personfradrag against its own tax (bundskat value then down the
        state brackets); § 12, stk. 2: what is left reduces the other taxes."""
        pf = self.f.value("personfradrag")
        kommune_rest = _credit(self.taxes, pf * self.kk_rate, ["kommune_kirke"])
        bund_rest = _credit(self.taxes, pf * self.bund_rate, STATE_TAXES)
        kommune_rest = _credit(self.taxes, kommune_rest, STATE_TAXES)
        bund_rest = _credit(self.taxes, bund_rest, ["kommune_kirke"])
        self.personfradrag_rest = kommune_rest + bund_rest
        self._snapshot()

    def personfradrag_from_spouse(self, value: Decimal) -> Decimal:
        """§ 10, stk. 2: a spouse's unused skatteværdi reduces this person's taxes (§ 9 order)."""
        rest = _credit(self.taxes, value, [*STATE_TAXES, "kommune_kirke"])
        self._snapshot()
        return rest

    def _snapshot(self) -> None:
        # The tax lines are shown after personfradrag and before the § 11 nedslag, which is its
        # own line (kompensation), as in svmn.dk's worked example.
        self.shown = dict(self.taxes)

    def nedslag(self, negativ_kapital: Decimal | None = None, graense: Decimal | None = None) -> None:
        """§ 11: nedslag for negative nettokapitalindkomst, in the order of § 11, stk. 1. A
        couple passes the netted negative amount and the raised grænse (§ 11, stk. 3)."""
        f = self.f
        negativ_kapital = _pos(-self.nki) if negativ_kapital is None else negativ_kapital
        graense = f.value("negativ_kapitalindkomst_kompensation_graense") if graense is None else graense
        nedslag = min(negativ_kapital, graense) * f.rate("negativ_kapitalindkomst_kompensation")
        self.nedslag_rest = _credit(self.taxes, nedslag, [*STATE_TAXES, "kommune_kirke"])
        self.kompensation = nedslag - self.nedslag_rest

    def nedslag_from_spouse(self, value: Decimal) -> Decimal:
        """§ 11, stk. 4: a spouse's unused nedslag against this person's taxes."""
        rest = _credit(self.taxes, value, [*STATE_TAXES, "kommune_kirke"])
        self.kompensation += value - rest
        return rest

    def result(self) -> SalaryTax:
        indkomstskat = sum(self.taxes.values(), Decimal(0))
        skat_i_alt = _ore(indkomstskat + self.am_bidrag + self.am_aktieloen)
        gross, shown = self.gross, self.shown
        return SalaryTax(
            year=self.year,
            am_bidrag_grundlag=self.am_grundlag,
            am_bidrag=self.am_bidrag,
            am_bidrag_aktieloen=self.am_aktieloen,
            personlig_indkomst=self.personlig,
            beskaeftigelsesfradrag=self.besk,
            jobfradrag=self.job,
            ekstra_pensionsfradrag=self.ekstra,
            ligningsmaessige_fradrag=self.ligningsmaessige,
            skattepligtig_indkomst=self.skattepligtig,
            kommune_og_kirkeskat=_ore(shown["kommune_kirke"]),
            kompensation=_ore(self.kompensation),
            bundskat=_ore(shown["bundskat"]),
            mellemskat=_ore(shown["mellemskat"]),
            topskat=_ore(shown["topskat"]),
            toptopskat=_ore(shown["toptopskat"]),
            indkomstskat=_ore(indkomstskat),
            uudnyttet_personfradrag_vaerdi=_ore(self.personfradrag_rest),
            uudnyttet_kompensation=_ore(self.nedslag_rest),
            underskud_til_fremfoersel=_ore(self.underskud_rest),
            skat_i_alt=skat_i_alt,
            til_udbetaling=_ore(gross - self.cash_deductions - skat_i_alt),
            effektiv_skatteprocent=_ore(skat_i_alt / (gross + self.share_compensation) * 100) if gross else Decimal(0),
            all_verified=self.f.all_verified(),
            sources=self.f.sources(),
        )
