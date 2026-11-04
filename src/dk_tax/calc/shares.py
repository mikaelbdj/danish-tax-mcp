"""Skat af aktieindkomst for one person (not married couples yet).

Rules, with sources:
- Aktieindkomst (PSL § 4 a): share dividends and gains and losses on shares (ABL §§ 12-14,
  19 B). RSU vesting is personal income, not aktieindkomst; a later sale is.
- Tax (PSL § 8 a, stk. 1-2, as rewritten by lov nr. 1691 af 30/12/2024 § 4): 27 % up to the
  progressionsgrænse, 42 % above. The grænse is regulated (§ 8 a, stk. 7, § 20); the kroner
  amounts come from svmn.dk.
- Udbytteskat (§ 8 a, stk. 1-3): withholding on the part up to the grænse is final, on the
  part above it credited in the slutskat, and any excess over 27 % of the total (all of it if
  aktieindkomst is negative) is credited too. Net effect: tax minus withholding.
- Listed shares (ABL § 13 A, JV C.B.2.2.1.4): a loss only offsets the year's total dividends
  and gains on listed shares; the year's loss first, then older losses; the rest is carried
  forward as a loss. It never makes aktieindkomst negative.
- Unlisted shares (ABL § 13, JV C.B.2.2.1.3): the loss is part of aktieindkomst. Negative
  aktieindkomst gives a negative tax at the same rates (§ 8 a, stk. 5), credited in the
  slutskat; what cannot be credited is carried forward to later years' slutskat.

Assumptions: the share tax not covered by withheld udbytteskat counts as slutskat that
carried-forward negative tax can be credited against. Amounts are exact, rounded to øre for
display. Not covered: married couples (§ 8 a, stk. 4 and 6; ABL § 13 A transfer), foreign
withholding tax (lempelse), aktiesparekonto, CFC, and § 4 a, stk. 3 (§ 19 B on personal
income).
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from dk_tax.calc.figures import FigureRef, Figures

Amount = int | Decimal


class ShareIncomeTax(BaseModel):
    """Skat af aktieindkomst for one year and one person. Kroner, rounded to øre."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # field docstrings -> outputSchema

    year: int
    progressionsgraense: Decimal
    boersnoteret_netto: Decimal
    """Listed dividends and gains after this year's and carried-forward listed losses (>= 0)."""
    boersnoteret_tab_fremfoert_naeste_aar: Decimal
    """Listed-share loss left to carry forward to next year (as a loss, not a tax)."""
    aktieindkomst: Decimal
    """boersnoteret_netto + oevrig_aktieindkomst. Negative only through unlisted losses."""
    skat: Decimal
    """Tax on positive aktieindkomst: 27 % up to the progressionsgrænse, 42 % above."""
    negativ_skat: Decimal
    """This year's negative tax on negative aktieindkomst, as a positive amount."""
    udbytteskat_indeholdt: Decimal
    negativ_skat_anvendt: Decimal
    """Negative tax (this year's plus carried forward) credited against this year's slutskat."""
    negativ_skat_fremfoert_naeste_aar: Decimal
    """Negative tax left to carry forward to next year's slutskat."""
    netto: Decimal
    """What shares add to the year's tax bill: skat - udbytteskat_indeholdt - negativ_skat_anvendt.
    Negative means it lowers the tax on other income."""
    slutskat_ukendt: bool
    """True if oevrig_slutskat was not given: negativ_skat_anvendt then assumes all of it could
    be credited, which overstates it if the other tax is smaller."""
    all_verified: bool
    sources: dict[str, FigureRef]


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def estimate_share_income_tax(
    year: int,
    *,
    boersnoteret_udbytte_gevinst: Amount = 0,
    boersnoteret_tab: Amount = 0,
    boersnoteret_tab_fremfoert: Amount = 0,
    oevrig_aktieindkomst: Amount = 0,
    udbytteskat_indeholdt: Amount = 0,
    negativ_skat_fremfoert: Amount = 0,
    oevrig_slutskat: Amount | None = None,
) -> ShareIncomeTax:
    """Skat af aktieindkomst for one person.

    boersnoteret_udbytte_gevinst: the year's dividends and gains on listed shares.
    boersnoteret_tab: the year's losses on listed shares (a positive amount).
    boersnoteret_tab_fremfoert: unused listed-share losses from earlier years.
    oevrig_aktieindkomst: unlisted shares: dividends plus gains minus losses (can be negative).
    udbytteskat_indeholdt: Danish udbytteskat withheld on the dividends.
    negativ_skat_fremfoert: unused negative share tax from earlier years.
    oevrig_slutskat: the year's other slutskat (income tax and AM-bidrag), which negative tax
      can be credited against. None: unknown.
    """
    D = lambda x: Decimal(str(x))  # noqa: E731
    for name, value in [
        ("boersnoteret_udbytte_gevinst", boersnoteret_udbytte_gevinst),
        ("boersnoteret_tab", boersnoteret_tab),
        ("boersnoteret_tab_fremfoert", boersnoteret_tab_fremfoert),
        ("udbytteskat_indeholdt", udbytteskat_indeholdt),
        ("negativ_skat_fremfoert", negativ_skat_fremfoert),
        ("oevrig_slutskat", oevrig_slutskat or 0),
    ]:
        if D(value) < 0:
            raise ValueError(f"{name} cannot be negative (losses are entered as positive amounts)")
    f = Figures(year)
    try:
        lav, hoej = f.rate("aktieindkomst_lav_sats"), f.rate("aktieindkomst_hoej_sats")
        graense = f.value("aktieindkomst_progressionsgraense")
    except KeyError as e:
        raise ValueError(f"No aktieindkomst figures for {year}") from e

    def split(base: Decimal) -> Decimal:
        return min(base, graense) * lav + max(Decimal(0), base - graense) * hoej

    # Listed shares: losses only against listed income (ABL § 13 A); the rest stays a loss
    tab_i_alt = D(boersnoteret_tab) + D(boersnoteret_tab_fremfoert)
    boersnoteret = max(Decimal(0), D(boersnoteret_udbytte_gevinst) - tab_i_alt)
    tab_videre = max(Decimal(0), tab_i_alt - D(boersnoteret_udbytte_gevinst))

    aktieindkomst = boersnoteret + D(oevrig_aktieindkomst)
    skat = split(aktieindkomst) if aktieindkomst > 0 else Decimal(0)
    negativ = split(-aktieindkomst) if aktieindkomst < 0 else Decimal(0)

    efter_udbytteskat = skat - D(udbytteskat_indeholdt)
    til_raadighed = negativ + D(negativ_skat_fremfoert)
    if oevrig_slutskat is None:
        anvendt = til_raadighed
    else:
        anvendt = min(til_raadighed, D(oevrig_slutskat) + max(Decimal(0), efter_udbytteskat))

    return ShareIncomeTax(
        year=year,
        progressionsgraense=graense,
        boersnoteret_netto=_ore(boersnoteret),
        boersnoteret_tab_fremfoert_naeste_aar=_ore(tab_videre),
        aktieindkomst=_ore(aktieindkomst),
        skat=_ore(skat),
        negativ_skat=_ore(negativ),
        udbytteskat_indeholdt=_ore(D(udbytteskat_indeholdt)),
        negativ_skat_anvendt=_ore(anvendt),
        negativ_skat_fremfoert_naeste_aar=_ore(til_raadighed - anvendt),
        netto=_ore(efter_udbytteskat - anvendt),
        slutskat_ukendt=oevrig_slutskat is None,
        all_verified=f.all_verified(),
        sources=f.sources(),
    )
