"""MCP layer: thin tool wrappers over the dk_tax logic."""

from collections.abc import Mapping
from datetime import date
from difflib import get_close_matches
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

from dk_tax.calc.couple import CoupleTax
from dk_tax.calc.couple import estimate_couple_tax as _couple
from dk_tax.calc.payslip import Payslip
from dk_tax.calc.payslip import estimate_payslip as _payslip
from dk_tax.calc.property import PropertyTax
from dk_tax.calc.property import estimate_property_tax as _property
from dk_tax.calc.salary import SalaryTax
from dk_tax.calc.salary import estimate_salary_tax as _estimate
from dk_tax.calc.shares import ShareIncomeTax
from dk_tax.calc.shares import estimate_couple_share_income_tax as _couple_shares
from dk_tax.calc.shares import estimate_share_income_tax as _shares
from dk_tax.loader import Figure, Kommune, Status, load_kommuner, load_year, slug

server = MCPServer(
    "dk-tax",
    instructions=(
        "Danish personal tax figures (rates, thresholds, deductions) per income year, "
        "each with its official source. Never state a Danish tax figure from memory: "
        "look it up here and cite its source and income year. Not tax advice."
    ),
)


class FigureIndexEntry(BaseModel):
    name: str
    unit: str


class FigureIndex(BaseModel):
    year: int
    figures: dict[str, FigureIndexEntry]


class FiguresResult(BaseModel):
    year: int
    figures: dict[str, Figure]


class KommuneResult(BaseModel):
    year: int
    kommune: Kommune
    source: str
    verified: date
    status: Status


def _load(year: int) -> Mapping[str, Figure]:
    try:
        return load_year(year)
    except LookupError as e:
        raise ToolError(str(e)) from e


def _kommune(year: int, kommune: str) -> KommuneResult:
    try:
        table = load_kommuner(year)
    except LookupError as e:
        raise ToolError(str(e)) from e
    key = slug(kommune)
    if key not in table.kommuner:
        raise ToolError(_unknown("kommune", key, list(table.kommuner)))
    return KommuneResult(
        year=year,
        kommune=table.kommuner[key],
        source=table.source,
        verified=table.verified,
        status=table.status,
    )


def _unknown(kind: str, wanted: str, known: list[str]) -> str:
    hint = get_close_matches(wanted, known, n=3)
    return f"Unknown {kind} '{wanted}'." + (f" Did you mean: {', '.join(hint)}?" if hint else "")


@server.tool()
def list_figures(year: int) -> FigureIndex:
    """List the tax figure keys available for an income year, with name and unit.

    Use this to find the right keys, then fetch values with get_figures.
    Keys differ between years when the law changed (e.g. 2025 has the old 15 %
    topskat; mellemskat and toptopskat start in 2026).
    """
    figures = _load(year)
    return FigureIndex(
        year=year,
        figures={key: FigureIndexEntry(name=f.name, unit=f.unit) for key, f in figures.items()},
    )


@server.tool()
def get_figures(year: int, keys: list[str]) -> FiguresResult:
    """Get Danish tax figures for an income year, each with source, verified date and status.

    Values are exactly as printed in the source: percent as 12.01 (not 0.1201),
    amounts in whole DKK. When answering, cite the source and the income year,
    and say so if status is not 'verified'. Use list_figures to discover keys.
    """
    figures = _load(year)
    unknown = [k for k in keys if k not in figures]
    if unknown:
        raise ToolError(" ".join(_unknown("figure", k, list(figures)) for k in unknown))
    return FiguresResult(year=year, figures={k: figures[k] for k in keys})


@server.tool()
def get_kommune(year: int, kommune: str) -> KommuneResult:
    """Get a municipality's kommuneskat, kirkeskat, skatteloftsnedslag and grundskyldspromille.

    `kommune` is the municipality name, e.g. 'Aarhus' or 'Lyngby-Taarbæk'.
    Percentages as printed (24.52 means 24,52 %). Kirkeskat applies only to
    members of Folkekirken.
    """
    return _kommune(year, kommune)


class SalaryTaxResult(BaseModel):
    tax: SalaryTax
    kommune: KommuneResult


