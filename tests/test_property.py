"""Property tax calculator: ejendomsværdiskat and grundskyld (ejendomsskatteloven).

No official worked example of the amounts was found, so these are hand calculations from
the law (lov nr. 678 af 3/6/2023 as amended) with the 2026 figures. The day count is tested
against the example in the bill (LSF 113 2022/23). Aarhus grundskyld 6 promille.
"""

from datetime import date
from decimal import Decimal

import pytest

from dk_tax.calc.property import days_from, days_through, estimate_property_tax

AARHUS = Decimal(6)


def test_2026_hand_calculation_above_progressionsgraense():
    """ESL §§ 13, 17, 22. Ejendomsværdi 12.000.000, grundværdi 2.000.000, sole owner.
    ejendomsværdiskat grundlag  80 % x 12.000.000                     = 9.600.000
                                5,1 promille x 9.007.000              =    45.935,70
                                14 promille x (9.600.000 - 9.007.000) =     8.302,00
                                                                      =    54.237,70
    grundskyld                  80 % x 2.000.000 = 1.600.000 x 6 promille = 9.600,00
    """
    r = estimate_property_tax(2026, 12_000_000, 2_000_000, grundskyldspromille=AARHUS)
    assert r.ejendomsvaerdiskat_grundlag == 9_600_000
    assert r.ejendomsvaerdiskat == Decimal("54237.70")
    assert r.grundskyld_grundlag == 1_600_000
    assert r.grundskyld == Decimal("9600.00")
    assert r.grundskyld_oevre_graense  # no previous-year grundskyld given, so § 45 not applied
    assert r.vurderingsaar == 2025  # §§ 13, 17, stk. 2: the previous year's valuation
    assert r.all_verified
    assert {"ejendomsvaerdiskat_sats", "ejendomsvaerdiskat_progressionsgraense"} <= set(r.sources)


def test_co_owner_pays_share_of_ejendomsvaerdiskat_computed_for_the_whole_property():
    """§ 13, stk. 1, 2. pkt.: computed for the property; § 16: split by ownership share.
    So the progressionsgrænse is not halved for a 50 % owner.
    Whole property 54.237,70 (as above) x 50 % = 27.118,85. Grundskyld is one amount for
    the property (§ 19 as amended by lov nr. 562 af 27/5/2025)."""
    r = estimate_property_tax(2026, 12_000_000, 2_000_000, grundskyldspromille=AARHUS, ejerandel_pct=50)
    assert r.ejendomsvaerdiskat_ejendom == Decimal("54237.70")
    assert r.ejendomsvaerdiskat == Decimal("27118.85")
    assert r.grundskyld == Decimal("9600.00")


def test_stigningsbegraensning_caps_grundskyld():
    """§ 45, stk. 2: the lower of full grundskyld and last year's + 4,75 % of full.
    Grundværdi 1.000.000: full = 800.000 x 6 promille = 4.800.
    Last year 4.000: 4.000 + 4,75 % x 4.800 = 4.228 < 4.800, so 4.228."""
    r = estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, grundskyld_forrige_aar=4_000)
    assert r.grundskyld_fuld == Decimal("4800.00")
    assert r.grundskyld == Decimal("4228.00")
    assert r.stigningsbegraensning_anvendt
    assert not r.grundskyld_oevre_graense


def test_stigningsbegraensning_not_binding():
    """Last year 4.700: 4.700 + 228 = 4.928 > 4.800, so the full 4.800 applies."""
    r = estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, grundskyld_forrige_aar=4_700)
    assert r.grundskyld == Decimal("4800.00")
    assert not r.stigningsbegraensning_anvendt


def test_below_progressionsgraense_only_the_low_rate():
    """80 % x 4.000.000 = 3.200.000 x 5,1 promille = 16.320."""
    r = estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS)
    assert r.ejendomsvaerdiskat == Decimal("16320.00")


def test_pre_2026_years_are_rejected():
    with pytest.raises(ValueError, match="2026"):
        estimate_property_tax(2025, 4_000_000, 1_000_000, grundskyldspromille=AARHUS)


# --- Part of the year (ESL §§ 15, 18, 72) -------------------------------------------------


def test_day_count_matches_the_bills_example():
    """LSF 113 2022/23, notes to § 72: liability ending 5 May is 125 of 360 days
    (the year is 360 days, 30 in each month). A buyer taking over on 6 May has the rest."""
    assert days_through(date(2026, 5, 5)) == 125
    assert days_from(date(2026, 5, 6)) == 360 - 125


def test_day_31_counts_as_day_30():
    """Assumption (§ 72 has no 31st): the usual 30/360 convention."""
    assert days_from(date(2026, 3, 31)) == days_from(date(2026, 3, 30)) == 271


def test_bought_1_april_pays_270_of_360_days():
    """ESL § 15, stk. 2-3 and § 18, stk. 2: from and including the overtagelsesdag.
    Full year 16.320 (ejendomsværdiskat) and 4.800 (grundskyld), x 270/360."""
    r = estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, overtagelsesdag=date(2026, 4, 1))
    assert (r.ejendomsvaerdiskat_dage, r.grundskyld_dage) == (270, 270)
    assert r.ejendomsvaerdiskat == Decimal("12240.00")
    assert r.grundskyld == Decimal("3600.00")


def test_later_indflytning_moves_only_the_ejendomsvaerdiskat_start():
    """§ 15, stk. 3: a later indflytningsdag replaces the overtagelsesdag for
    ejendomsværdiskat; grundskyld still runs from the overtagelsesdag (§ 18, stk. 2).
    Indflytning 1 July: 180/360 x 16.320 = 8.160."""
    r = estimate_property_tax(
        2026,
        4_000_000,
        1_000_000,
        grundskyldspromille=AARHUS,
        overtagelsesdag=date(2026, 4, 1),
        indflytningsdag=date(2026, 7, 1),
    )
    assert r.ejendomsvaerdiskat == Decimal("8160.00")
    assert r.grundskyld == Decimal("3600.00")


