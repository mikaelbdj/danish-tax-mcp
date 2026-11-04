"""Income tax for a married couple living together at year end, for one income year.

Each spouse is taxed on their own income as in calc/salary.py (JV C.A.8.2), with these
joint elements (personskatteloven, LBK nr. 1284 af 14/06/2021 as amended, last by lov nr.
482 af 22/05/2024 and lov nr. 1691 af 30/12/2024):
- Bundskat: one spouse's negative nettokapitalindkomst is set against the other's positive
  (§ 6, stk. 3).
- The bracket with a capital part (mellemskat from 2026, topskat up to 2025):
  married all year (§ 7, stk. 6-12): each pays on their own personal income; the combined
  positive nettokapitalindkomst over twice the grundbeløb is taxed on top of the higher
  personal income and split by each spouse's kapitalindkomst over the grundbeløb.
  Married at year end only (§ 7, stk. 5): each pays alone, but a negative amount is first
  set against the other's positive one, and an unused grundbeløb raises the other's.
- Underskud (§ 13, stk. 2): what is left after the spouse's own state taxes is deducted in
  the other's skattepligtig indkomst, then its skatteværdi reduces the other's state taxes.
- Personfradrag (§ 10, stk. 2): unused skatteværdi reduces the other's taxes.
- Nedslag for negative nettokapitalindkomst (§ 11, stk. 3-4): a positive amount is set
  against the other's negative one, an unused part of the 50.000 kr. grænse raises the
  other's, and an unused nedslag reduces the other's taxes.

Assumptions (no official worked example found): 'samlede positive nettokapitalindkomst'
in § 7, stk. 8 is the net of both spouses; with equal personal income spouse 1 counts as
the higher (§ 7, stk. 12 looks at certain deductions instead); the order of the steps
follows §§ 13, 9 and 11 for both spouses before amounts move between them.
Both spouses live in the same kommune; kirkeskat is per spouse. Not covered: aktieindkomst
(estimate_share_income_tax), business income (KSL § 25 A), negative personlig indkomst
(§ 13, stk. 4), underskud from earlier years.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from dk_tax.calc.figures import FigureRef
from dk_tax.calc.salary import MARGINAL_STEP, SalaryTax, _ore, _Person, _pos

Amount = int | Decimal


class CoupleTax(BaseModel):
    """Both spouses' income tax after the joint elements. Kroner, rounded to øre."""

    model_config = ConfigDict(use_attribute_docstrings=True)  # field docstrings -> outputSchema

    year: int
    married_all_year: bool
    spouse_1: SalaryTax
    spouse_2: SalaryTax
    mellemskat_kapital: Decimal
    """Married all year: the tax on the combined positive kapitalindkomst (§ 7, stk. 8-9,
    topskat up to 2025), included in the spouses' mellemskat lines. Otherwise 0."""
    overfoert_underskud_1_til_2: Decimal
    """Kroner of spouse 1's underskud deducted in spouse 2's skattepligtig indkomst (§ 13, stk. 2)."""
    overfoert_underskud_2_til_1: Decimal
    overfoert_personfradrag_1_til_2: Decimal
    """Skatteværdi of spouse 1's unused personfradrag used against spouse 2's taxes (§ 10, stk. 2)."""
    overfoert_personfradrag_2_til_1: Decimal
    overfoert_kompensation_1_til_2: Decimal
    """Spouse 1's unused § 11 nedslag used against spouse 2's taxes (§ 11, stk. 4)."""
    overfoert_kompensation_2_til_1: Decimal
    skat_i_alt: Decimal
    """Household total: spouse_1.skat_i_alt + spouse_2.skat_i_alt."""
    all_verified: bool
    sources: dict[str, FigureRef]


def estimate_couple_tax(
    year: int,
    spouse_1: dict,
    spouse_2: dict,
    *,
    kommuneskat: Amount,
    married_all_year: bool = True,
) -> CoupleTax:
    """Both spouses' tax. spouse_1/spouse_2 take the inputs of estimate_salary_tax
    (gross_salary required, kirkeskat per spouse) except kommuneskat, which they share."""
    result = _compute(year, spouse_1, spouse_2, kommuneskat, married_all_year)
    marginals = []
    for i in (0, 1):
        bumped = [dict(spouse_1), dict(spouse_2)]
        bumped[i]["gross_salary"] = Decimal(str(bumped[i]["gross_salary"])) + MARGINAL_STEP
        nxt = _compute(year, *bumped, kommuneskat, married_all_year)
        # marginal effect on the household's tax of the next 1.000 kr. of this spouse's salary
        marginals.append(_ore((nxt.skat_i_alt - result.skat_i_alt) / MARGINAL_STEP * 100))
    return result.model_copy(
        update={
            "spouse_1": result.spouse_1.model_copy(update={"marginalskat": marginals[0]}),
            "spouse_2": result.spouse_2.model_copy(update={"marginalskat": marginals[1]}),
        }
    )


