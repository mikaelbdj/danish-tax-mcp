"""Salary tax calculator: the official 2023 example, a hand calculation for 2026,
and svmn.dk's skatteloft table for every kommune."""

from decimal import Decimal

import pytest

from dk_tax.calc.salary import estimate_salary_tax
from dk_tax.loader import load_kommuner, load_year


def test_svmn_2023_example_single_taxpayer():
    """svmn.dk, 'Skatteberegningseksempel for en ugift skatteyder i 2023' (dated 07-08-2023):
    https://svmn.dk/tal-og-metode/satser/skatte-og-afgiftsberegning/skatteberegningseksempel-for-en-ugift-skatteyder-i-2023

    Row numbers [n] refer to that page. Ballerup kommune, folkekirke member,
    more than 15 years to folkepensionsalder. Aktieindkomst and ejendomsværdiskat
    in the example are out of scope for this calculator.
    """
    result = estimate_salary_tax(
        2023,
        gross_salary=750_000,  # [1]
        kommuneskat=Decimal("25.5"),  # Ballerup 2023, as stated in the example
        kirkeskat=Decimal("0.72"),
        atp_own=1_136,  # [2]; the employer pays twice that ([29] = 3 x [2])
        atp_employer=2_272,
        pension_own=42_750,  # [3]; employer pays twice that ([30] = 3 x [3])
        pension_employer=85_500,
        private_ratepension=60_900,  # [8]
        other_personal_income=1_800,  # [7] group life insurance paid via the pension fund
        net_capital_income=-30_000,  # [12]
        other_deductions=16_000,  # [16] befordring 10.000 + [18] union dues 6.000
        within_15_years_of_pension=False,
    )

    # Income statement (whole kroner in the example).
    assert result.am_bidrag_grundlag == 706_114  # [4]
    assert result.am_bidrag == 56_489  # [5]
    assert result.personlig_indkomst == 590_525  # [9]
    assert result.beskaeftigelsesfradrag == 45_600  # [32] capped
    assert result.jobfradrag == 2_700  # [33] capped
    assert result.ekstra_pensionsfradrag == 9_348  # [39] 12 % of the capped base 77.900
    assert result.ligningsmaessige_fradrag == 73_648  # [22]
    assert result.skattepligtig_indkomst == 486_877  # [26]

    # Taxes (to the øre).
    assert result.kommune_og_kirkeskat == Decimal("115073.55")  # [49]
    assert result.kompensation == Decimal("2400.00")  # [51]
    assert result.bundskat == Decimal("65428.52")  # [55]
    assert result.topskat == Decimal("3137.79")  # [67] after skatteloft
    assert result.indkomstskat == Decimal("181239.85")  # [68]


def test_2026_hand_calculation_aarhus():
    """Derived from the law (no official 2026 example exists); every step checkable by hand.

    900.000 kr. salary, no pension or ATP, Aarhus (24,52 %), not a folkekirke member.
      AM-bidrag            8 % x 900.000                            =  72.000
      personlig indkomst   900.000 - 72.000                         = 828.000
      beskæftigelsesfr.    12,75 % x 900.000 = 114.750, cap         =  63.300
      jobfradrag           4,5 % x (900.000 - 235.200) = 29.916, cap =   3.100
      skattepligtig        828.000 - 66.400                         = 761.600
      kommuneskat          24,52 % x (761.600 - 54.100)             = 173.479,00
      bundskat             12,01 % x (828.000 - 54.100)             =  92.945,39
      mellemskat           7,5 % x (828.000 - 641.200); 24,52 + 12,01 + 7,5
                           = 44,03 < 44,57, so no skatteloft cut    =  14.010,00
      topskat              7,5 % x (828.000 - 777.900)              =   3.757,50
      indkomstskat                                                  = 284.191,89
    """
    r = estimate_salary_tax(2026, 900_000, kommuneskat=Decimal("24.52"))
    assert (r.am_bidrag, r.personlig_indkomst, r.skattepligtig_indkomst) == (72_000, 828_000, 761_600)
    assert (r.beskaeftigelsesfradrag, r.jobfradrag, r.ekstra_pensionsfradrag) == (63_300, 3_100, 0)
    assert r.kommune_og_kirkeskat == Decimal("173479.00")
    assert r.bundskat == Decimal("92945.39")
    assert r.mellemskat == Decimal("14010.00")
    assert r.topskat == Decimal("3757.50")
    assert r.toptopskat == 0
    assert r.indkomstskat == Decimal("284191.89")
    assert r.skat_i_alt == Decimal("356191.89")


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_skatteloft_matches_svmn_table_for_every_kommune(year):
    """svmn.dk publishes each kommune's skatteloftsnedslag (percentage points cut from
    topskat up to 2025, mellemskat from 2026). Derive the cut from our calculation and compare."""
    bracket, rate = ("topskat", 15) if year < 2026 else ("mellemskat", Decimal("7.5"))
    graense = load_year(year)[f"{bracket}_graense"].value
    above = 10_000  # personal income 10.000 kr. above the threshold, below the next bracket
    for key, k in load_kommuner(year).kommuner.items():
        # Gross salary such that personlig indkomst = graense + above (AM-bidrag 8 %).
        gross = (graense + above) / Decimal("0.92")
        r = estimate_salary_tax(year, gross, kommuneskat=k.kommuneskat)
        tax = getattr(r, bracket)
        base = r.personlig_indkomst - graense
        cut = rate - tax * 100 / base
        assert abs(cut - k.skatteloftsnedslag) < Decimal("0.001"), f"{year} {key}: {cut} != {k.skatteloftsnedslag}"
