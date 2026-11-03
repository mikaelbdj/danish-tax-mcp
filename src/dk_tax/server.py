"""MCP layer: thin tool wrappers over the dk_tax logic."""

from collections.abc import Mapping
from datetime import date
from difflib import get_close_matches
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from dk_tax.calc.payslip import Payslip
from dk_tax.calc.payslip import estimate_payslip as _payslip
from dk_tax.calc.property import PropertyTax
from dk_tax.calc.property import estimate_property_tax as _property
from dk_tax.calc.salary import SalaryTax
from dk_tax.calc.salary import estimate_salary_tax as _estimate
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
    'verified' (all_verified tells you at a glance). Not covered: married couples,
    aktieindkomst, ejendomsværdiskat. Not tax advice.
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
    bonus: the year's total bonus in DKK, paid in bonus_payments equal parts (4 = quarterly). share_compensation: the year's RSU vest value in DKK.
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
) -> PropertyTaxResult:
    """Estimate ejendomsværdiskat and grundskyld for an owner-occupied home (house or
    ejerlejlighed) for one full year, from income year 2026.

    ejendomsvaerdi, grundvaerdi: DKK as assessed in the official property valuation for the
      PREVIOUS year (the 2026 tax uses the 2025 values). For an ejerlejlighed, the flat's own
      values. 80 % of each is taxed.
    ejerandel_pct: the user's ownership share; ejendomsværdiskat is computed for the whole
      property and then split. Grundskyld is reported for the whole property.
    grundskyld_forrige_aar: the property's grundskyld last year (e.g. from the previous owner's
      or last year's property tax bill). Grundskyld can rise at most 4,75 % of the full amount
      a year, also after a sale; without this input grundskyld is the uncapped upper bound
      (grundskyld_oevre_graense is true): say so.
    Assumes the home is owned and lived in the whole year; buying or selling during the year
    is not handled yet. Buyers get no transitional rabat (it lapses on a change of owner).
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
        )
    except (LookupError, ValueError) as e:
        raise ToolError(str(e)) from e
    return PropertyTaxResult(tax=tax, kommune=kommune_result)
