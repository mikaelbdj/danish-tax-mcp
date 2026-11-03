"""Property tax calculator: ejendomsværdiskat and grundskyld (ejendomsskatteloven).

No official worked example found, so these are hand calculations from the law
(lov nr. 678 af 3/6/2023 as amended) with the 2026 figures. Aarhus grundskyld 6 promille.
"""

from decimal import Decimal

import pytest

from dk_tax.calc.property import estimate_property_tax

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
