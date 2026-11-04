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
- Purchase year: both taxes are computed for the whole year (§§ 15, 18), then reduced to
  the days from and including the overtagelsesdag (§ 15, stk. 3; § 18, stk. 2). For
  ejendomsværdiskat a later indflytningsdag replaces it (§ 15, stk. 3); JV C.H.4.2.4
  (2026-2) treats that as an exception for owners moving from another owned home they are
  selling. The year is 360 days, 30 in each month (§ 72); the notes to § 72 in LSF 113
  2022/23 give the example 5 May = 125 of 360 days.

Scope: owning and living in the home from the overtagelsesdag (or all year) to the end of
the year. Not covered: sale during the year (§ 15, stk. 4), the transitional rabat for
pre-2024 owners (§§ 35-43; it lapses on a change of owner, § 43, so buyers never have it),
homes bought before 1 July 1998 (§§ 23-24), pensionistnedslag (§§ 25-26),
grundforbedringer, renting out, tofamilieshuse, sommerhuse.

Assumptions: amounts are kept exact and rounded to øre for display; SKAT's own rounding of
these taxes is not confirmed. Day 31 of a month counts as day 30 (§ 72 has 30-day months).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from dk_tax.calc.figures import FigureRef, Figures

FIRST_YEAR = 2026  # first year with figures for this calculator
DAYS_IN_YEAR = 360  # ESL § 72: 360 days, 30 in each month

Amount = int | Decimal


class PropertyTax(BaseModel):
    """Ejendomsværdiskat and grundskyld for one year. Kroner, rounded to øre."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # field docstrings -> outputSchema

    year: int
    vurderingsaar: int
    """The valuation year the ejendomsværdi and grundværdi should come from: the year
    before the income year (§ 13, stk. 2; § 17, stk. 2)."""
    ejendomsvaerdiskat_grundlag: Decimal
    ejendomsvaerdiskat_dage: int
    """Days of 360 with ejendomsværdiskat (from the overtagelsesdag or indflytningsdag)."""
    ejendomsvaerdiskat_ejendom: Decimal
    """Ejendomsværdiskat for the whole property for ejendomsvaerdiskat_dage."""
    ejerandel_pct: Decimal
    ejendomsvaerdiskat: Decimal
    """The owner's share of ejendomsvaerdiskat_ejendom."""
    grundskyld_grundlag: Decimal
    grundskyld_dage: int
    """Days of 360 with grundskyld (from the overtagelsesdag)."""
    grundskyld_fuld: Decimal
    """Grundskyld for a whole year before the stigningsbegrænsning."""
    grundskyld: Decimal
    """Grundskyld for the property for grundskyld_dage, after the stigningsbegrænsning if
    last year's amount was given."""
    stigningsbegraensning_anvendt: bool
    """True if the cap lowered the grundskyld."""
    grundskyld_oevre_graense: bool
    """True if last year's grundskyld was not given: grundskyld is then an upper bound."""
    all_verified: bool
    sources: dict[str, FigureRef]


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def days_through(d: date) -> int:
    """Days of the 360-day year from 1 January up to and including d (§ 72; day 31 = day 30)."""
    return (d.month - 1) * 30 + min(d.day, 30)


def days_from(d: date) -> int:
    """Days of the 360-day year from and including d to 31 December."""
    return DAYS_IN_YEAR - days_through(d) + 1


def _days_liable(start: date | None, year: int) -> int:
    if start is None or start.year < year:
        return DAYS_IN_YEAR
    if start.year > year:
        return 0
    return days_from(start)


def estimate_property_tax(
    year: int,
    ejendomsvaerdi: Amount,
    grundvaerdi: Amount,
    *,
    grundskyldspromille: Amount,
    ejerandel_pct: Amount = 100,
    grundskyld_forrige_aar: Amount | None = None,
    overtagelsesdag: date | None = None,
    indflytningsdag: date | None = None,
) -> PropertyTax:
    """Ejendomsværdiskat and grundskyld for one year of owning and living in the home.

    ejendomsvaerdi, grundvaerdi: the values assessed for the PREVIOUS year (the 2026 tax
      uses the 2025 assessment). For an ejerlejlighed, the flat's own values.
    grundskyldspromille: the kommune's rate, per mille as printed.
    ejerandel_pct: the owner's registered share, for ejendomsværdiskat.
    grundskyld_forrige_aar: the property's grundskyld for the previous year, to apply the
      stigningsbegrænsning.
    overtagelsesdag: if bought during the year; earlier years mean a whole year.
    indflytningsdag: a later move-in that replaces the overtagelsesdag for ejendomsværdiskat.
    """
    if year < FIRST_YEAR:
        raise ValueError(f"Property tax rules are implemented from income year {FIRST_YEAR}")
    if overtagelsesdag and overtagelsesdag.year > year:
        raise ValueError(f"overtagelsesdag {overtagelsesdag} is after the income year {year}")
    if indflytningsdag and overtagelsesdag and indflytningsdag < overtagelsesdag:
        raise ValueError(f"indflytningsdag {indflytningsdag} is before the overtagelsesdag {overtagelsesdag}")
    gs_dage = _days_liable(overtagelsesdag, year)
    evs_dage = min(gs_dage, _days_liable(indflytningsdag, year)) if indflytningsdag else gs_dage
    D = lambda x: Decimal(str(x))  # noqa: E731
    f = Figures(year)
    andel = f.rate("beskatningsgrundlag_ejendom_andel")

    # Ejendomsværdiskat, for the whole property, then the owner's share
    evs_grundlag = andel * D(ejendomsvaerdi)
    graense = f.value("ejendomsvaerdiskat_progressionsgraense")
    evs_ejendom = min(evs_grundlag, graense) * f.rate("ejendomsvaerdiskat_sats") + max(
        Decimal(0), evs_grundlag - graense
    ) * f.rate("ejendomsvaerdiskat_progressiv_sats")
    evs_ejendom = evs_ejendom * evs_dage / DAYS_IN_YEAR
    evs = evs_ejendom * D(ejerandel_pct) / 100

    # Grundskyld with the stigningsbegrænsning
    gs_grundlag = andel * D(grundvaerdi)
    gs_fuld = gs_grundlag * D(grundskyldspromille) / 1000
    gs_aar = gs_fuld
    if grundskyld_forrige_aar is not None:
        gs_aar = min(gs_fuld, D(grundskyld_forrige_aar) + gs_fuld * f.rate("grundskyld_stigningsprocent"))
    gs = gs_aar * gs_dage / DAYS_IN_YEAR

    return PropertyTax(
        year=year,
        vurderingsaar=year - 1,
        ejendomsvaerdiskat_grundlag=_ore(evs_grundlag),
        ejendomsvaerdiskat_dage=evs_dage,
        ejendomsvaerdiskat_ejendom=_ore(evs_ejendom),
        ejerandel_pct=D(ejerandel_pct),
        ejendomsvaerdiskat=_ore(evs),
        grundskyld_grundlag=_ore(gs_grundlag),
        grundskyld_dage=gs_dage,
        grundskyld_fuld=_ore(gs_fuld),
        grundskyld=_ore(gs),
        stigningsbegraensning_anvendt=gs_aar < gs_fuld,
        grundskyld_oevre_graense=grundskyld_forrige_aar is None,
        all_verified=f.all_verified(),
        sources=f.sources(),
    )
