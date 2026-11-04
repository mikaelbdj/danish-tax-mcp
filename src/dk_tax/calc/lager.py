"""Yearly gain or loss on investeringsselskaber (most ETFs) for a person: lagerbeskatning.

Rules, with sources (aktieavancebeskatningsloven, LBK nr. 849 af 21/09/2026):
- § 23, stk. 8: gains and losses on shares and investeringsbeviser in investeringsselskaber
  (§§ 19 A-19 C) are always taxed on the lagerprincip, also when nothing is sold.
- § 23, stk. 2: the year's gain is the value at the end of the year minus the value at the
  start; for what was bought in the year the purchase price replaces the start value, for
  what was sold the sale price replaces the end value. Summed over a fund's lots that is
  end value + sales - start value - purchases, however many trades there were.
- § 19 B (aktiebaseret: on SKAT's ABIS list): aktieindkomst. JV C.B.4.3.2 (2026-2): losses
  are deducted 'uden begrænsninger', unlike listed shares (§ 13 A). A net gain can absorb
  listed-share losses (JV C.B.2.2.1.4).
- § 19 C (obligationsbaseret: everything else): kapitalindkomst (PSL § 4 a, stk. 2).

Not covered: distributions (udlodning/udbytte), which are taxed separately; the condition
in § 19 D that a loss is only deductible if SKAT received the purchase details (normally
reported by the broker); funds whose income year differs from the calendar year
(§ 23, stk. 8, 2.-4. pkt.); aktiesparekonto (its own 17 % lager tax).
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

Amount = int | Decimal


class Fund(BaseModel):
    """One fund for one year. Kroner."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    name: str
    isin: str | None = None
    aktiebaseret: bool | None = None
    """True if on SKAT's ABIS list for the year (§ 19 B), False if not (§ 19 C)."""
    value_start: Decimal = Decimal(0)
    """Market value of the holding on 1 January (0 if none)."""
    value_end: Decimal = Decimal(0)
    """Market value of the holding on 31 December (0 if all sold)."""
    purchases: Decimal = Decimal(0)
    """Total paid for units bought during the year, including costs."""
    sales: Decimal = Decimal(0)
    """Total received for units sold during the year, after costs."""


class FundResult(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str
    isin: str | None
    aktiebaseret: bool
    gevinst: Decimal
    """value_end + sales - value_start - purchases (negative: a loss)."""
    indkomsttype: str
    """'aktieindkomst' (§ 19 B) or 'kapitalindkomst' (§ 19 C)."""


class LagerGains(BaseModel):
    """The year's lager result per fund and in total. Kroner, rounded to øre."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    year: int
    funds: list[FundResult]
    aktieindkomst: Decimal
    """Net gain (negative: loss) on aktiebaserede funds (§ 19 B)."""
    kapitalindkomst: Decimal
    """Net gain (negative: loss) on obligationsbaserede funds (§ 19 C)."""
    til_estimate_share_income_tax: dict[str, Decimal]
    """How to pass the aktieindkomst on: a net gain as boersnoteret_udbytte_gevinst (listed
    losses may absorb it), a net loss as oevrig_aktieindkomst (deductible without the
    listed-share limit). Add it to the person's other share income."""
    til_net_capital_income: Decimal
    """Add to net_capital_income in estimate_salary_tax / estimate_couple_tax."""


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def estimate_lager_gains(year: int, funds: list[Fund]) -> LagerGains:
    results = []
    for f in funds:
        for field in ("value_start", "value_end", "purchases", "sales"):
            if getattr(f, field) < 0:
                raise ValueError(f"{f.name}: {field} cannot be negative")
        if f.aktiebaseret is None:
            raise ValueError(f"{f.name}: say whether it is aktiebaseret (on SKAT's ABIS list for {year})")
        gevinst = f.value_end + f.sales - f.value_start - f.purchases
        results.append(
            FundResult(
                name=f.name,
                isin=f.isin,
                aktiebaseret=f.aktiebaseret,
                gevinst=_ore(gevinst),
                indkomsttype="aktieindkomst" if f.aktiebaseret else "kapitalindkomst",
            )
        )
    aktie = sum((r.gevinst for r in results if r.aktiebaseret), Decimal(0))
    kapital = sum((r.gevinst for r in results if not r.aktiebaseret), Decimal(0))
    if aktie > 0:
        share_inputs = {"boersnoteret_udbytte_gevinst": _ore(aktie)}
    elif aktie < 0:
        share_inputs = {"oevrig_aktieindkomst": _ore(aktie)}
    else:
        share_inputs = {}
    return LagerGains(
        year=year,
        funds=results,
        aktieindkomst=_ore(aktie),
        kapitalindkomst=_ore(kapital),
        til_estimate_share_income_tax=share_inputs,
        til_net_capital_income=_ore(kapital),
    )
