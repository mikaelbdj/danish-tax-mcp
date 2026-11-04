"""Married couple living together at year end (PSL §§ 6, 7, 10, 11, 13; JV C.A.8.2).

No official worked example for spouses was found, so these are hand calculations from the
law text. 2026: personfradrag 54.100, bundskat 12,01 %, mellemskat 7,5 % over 641.200 with a
capital grundbeløb of 55.000, skatteloft 44,57 % and 42,0 % for capital income. Kommuneskat
25 %, no kirkeskat, and income without AM-bidrag (other_personal_income) to keep the
numbers short. Single-person reference values come from estimate_salary_tax itself.
"""

from decimal import Decimal

from dk_tax.calc.couple import estimate_couple_tax
from dk_tax.calc.salary import estimate_salary_tax


def person(personlig=0, nki=0):
    return {"gross_salary": 0, "other_personal_income": personlig, "net_capital_income": nki}


def couple(a, b, **kw):
    return estimate_couple_tax(2026, a, b, kommuneskat=25, **kw)


def single(personlig=0, nki=0):
    return estimate_salary_tax(2026, 0, kommuneskat=25, other_personal_income=personlig, net_capital_income=nki)


def test_unused_personfradrag_moves_to_the_spouse():
    """§ 10, stk. 2: B has no income, so all of B's skatteværdi (25 % and 12,01 % of 54.100 =
    13.525 + 6.497,41 = 20.022,41) reduces A's taxes."""
    r = couple(person(600_000), person())
    assert r.overfoert_personfradrag_2_til_1 == Decimal("20022.41")
    assert r.spouse_1.indkomstskat == single(600_000).indkomstskat - Decimal("20022.41")
    assert r.spouse_2.indkomstskat == 0
    assert r.spouse_2.uudnyttet_personfradrag_vaerdi == 0


def test_negative_capital_income_is_netted_for_bundskat_and_the_nedslag():
    """§ 6, stk. 3: B's -40.000 is set against A's +40.000 before bundskat, so A pays
    12,01 % x 40.000 = 4.804 less. § 11, stk. 3, 2. pkt.: A's positive amount is also set
    against B's negative before the nedslag, so B gets none (single: 8 % x 40.000 = 3.200)."""
    r = couple(person(300_000, 40_000), person(300_000, -40_000))
    assert r.spouse_1.bundskat == single(300_000, 40_000).bundskat - Decimal("4804.00")
    assert r.spouse_2.kompensation == 0
    assert single(300_000, -40_000).kompensation == Decimal("3200.00")


def test_mellemskat_on_joint_capital_income_married_all_year():
    """§ 7, stk. 8-11: A 900.000 + 200.000 kapital, B 300.000 + 80.000. Combined 280.000
    over 2 x 55.000 = 170.000 is taxed on top of A's personal income (the higher). The
    capital rate is cut by the 42 % loft: 25 + 12,01 + 7,5 - 42 = 2,51, so 4,99 %:
    170.000 x 4,99 % = 8.483, split by kapital over 55.000: A 145/170, B 25/170."""
    r = couple(person(900_000, 200_000), person(300_000, 80_000))
    assert r.mellemskat_kapital == Decimal("8483.00")
    personal_a = (Decimal(900_000) - 641_200) * Decimal("0.075")
    assert r.spouse_1.mellemskat == (personal_a + Decimal("7235.50")).quantize(Decimal("0.01"))
    assert r.spouse_2.mellemskat == Decimal("1247.50")


def test_mellemskat_married_only_at_year_end_uses_own_brackets():
    """§ 7, stk. 5 (not married all year): each is taxed alone; only an unused grundbeløb
    moves. B's 80.000 is over 55.000, so nothing moves; B's 300.000 + 25.000 stays under
    641.200 and pays no mellemskat. A: 145.000 x 4,99 % = 7.235,50 on capital."""
    r = couple(person(900_000, 200_000), person(300_000, 80_000), married_all_year=False)
    assert r.spouse_2.mellemskat == 0
    assert r.spouse_1.mellemskat == single(900_000, 200_000).mellemskat


def test_unused_capital_grundbeloeb_moves_at_year_end():
    """§ 7, stk. 5: B has no kapitalindkomst, so A's grundbeløb is 55.000 + 55.000:
    (200.000 - 110.000) x 4,99 % = 4.491 instead of 7.235,50."""
    r = couple(person(900_000, 200_000), person(300_000), married_all_year=False)
    personal_a = (Decimal(900_000) - 641_200) * Decimal("0.075")
    assert r.spouse_1.mellemskat == (personal_a + Decimal("4491.00")).quantize(Decimal("0.01"))


def test_joint_capital_income_is_the_net_of_both():
    """Assumption: 'samlede positive nettokapitalindkomst' (§ 7, stk. 8) is the net of both
    spouses, as § 6, stk. 3 and § 7, stk. 5 net a negative amount first. A +200.000, B
    -30.000: (170.000 - 110.000) x 4,99 % = 2.994."""
    r = couple(person(900_000, 200_000), person(300_000, -30_000))
    assert r.mellemskat_kapital == Decimal("2994.00")


def test_underskud_personfradrag_and_nedslag_move_to_the_spouse():
    """A: personlig 100.000, kapital -150.000, skattepligtig -50.000. § 13, stk. 1: value
    12.500 against A's bundskat 12.010; 490 left = 1.960 kr. § 13, stk. 2: deducted in B's
    skattepligtig indkomst, so B's kommuneskat falls by 25 % x 1.960 = 490. § 10, stk. 2:
    A's whole personfradrag value 20.022,41 goes to B. § 11, stk. 3: B has no negative
    kapitalindkomst, so A's grænse is 100.000: nedslag 8 % x 100.000 = 8.000, unused by A,
    goes to B (§ 11, stk. 4)."""
    r = couple(person(100_000, -150_000), person(400_000))
    assert r.overfoert_underskud_1_til_2 == Decimal("1960.00")
    assert r.spouse_1.underskud_til_fremfoersel == 0
    assert r.overfoert_personfradrag_1_til_2 == Decimal("20022.41")
    assert r.overfoert_kompensation_1_til_2 == Decimal("8000.00")
    expected_b = single(400_000).indkomstskat - Decimal("490") - Decimal("20022.41") - Decimal("8000")
    assert r.spouse_2.indkomstskat == expected_b
    assert r.spouse_1.indkomstskat == 0


def test_household_total_and_sources():
    r = couple(person(600_000), person(200_000))
    assert r.skat_i_alt == r.spouse_1.skat_i_alt + r.spouse_2.skat_i_alt
    assert r.all_verified
    assert "personfradrag" in r.sources


def test_two_earners_without_capital_income_are_taxed_as_singles():
    """JV C.A.8.2: apart from the joint elements, each spouse is taxed on their own income."""
    r = couple(person(500_000), person(450_000))
    assert r.spouse_1.indkomstskat == single(500_000).indkomstskat
    assert r.spouse_2.indkomstskat == single(450_000).indkomstskat