@server.tool()
def estimate_salary_tax(
    year: int,
    gross_salary: int,
    kommune: str,
    folkekirke_member: bool,
    atp_full_time: bool = True,
    atp_own: int = 0,
    atp_employer: int = 0,
    pension_own: int = 0,
    pension_employer: int = 0,
    private_ratepension: int = 0,
    other_personal_income: int = 0,
    net_capital_income: int = 0,
    other_deductions: int = 0,
    within_15_years_of_pension: bool = False,
) -> SalaryTaxResult:
    """Estimate a single (unmarried) employee's Danish income tax for one year, with the full breakdown.

    Use this instead of doing tax arithmetic yourself. All amounts are yearly DKK, not percent.
    gross_salary: total salary INCLUDING the employee's own pension share and EXCLUDING the
      employer's share; bonus and RSU vests count as salary. If the user gives pension as
      percentages of salary, convert them to kroner first.
    pension_own / pension_employer: contributions to an employer-administered pension.
    private_ratepension: what the person pays into a ratepension themselves.
    atp_full_time: use the statutory full-time ATP amounts; set False and pass atp_own /
      atp_employer for part-time or other ATP.
    other_deductions: other ligningsmæssige fradrag (befordring, union dues, ...).
    The result includes til_udbetaling (take-home), effektiv_skatteprocent and marginalskat
    (share of the next 1.000 kr. that goes to tax), and the source, verified date and status
    of every figure used: cite them with the income year, and flag any figure that is not
    'verified' (all_verified tells you at a glance). For a married couple living together
    at year end use estimate_couple_tax; aktieindkomst: estimate_share_income_tax;
    ejendomsværdiskat: estimate_property_tax. Not tax advice.
    """
    kommune_result = _kommune(year, kommune)
    k = kommune_result.kommune
    try:
        tax = _estimate(
            year,
            gross_salary,
            kommuneskat=k.kommuneskat,
            kirkeskat=k.kirkeskat if folkekirke_member else 0,
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
    except LookupError as e:
        raise ToolError(str(e)) from e
    return SalaryTaxResult(tax=tax, kommune=kommune_result)


class SpouseIncome(BaseModel):
    """One spouse's yearly income, as for estimate_salary_tax. All amounts DKK."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    gross_salary: int
    """Total salary INCLUDING own pension share, EXCLUDING the employer's share; 0 if none."""
    folkekirke_member: bool
    atp_full_time: bool = True
    """Statutory full-time ATP; set False (and atp_own/atp_employer) for part-time or no job."""
    atp_own: int = 0
    atp_employer: int = 0
    pension_own: int = 0
    pension_employer: int = 0
    private_ratepension: int = 0
    other_personal_income: int = 0
    """E.g. SU, dagpenge or pension paid out: personal income without AM-bidrag."""
    net_capital_income: int = 0
    """This spouse's own nettokapitalindkomst (interest on loans in their name is negative)."""
    other_deductions: int = 0
    within_15_years_of_pension: bool = False


class CoupleTaxResult(BaseModel):
    tax: CoupleTax
    kommune: KommuneResult


@server.tool()
def estimate_couple_tax(
    year: int,
    kommune: str,
    spouse_1: SpouseIncome,
    spouse_2: SpouseIncome,
    married_all_year: bool = True,
) -> CoupleTaxResult:
    """Estimate the income tax of a married couple living together at year end, one year.

    Each spouse is taxed on their own income (same inputs as estimate_salary_tax), and the
    law then moves amounts between them: unused personfradrag, negative kapitalindkomst
    against the other's positive (bundskat, mellemskat, the 8 % nedslag on the first
    50.000 kr.), an unused capital grundbeløb for mellemskat, and an underskud. The overfoert_*
    fields show what moved. married_all_year: False if they married (or moved in as
    spouses) during the year; mellemskat on capital income is then computed per spouse.
    Use it only for married couples or registered partners; cohabiting unmarried couples
    are taxed as singles (estimate_salary_tax for each). Mortgage interest belongs to the
    spouse(s) whose name the loan is in, as negative net_capital_income.
    marginalskat per spouse is the household's extra tax on that spouse's next 1.000 kr.
    Not covered: aktieindkomst (estimate_share_income_tax), business income, underskud from
    earlier years, the skattekort (estimate_payslip is for one person).
    Cite the sources with the income year and flag any figure that is not 'verified'.
    Not tax advice.
    """
    kommune_result = _kommune(year, kommune)
    k = kommune_result.kommune

    def inputs(sp: SpouseIncome) -> dict:
        d = sp.model_dump()
        d["kirkeskat"] = k.kirkeskat if d.pop("folkekirke_member") else 0
        return d

    try:
        tax = _couple(
            year, inputs(spouse_1), inputs(spouse_2), kommuneskat=k.kommuneskat, married_all_year=married_all_year
        )
    except (LookupError, ValueError) as e:
        raise ToolError(str(e)) from e
    return CoupleTaxResult(tax=tax, kommune=kommune_result)


class PayslipResult(BaseModel):
    payslip: Payslip
    kommune: KommuneResult


@server.tool()
def estimate_payslip(
    year: int,
    monthly_salary: int,
    kommune: str,
    folkekirke_member: bool,
    pension_own_pct: float = 0,
    pension_employer_pct: float = 0,
    bonus: int = 0,
    bonus_payments: int = 1,
    bonus_has_pension: bool = False,
    share_compensation: int = 0,
    include_bonus_in_forskud: bool = True,
    include_shares_in_forskud: bool = True,
    share_withholding: Literal["none", "traekprocent", "fixed"] = "none",
    share_withholding_rate: float | None = None,
    vests_per_year: int = 4,
    atp_full_time: bool = True,
    net_capital_income: int = 0,
    other_deductions: int = 0,
    within_15_years_of_pension: bool = False,
) -> PayslipResult:
    """Predict the skattekort (trækprocent, månedsfradrag) and what is actually paid out in a
    normal month and in the bonus month, plus the year-end restskat, from 2026 onwards.

    Use this for questions about monthly take-home pay or what to enter in the
    forskudsopgørelse. One scenario per call: the include_*_in_forskud flags say whether the
    bonus and the shares are entered in the forskudsopgørelse; call twice to compare.
    monthly_salary: DKK per month INCLUDING the employee's own pension share.
    pension_*_pct: percent of monthly_salary (e.g. 4 and 8).
    bonus: the year's total bonus in DKK, paid in bonus_payments equal parts (4 = quarterly).
    share_compensation: the year's RSU vest value in DKK.
      Shares are B-income: the employer withholds nothing, so if they are left out of the
      forskudsopgørelse the tax comes as restskat (year_end.restskat > 0); paying it
      voluntarily before 31 December avoids interest.
    share_withholding: "none" = shares are B-income, nothing withheld (skat.dk's general rule);
      "traekprocent" = the employer keeps back shares to cover the tax at the skattekort's
      percentage (withhold-to-cover, common in private companies); "fixed" = at
      share_withholding_rate percent. Ask the employer which applies; see share_vest.
    Cite the sources with the income year and flag any figure that is not 'verified'.
    Assumptions are listed in dk_tax.calc.payslip. Not tax advice.
    """
    kommune_result = _kommune(year, kommune)
    k = kommune_result.kommune
    try:
        payslip = _payslip(
            year,
            monthly_salary,
            kommuneskat=k.kommuneskat,
            kirkeskat=k.kirkeskat if folkekirke_member else 0,
            pension_own_pct=str(pension_own_pct),
            pension_employer_pct=str(pension_employer_pct),
            bonus=bonus,
            bonus_payments=bonus_payments,
            bonus_has_pension=bonus_has_pension,
            share_compensation=share_compensation,
            include_bonus_in_forskud=include_bonus_in_forskud,
            include_shares_in_forskud=include_shares_in_forskud,
            share_withholding=share_withholding,
            share_withholding_rate=None if share_withholding_rate is None else str(share_withholding_rate),
            vests_per_year=vests_per_year,
            atp_full_time=atp_full_time,
            net_capital_income=net_capital_income,
            other_deductions=other_deductions,
            within_15_years_of_pension=within_15_years_of_pension,
        )
    except (LookupError, ValueError) as e:
        raise ToolError(str(e)) from e
    return PayslipResult(payslip=payslip, kommune=kommune_result)


class PropertyTaxResult(BaseModel):
    tax: PropertyTax
    kommune: KommuneResult


@server.tool()
def estimate_property_tax(
    year: int,
    kommune: str,
    ejendomsvaerdi: int,
    grundvaerdi: int,
    ejerandel_pct: float = 100,
    grundskyld_forrige_aar: int | None = None,
    overtagelsesdag: date | None = None,
    indflytningsdag: date | None = None,
    salg_overtagelsesdag: date | None = None,
    udflytningsdag: date | None = None,
) -> PropertyTaxResult:
    """Estimate ejendomsværdiskat and grundskyld for an owner-occupied home (house or
    ejerlejlighed) for one income year, from 2026, including the year it is bought.

    ejendomsvaerdi, grundvaerdi: DKK as assessed in the official property valuation for the
      PREVIOUS year (the 2026 tax uses the 2025 values). For an ejerlejlighed, the flat's own
      values. 80 % of each is taxed. The values are on vurderingsportalen.dk. For 2026 SKAT
      charges a provisional tax from a foreløbig vurdering and recalculates it when the final
      valuation is ready, so the estimate can change later.
      Exception: for a new build, a newly created ejerlejlighed, or a conversion or extension
      with a building permit in the year, SKAT uses a provisional base or the current year's
      valuation (ESL § 13, stk. 3 and 5; § 17, stk. 4-5). Tell the user this estimate may not
      match. A sale on its own does not trigger the exception.
    ejerandel_pct: the user's ownership share; ejendomsværdiskat is computed for the whole
      property and then split. Grundskyld is reported for the whole property.
    grundskyld_forrige_aar: the property's grundskyld last year (e.g. from the previous owner's
      or last year's property tax bill). Grundskyld can rise at most 4,75 % of the full amount
      a year, also after a sale; without this input grundskyld is the uncapped upper bound
      (grundskyld_oevre_graense is true): say so.
    overtagelsesdag: the takeover date if the home is bought during the year. Both taxes are
      then reduced to the days from that date, counting the year as 360 days (30 per month).
    indflytningsdag: only if the user moves in later than the overtagelsesdag AND is moving
      from another home they own and are selling; it then replaces the overtagelsesdag for
      ejendomsværdiskat only. Moving from a rental: leave it out.
    Once the purchase is registered in the forskudsopgørelse (TastSelv), SKAT shows its own
    amounts under 'Eksisterende ejendomme og grunde'; suggest the user compare.
    salg_overtagelsesdag: if the home is sold, the BUYER's takeover date: the seller pays to
      and including the day before. Bought and sold in the same year: pass both dates.
    udflytningsdag: if the seller moves out before that, the last day of ejendomsværdiskat
      (grundskyld still runs to the day before the buyer takes over).
    Buyers get no transitional rabat (it lapses on a change of owner).
    Mortgage interest (rentefradrag) is not a property tax: pass it as negative
    net_capital_income to estimate_salary_tax.
    Cite the sources with the income year and flag any figure that is not 'verified'.
    Not tax advice.
    """
    kommune_result = _kommune(year, kommune)
    try:
        tax = _property(
            year,
            ejendomsvaerdi,
            grundvaerdi,
            grundskyldspromille=kommune_result.kommune.grundskyldspromille,
            ejerandel_pct=str(ejerandel_pct),
            grundskyld_forrige_aar=grundskyld_forrige_aar,
            overtagelsesdag=overtagelsesdag,
            indflytningsdag=indflytningsdag,
            salg_overtagelsesdag=salg_overtagelsesdag,
            udflytningsdag=udflytningsdag,
        )
    except (LookupError, ValueError) as e:
        raise ToolError(str(e)) from e
    return PropertyTaxResult(tax=tax, kommune=kommune_result)


class SpouseShareIncome(BaseModel):
    """The spouse's share income for estimate_share_income_tax; all fields DKK, optional."""

    model_config = ConfigDict(extra="forbid")

    boersnoteret_udbytte_gevinst: int = 0
    boersnoteret_tab: int = 0
    boersnoteret_tab_fremfoert: int = 0
    oevrig_aktieindkomst: int = 0
    udbytteskat_indeholdt: int = 0
    negativ_skat_fremfoert: int = 0
    oevrig_slutskat: int | None = None


class ShareIncomeTaxResult(BaseModel):
    person: ShareIncomeTax
    spouse: ShareIncomeTax | None


@server.tool()
def estimate_share_income_tax(
    year: int,
    boersnoteret_udbytte_gevinst: int = 0,
    boersnoteret_tab: int = 0,
    boersnoteret_tab_fremfoert: int = 0,
    oevrig_aktieindkomst: int = 0,
    udbytteskat_indeholdt: int = 0,
    negativ_skat_fremfoert: int = 0,
    oevrig_slutskat: int | None = None,
    spouse: SpouseShareIncome | None = None,
) -> ShareIncomeTaxResult:
    """Estimate skat af aktieindkomst (27 % / 42 %) for one person for one income year.

    Aktieindkomst is share dividends and gains and losses on shares, taxed apart from salary
    (no personfradrag, brackets or skatteloft). RSU vesting is salary (estimate_salary_tax);
    selling the vested shares later, or their dividends, is aktieindkomst. Aktiesparekonto
    is a separate 17 % scheme and does not belong here.
    boersnoteret_udbytte_gevinst / boersnoteret_tab: the year's dividends plus gains, and
      losses (as a positive amount), on listed shares and listed funds taxed as aktieindkomst.
      A listed loss only offsets listed income; the rest is carried forward as a loss
      (boersnoteret_tab_fremfoert_naeste_aar) and never gives negative tax.
    boersnoteret_tab_fremfoert: unused listed-share losses from earlier years (årsopgørelse).
    oevrig_aktieindkomst: unlisted shares: dividends plus gains minus losses; may be negative.
      Negative aktieindkomst gives a negative tax credited against the other tax.
    udbytteskat_indeholdt: Danish udbytteskat withheld (27 %), not foreign withholding tax.
    negativ_skat_fremfoert: unused negative share tax from earlier years.
    oevrig_slutskat: the year's other tax, e.g. skat_i_alt from estimate_salary_tax, which
      negative tax is credited against. Without it slutskat_ukendt is true and all negative
      tax is assumed usable: say so.
    netto is what shares add to (or, if negative, take off) the year's tax.
    Ask whether the shares are listed: the loss rules differ.
    spouse: for a married couple living together at year end, the spouse's share income
      (same fields). Then an unused grænse moves to the other spouse, negative aktieindkomst
      is set against the spouse's positive, a listed loss the owner cannot use is deducted
      in the spouse's listed income, and negative tax can be credited in the spouse's
      slutskat. Pass the spouse even if they have no shares (an empty object), since
      their unused grænse still counts. Unmarried couples: one call each, no spouse.
    Foreign withholding tax relief (e.g. US dividends) is not handled.
    Cite the sources with the income year and flag any figure that is not 'verified'.
    Not tax advice.
    """
    person = {
        "boersnoteret_udbytte_gevinst": boersnoteret_udbytte_gevinst,
        "boersnoteret_tab": boersnoteret_tab,
        "boersnoteret_tab_fremfoert": boersnoteret_tab_fremfoert,
        "oevrig_aktieindkomst": oevrig_aktieindkomst,
        "udbytteskat_indeholdt": udbytteskat_indeholdt,
        "negativ_skat_fremfoert": negativ_skat_fremfoert,
        "oevrig_slutskat": oevrig_slutskat,
    }
    try:
        if spouse is None:
            return ShareIncomeTaxResult(person=_shares(year, **person), spouse=None)
        a, b = _couple_shares(year, person, spouse.model_dump())
        return ShareIncomeTaxResult(person=a, spouse=b)
    except (LookupError, ValueError) as e:
        raise ToolError(str(e)) from e
