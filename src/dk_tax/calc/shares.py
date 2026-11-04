"""Skat af aktieindkomst for one person or a married couple living together at year end.

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
  and gains on listed shares (including net gains on aktiebaserede investeringsselskaber,
  § 19 B; their losses are not limited, JV C.B.4.3.2, and belong in oevrig_aktieindkomst);
  the year's loss first, then older losses; the rest is carried
  forward as a loss. It never makes aktieindkomst negative.
- Unlisted shares (ABL § 13, JV C.B.2.2.1.3): the loss is part of aktieindkomst. Negative
  aktieindkomst gives a negative tax at the same rates (§ 8 a, stk. 5), credited in the
  slutskat; what cannot be credited is carried forward to later years' slutskat.

- Married couples living together at year end: a listed loss the owner cannot use is
  deducted in the spouse's listed income, the rest goes back to the owner (ABL § 13 A,
  JV C.B.2.2.1.4). Negative aktieindkomst is set against the spouse's positive (§ 8 a,
  stk. 6); negative tax on what is left uses the double grænse, split by size if both are
  negative, and what the owner's slutskat cannot take goes to the spouse's. An unused grænse
  raises the spouse's, by at most one grænse (§ 8 a, stk. 4).

Assumptions: the share tax not covered by withheld udbytteskat counts as slutskat that
negative tax can be credited against; for § 8 a, stk. 4 a spouse's aktieindkomst is taken
after the stk. 6 offset. Amounts are exact, rounded to øre for display. Not covered: foreign
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
    """For a couple: raised by the spouse's unused grænse, or the share of the double grænse."""
    boersnoteret_netto: Decimal
    """Listed dividends and gains after this year's and carried-forward listed losses (>= 0)."""
    boersnoteret_tab_til_aegtefaelle: Decimal = Decimal(0)
    """Listed-share loss deducted in the spouse's listed income (ABL § 13 A)."""
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
    """This person's negative tax (this year's plus carried forward) credited this year, in
    their own slutskat or the spouse's."""
    negativ_skat_til_aegtefaelle: Decimal = Decimal(0)
    """The part of negativ_skat_anvendt credited in the spouse's slutskat (§ 8 a, stk. 6)."""
    negativ_skat_fremfoert_naeste_aar: Decimal
    """Negative tax left to carry forward to next year's slutskat."""
    netto: Decimal
    """What shares add to this person's tax bill: skat - udbytteskat_indeholdt - negative tax
    (own or the spouse's) credited in this person's slutskat. Negative lowers other tax."""
    slutskat_ukendt: bool
    """True if oevrig_slutskat was not given: negativ_skat_anvendt then assumes all of it could
    be credited, which overstates it if the other tax is smaller."""
    all_verified: bool
    sources: dict[str, FigureRef]


