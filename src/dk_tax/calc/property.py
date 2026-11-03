"""Ejendomsværdiskat and grundskyld for an owner-occupied home, from income year 2026.

Rules, with sources (ejendomsskatteloven, lov nr. 678 af 3/6/2023, as amended by lov
nr. 1214/2024, 562/2025, 1779/2025 and 615/2026):
- Ejendomsværdiskat: 80 % of the ejendomsværdi assessed for the previous income year
  (§ 13, stk. 2) at 5,1 promille up to the progressionsgrænse and 14 promille above it
  (§ 22, stk. 1). Computed for the whole property (§ 13, stk. 1, 2. pkt.), then shared
  by registered ownership shares (§ 16).
- Grundskyld: 80 % of the grundværdi assessed for the previous year (§ 17, stk. 2) at the
  kommune's promille (§ 28). One amount for the property (§ 19 as amended by 562/2025).
- Stigningsbegrænsning: grundskyld is the lower of the full grundskyld and last year's
  grundskyld plus 4,75 % of the full grundskyld (§ 45, stk. 2). It follows the property,
  also after a change of owner. Without last year's amount the full grundskyld is an
  upper bound.

Scope: a whole year of ownership and occupation. Not covered: the transitional rabat for
pre-2024 owners (§§ 35-43; it lapses on a change of owner, § 43, so buyers never have it),
purchase or sale during the year (§ 15, stk. 2-4, § 18, stk. 2), homes bought before
1 July 1998 (§§ 23-24), pensionistnedslag (§§ 25-26), grundforbedringer, renting out,
tofamilieshuse, sommerhuse.

Assumption: amounts are kept exact and rounded to øre for display; SKAT's own rounding of
these taxes is not confirmed.
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from dk_tax.calc.figures import FigureRef, Figures

FIRST_YEAR = 2026  # first year with figures for this calculator

Amount = int | Decimal


class PropertyTax(BaseModel):
    """Ejendomsværdiskat and grundskyld for one year. Kroner, rounded to øre."""

    year: int
    ejendomsvaerdiskat_grundlag: Decimal
    ejendomsvaerdiskat_ejendom: Decimal
    """Ejendomsværdiskat for the whole property."""
    ejerandel_pct: Decimal
    ejendomsvaerdiskat: Decimal
    """The owner's share of ejendomsvaerdiskat_ejendom."""
    grundskyld_grundlag: Decimal
    grundskyld_fuld: Decimal
    """Grundskyld before the stigningsbegrænsning."""
    grundskyld: Decimal
    """Grundskyld for the property after the stigningsbegrænsning, if last year's amount was given."""
    stigningsbegraensning_anvendt: bool
    """True if the cap lowered the grundskyld."""
    grundskyld_oevre_graense: bool
    """True if last year's grundskyld was not given: grundskyld is then an upper bound."""
    all_verified: bool
    sources: dict[str, FigureRef]


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def estimate_property_tax(
    year: int,
    ejendomsvaerdi: Amount,
    grundvaerdi: Amount,
    *,
    grundskyldspromille: Amount,
    ejerandel_pct: Amount = 100,
    grundskyld_forrige_aar: Amount | None = None,
) -> PropertyTax:
    """Ejendomsværdiskat and grundskyld for one year of owning and living in the home.

    ejendomsvaerdi, grundvaerdi: the values assessed for the PREVIOUS year (the 2026 tax
      uses the 2025 assessment). For an ejerlejlighed, the flat's own values.
    grundskyldspromille: the kommune's rate, per mille as printed.
    ejerandel_pct: the owner's registered share, for ejendomsværdiskat.
    grundskyld_forrige_aar: the property's grundskyld for the previous year, to apply the
      stigningsbegrænsning.
    """
    if year < FIRST_YEAR:
        raise ValueError(f"Property tax rules are implemented from income year {FIRST_YEAR}")
    D = lambda x: Decimal(str(x))  # noqa: E731
    f = Figures(year)
    andel = f.rate("beskatningsgrundlag_ejendom_andel")

    # Ejendomsværdiskat, for the whole property, then the owner's share
    evs_grundlag = andel * D(ejendomsvaerdi)
    graense = f.value("ejendomsvaerdiskat_progressionsgraense")
    evs_ejendom = min(evs_grundlag, graense) * f.rate("ejendomsvaerdiskat_sats") + max(
        Decimal(0), evs_grundlag - graense
    ) * f.rate("ejendomsvaerdiskat_progressiv_sats")
    evs = evs_ejendom * D(ejerandel_pct) / 100

    # Grundskyld with the stigningsbegrænsning
    gs_grundlag = andel * D(grundvaerdi)
    gs_fuld = gs_grundlag * D(grundskyldspromille) / 1000
    gs = gs_fuld
    if grundskyld_forrige_aar is not None:
        gs = min(gs_fuld, D(grundskyld_forrige_aar) + gs_fuld * f.rate("grundskyld_stigningsprocent"))

    return PropertyTax(
        year=year,
        ejendomsvaerdiskat_grundlag=_ore(evs_grundlag),
        ejendomsvaerdiskat_ejendom=_ore(evs_ejendom),
        ejerandel_pct=D(ejerandel_pct),
        ejendomsvaerdiskat=_ore(evs),
        grundskyld_grundlag=_ore(gs_grundlag),
        grundskyld_fuld=_ore(gs_fuld),
        grundskyld=_ore(gs),
        stigningsbegraensning_anvendt=gs < gs_fuld,
        grundskyld_oevre_graense=grundskyld_forrige_aar is None,
        all_verified=f.all_verified(),
        sources=f.sources(),
    )
