"""MCP layer: thin tool wrappers over the dk_tax logic."""

from datetime import date
from difflib import get_close_matches

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

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


def _load(year: int) -> dict[str, Figure]:
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