def _ore(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


INPUTS = (
    "boersnoteret_udbytte_gevinst",
    "boersnoteret_tab",
    "boersnoteret_tab_fremfoert",
    "oevrig_aktieindkomst",
    "udbytteskat_indeholdt",
    "negativ_skat_fremfoert",
    "oevrig_slutskat",
)
NON_NEGATIVE = set(INPUTS) - {"oevrig_aktieindkomst"}


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
    oevrig_slutskat: the year's other slutskat (income tax, AM-bidrag and ejendomsværdiskat,
      JV C.H.4.1.1 (2026-2)), which negative tax can be credited against. None: unknown.
    """
    person = {k: v for k, v in locals().items() if k in INPUTS}
    return _compute(year, [person])[0]


def estimate_couple_share_income_tax(
    year: int, spouse_1: dict, spouse_2: dict
) -> tuple[ShareIncomeTax, ShareIncomeTax]:
    """Both spouses' skat af aktieindkomst; each dict takes the inputs of
    estimate_share_income_tax (all optional)."""
    a, b = _compute(year, [spouse_1, spouse_2])
    return a, b


def _compute(year: int, persons: list[dict]) -> list[ShareIncomeTax]:
    D = lambda x: Decimal(str(x))  # noqa: E731
    zero = Decimal(0)
    ps = []
    for person in persons:
        unknown = set(person) - set(INPUTS)
        if unknown:
            raise ValueError(f"Unknown input(s): {', '.join(sorted(unknown))}")
        p = {k: person.get(k, 0) for k in INPUTS}
        p["oevrig_slutskat"] = person.get("oevrig_slutskat")
        for name in NON_NEGATIVE:
            if p[name] is not None and D(p[name]) < 0:
                raise ValueError(f"{name} cannot be negative (losses are entered as positive amounts)")
        ps.append({k: (D(v) if v is not None else None) for k, v in p.items()})
    couple = len(ps) == 2
    f = Figures(year)
    try:
        lav, hoej = f.rate("aktieindkomst_lav_sats"), f.rate("aktieindkomst_hoej_sats")
        G = f.value("aktieindkomst_progressionsgraense")
    except KeyError as e:
        raise ValueError(f"No aktieindkomst figures for {year}") from e

    def split(base: Decimal, graense: Decimal) -> Decimal:
        return min(base, graense) * lav + max(zero, base - graense) * hoej

    others = [1, 0] if couple else [None]

    # Listed shares: losses only against listed income (ABL § 13 A); for a couple the
    # owner's unused loss is deducted in the spouse's listed income first
    for p in ps:
        tab = p["boersnoteret_tab"] + p["boersnoteret_tab_fremfoert"]
        p["listed"] = max(zero, p["boersnoteret_udbytte_gevinst"] - tab)
        p["tab_rest"] = max(zero, tab - p["boersnoteret_udbytte_gevinst"])
        p["tab_til_aegtefaelle"] = zero
    if couple:
        for i, j in enumerate(others):
            moved = min(ps[i]["tab_rest"], ps[j]["listed"])
            ps[j]["listed"] -= moved
            ps[i]["tab_rest"] -= moved
            ps[i]["tab_til_aegtefaelle"] = moved
    for p in ps:
        p["ai"] = p["listed"] + p["oevrig_aktieindkomst"]

    # § 8 a, stk. 6: negative aktieindkomst against the spouse's positive
    if couple:
        for i, j in enumerate(others):
            if ps[i]["ai"] < 0 < ps[j]["ai"]:
                moved = min(-ps[i]["ai"], ps[j]["ai"])
                ps[i]["ai"] += moved
                ps[j]["ai"] -= moved

    # Grænse: stk. 4 for a positive amount, the double grænse for a negative one (stk. 6)
    negative_total = sum((-p["ai"] for p in ps if p["ai"] < 0), zero)
    for i, j in enumerate(others):
        p = ps[i]
        if not couple:
            p["graense"] = G
        elif p["ai"] >= 0:
            p["graense"] = G + min(G, max(zero, G - max(zero, ps[j]["ai"])))
        else:
            p["graense"] = 2 * G * (-p["ai"]) / negative_total
        p["skat"] = split(p["ai"], p["graense"]) if p["ai"] > 0 else zero
        p["negativ"] = split(-p["ai"], p["graense"]) if p["ai"] < 0 else zero

    # Negative tax against the slutskat: one's own first, then the spouse's (stk. 5-6)
    for p in ps:
        efter = p["skat"] - p["udbytteskat_indeholdt"]
        p["efter_udbytteskat"] = efter
        p["room"] = None if p["oevrig_slutskat"] is None else p["oevrig_slutskat"] + max(zero, efter)
        p["available"] = p["negativ"] + p["negativ_skat_fremfoert"]
        p["credited_here"] = zero  # negative tax (anyone's) credited in this person's slutskat
        p["til_aegtefaelle"] = zero

    def credit(src: dict, dst: dict) -> Decimal:
        used = src["available"] if dst["room"] is None else min(src["available"], dst["room"])
        src["available"] -= used
        if dst["room"] is not None:
            dst["room"] -= used
        dst["credited_here"] += used
        return used

    for p in ps:
        p["anvendt"] = credit(p, p)
    if couple:
        for i, j in enumerate(others):
            moved = credit(ps[i], ps[j])
            ps[i]["anvendt"] += moved
            ps[i]["til_aegtefaelle"] = moved

    return [
        ShareIncomeTax(
            year=year,
            progressionsgraense=_ore(p["graense"]),
            boersnoteret_netto=_ore(p["listed"]),
            boersnoteret_tab_til_aegtefaelle=_ore(p["tab_til_aegtefaelle"]),
            boersnoteret_tab_fremfoert_naeste_aar=_ore(p["tab_rest"]),
            aktieindkomst=_ore(p["ai"]),
            skat=_ore(p["skat"]),
            negativ_skat=_ore(p["negativ"]),
            udbytteskat_indeholdt=_ore(p["udbytteskat_indeholdt"]),
            negativ_skat_anvendt=_ore(p["anvendt"]),
            negativ_skat_til_aegtefaelle=_ore(p["til_aegtefaelle"]),
            negativ_skat_fremfoert_naeste_aar=_ore(p["available"]),
            netto=_ore(p["efter_udbytteskat"] - p["credited_here"]),
            slutskat_ukendt=p["oevrig_slutskat"] is None,
            all_verified=f.all_verified(),
            sources=f.sources(),
        )
        for p in ps
    ]