def _compute(year: int, spouse_1: dict, spouse_2: dict, kommuneskat: Amount, married_all_year: bool) -> CoupleTax:
    p1 = _Person(year, kommuneskat=kommuneskat, **spouse_1)
    p2 = _Person(year, kommuneskat=kommuneskat, **spouse_2)
    pair = [(p1, p2), (p2, p1)]
    zero = Decimal(0)

    # § 6, stk. 3: the other spouse's negative nettokapitalindkomst reduces a positive one
    def netted_positive(a: _Person, b: _Person) -> Decimal:
        return _pos(a.nki + min(zero, b.nki)) if a.nki > 0 else zero

    # The bracket with a capital part (§ 7)
    grundbeloeb = p1.f.value(p1.capped[2])
    capped: dict[_Person, Decimal] = {}
    joint_capital_tax = zero
    if married_all_year:  # stk. 6-12
        higher = p1 if p1.personlig >= p2.personlig else p2
        combined = _pos(p1.nki + p2.nki)
        joint_capital_tax = higher.capped_bracket(combined, 2 * grundbeloeb) - higher.capped_bracket(zero)
        over = {p: _pos(p.nki - grundbeloeb) for p in (p1, p2)}
        total_over = over[p1] + over[p2]
        for a, _ in pair:
            share = over[a] / total_over if total_over else Decimal(a is higher)
            capped[a] = a.capped_bracket(zero) + joint_capital_tax * share
    else:  # stk. 5
        for a, b in pair:
            capped[a] = a.capped_bracket(netted_positive(a, b), grundbeloeb + _pos(grundbeloeb - _pos(b.nki)))

    # § 13, stk. 2: underskud left after one's own state taxes goes to the other spouse
    underskud = {p1: zero, p2: zero}
    for a, b in pair:
        a.gross_taxes(bund_kapital=netted_positive(a, b), capped_bracket=capped[a])
    for a in (p1, p2):
        a.underskud()
    for a, b in pair:
        if a.underskud_rest > 0 and b.skattepligtig > 0:
            moved = min(a.underskud_rest, b.skattepligtig)
            b.gross_taxes(bund_kapital=netted_positive(b, a), capped_bracket=capped[b], underskud_modtaget=moved)
            b.underskud()
            rest_value = b.underskud_value_from_spouse((a.underskud_rest - moved) * a.kk_rate)
            a.underskud_rest = rest_value / a.kk_rate if a.kk_rate else zero
            underskud[a] = moved
            break  # only one spouse can have an underskud the other can absorb

    # § 9 for each, then § 10, stk. 2: unused skatteværdi of personfradrag to the other
    for a, _ in pair:
        a.personfradrag()
    personfradrag = {}
    for a, b in pair:
        offered = a.personfradrag_rest
        a.personfradrag_rest = b.personfradrag_from_spouse(offered)
        personfradrag[a] = offered - a.personfradrag_rest

    # § 11, stk. 3-4: nedslag with netted amounts and a shared grænse, unused part to the other
    graense = p1.f.value("negativ_kapitalindkomst_kompensation_graense")
    for a, b in pair:
        negativ = _pos(_pos(-a.nki) - _pos(b.nki))
        a.nedslag(negativ, graense + _pos(graense - _pos(-b.nki)))
    kompensation = {}
    for a, b in pair:
        offered = a.nedslag_rest
        a.nedslag_rest = b.nedslag_from_spouse(offered)
        kompensation[a] = offered - a.nedslag_rest

    r1, r2 = p1.result(), p2.result()
    return CoupleTax(
        year=year,
        married_all_year=married_all_year,
        spouse_1=r1,
        spouse_2=r2,
        mellemskat_kapital=_ore(joint_capital_tax),
        overfoert_underskud_1_til_2=_ore(underskud[p1]),
        overfoert_underskud_2_til_1=_ore(underskud[p2]),
        overfoert_personfradrag_1_til_2=_ore(personfradrag[p1]),
        overfoert_personfradrag_2_til_1=_ore(personfradrag[p2]),
        overfoert_kompensation_1_til_2=_ore(kompensation[p1]),
        overfoert_kompensation_2_til_1=_ore(kompensation[p2]),
        skat_i_alt=r1.skat_i_alt + r2.skat_i_alt,
        all_verified=r1.all_verified and r2.all_verified,
        sources={**r1.sources, **r2.sources},
    )