def test_cap_applies_to_the_full_year_then_the_part_year_reduction():
    """§ 45 compares yearly amounts; §§ 17-18 then reduce to the days owned.
    Capped 4.228 (see above) x 270/360 = 3.171."""
    r = estimate_property_tax(
        2026,
        4_000_000,
        1_000_000,
        grundskyldspromille=AARHUS,
        grundskyld_forrige_aar=4_000,
        overtagelsesdag=date(2026, 4, 1),
    )
    assert r.grundskyld == Decimal("3171.00")


def test_bought_in_an_earlier_year_is_a_full_year():
    r = estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, overtagelsesdag=date(2025, 9, 1))
    assert (r.ejendomsvaerdiskat_dage, r.grundskyld_dage) == (360, 360)
    assert r.ejendomsvaerdiskat == Decimal("16320.00")


def test_inconsistent_dates_are_rejected():
    with pytest.raises(ValueError, match="after the income year"):
        estimate_property_tax(2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, overtagelsesdag=date(2027, 1, 1))
    with pytest.raises(ValueError, match="before the overtagelsesdag"):
        estimate_property_tax(
            2026,
            4_000_000,
            1_000_000,
            grundskyldspromille=AARHUS,
            overtagelsesdag=date(2026, 4, 1),
            indflytningsdag=date(2026, 3, 1),
        )


def test_indflytning_in_the_next_year_means_no_ejendomsvaerdiskat_this_year():
    r = estimate_property_tax(
        2026,
        4_000_000,
        1_000_000,
        grundskyldspromille=AARHUS,
        overtagelsesdag=date(2026, 11, 1),
        indflytningsdag=date(2027, 2, 1),
    )
    assert r.ejendomsvaerdiskat_dage == 0
    assert r.ejendomsvaerdiskat == 0
    assert r.grundskyld_dage == 60  # November and December


# --- Selling during the year (ESL § 15, stk. 4; § 18, stk. 2) ----------------------------


def test_sold_buyer_takes_over_6_may_seller_pays_125_days():
    """§ 15, stk. 4 and § 18, stk. 2: the seller pays to and including the day before the
    buyer's overtagelsesdag. LSF 113 2022/23, notes to § 72: to 5 May = 125 of 360 days.
    16.320 x 125/360 = 5.666,67; 4.800 x 125/360 = 1.666,67."""
    r = estimate_property_tax(
        2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, salg_overtagelsesdag=date(2026, 5, 6)
    )
    assert (r.ejendomsvaerdiskat_dage, r.grundskyld_dage) == (125, 125)
    assert r.ejendomsvaerdiskat == Decimal("5666.67")
    assert r.grundskyld == Decimal("1666.67")


def test_moving_out_earlier_ends_only_the_ejendomsvaerdiskat():
    """§ 15, stk. 4, 2. pkt.: an earlier udflytningsdag replaces the day before the
    overtagelsesdag for ejendomsværdiskat (to and including 31 March = 90 days: 4.080).
    Grundskyld still runs to 5 May (§ 18, stk. 2)."""
    r = estimate_property_tax(
        2026,
        4_000_000,
        1_000_000,
        grundskyldspromille=AARHUS,
        salg_overtagelsesdag=date(2026, 5, 6),
        udflytningsdag=date(2026, 3, 31),
    )
    assert r.ejendomsvaerdiskat_dage == 90
    assert r.ejendomsvaerdiskat == Decimal("4080.00")
    assert r.grundskyld_dage == 125


def test_bought_and_sold_in_the_same_year():
    """Bought 1 April, buyer takes over 1 October: 1 April to 30 September = 180 days.
    16.320 / 2 = 8.160; 4.800 / 2 = 2.400."""
    r = estimate_property_tax(
        2026,
        4_000_000,
        1_000_000,
        grundskyldspromille=AARHUS,
        overtagelsesdag=date(2026, 4, 1),
        salg_overtagelsesdag=date(2026, 10, 1),
    )
    assert (r.ejendomsvaerdiskat_dage, r.grundskyld_dage) == (180, 180)
    assert r.ejendomsvaerdiskat == Decimal("8160.00")
    assert r.grundskyld == Decimal("2400.00")


def test_sale_in_a_later_year_is_a_full_year_here():
    r = estimate_property_tax(
        2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, salg_overtagelsesdag=date(2027, 2, 1)
    )
    assert r.ejendomsvaerdiskat_dage == 360


def test_inconsistent_sale_dates_are_rejected():
    with pytest.raises(ValueError, match="before the income year"):
        estimate_property_tax(
            2026, 4_000_000, 1_000_000, grundskyldspromille=AARHUS, salg_overtagelsesdag=date(2025, 12, 1)
        )
    with pytest.raises(ValueError, match="not after the overtagelsesdag"):
        estimate_property_tax(
            2026,
            4_000_000,
            1_000_000,
            grundskyldspromille=AARHUS,
            overtagelsesdag=date(2026, 6, 1),
            salg_overtagelsesdag=date(2026, 6, 1),
        )
    with pytest.raises(ValueError, match="udflytningsdag"):
        estimate_property_tax(
            2026,
            4_000_000,
            1_000_000,
            grundskyldspromille=AARHUS,
            salg_overtagelsesdag=date(2026, 5, 6),
            udflytningsdag=date(2026, 5, 10),
        )
