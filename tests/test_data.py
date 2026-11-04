"""Data tests: every shipped figures file obeys the format rules from step 4."""

import re
from datetime import date
from decimal import Decimal

import pytest

from dk_tax.loader import Figure, available_years, load_kommuner, load_year, slug

YEARS = available_years()
OFFICIAL = re.compile(r"^https://(www\.)?(skat\.dk|info\.skat\.dk|svmn\.dk|retsinformation\.dk)/")


def test_expected_years_ship():
    assert {2025, 2026, 2027} <= set(YEARS)


@pytest.mark.parametrize("year", YEARS)
def test_every_figure_is_well_formed(year):
    # load_year already validates types and enums via pydantic; these are the rules it can't express.
    for key, f in load_year(year).items():
        assert re.fullmatch(r"[a-z0-9_]+", key) and slug(key) == key, f"{year}/{key}: key is not an ASCII slug"
        assert f.verified <= date.today(), f"{year}/{key}: verified date in the future"
        if f.status != "secondary":
            assert OFFICIAL.match(f.source), f"{year}/{key}: source is not an official site"
        if f.status != "verified":
            assert f.note, f"{year}/{key}: status '{f.status}' needs a note explaining why"
        if f.unit == "percent":
            assert 0 <= f.value <= 100, f"{year}/{key}: percentage out of range"
        if f.unit == "permille":
            assert 0 <= f.value <= 1000, f"{year}/{key}: per mille out of range"


def test_permille_rate_is_a_fraction():
    # Property tax rates are printed in promille (5,1 promille); stored as printed.
    f = Figure(
        name="x", value=Decimal("5.1"), unit="permille", source="s", verified=date(2026, 1, 1), status="verified"
    )
    assert f.rate() == Decimal("0.0051")


# 2023 exists only for the official worked example and has no municipal table.
@pytest.mark.parametrize("year", [y for y in YEARS if y != 2023])
def test_kommune_tables_are_complete(year):
    table = load_kommuner(year)
    assert OFFICIAL.match(table.source)
    assert len(table.kommuner) == 98
    assert "aarhus" in table.kommuner


# Regression guard: values checked by hand against the sources on 2026-11-01.
# If one of these fails, a figure was edited; re-verify it before updating the test.
@pytest.mark.parametrize(
    ("year", "key", "value"),
    [
        (2025, "personfradrag", 51600),
        (2025, "topskat", 15),
        (2025, "topskat_graense", 611800),
        (2026, "personfradrag", 54100),
        (2026, "bundskat", "12.01"),
        (2026, "mellemskat_graense", 641200),
        (2026, "skatteloft", "44.57"),
        (2027, "personfradrag", 55700),
        (2027, "topskat_graense", 800500),
        (2027, "aldersopsparing_max_indskud_7aar", 66000),  # the one the regex bug broke
        (2025, "restskat_dag_til_dag_rente", "3.7"),
        (2025, "restskat_procenttillaeg", "5.7"),
        (2026, "restskat_indregningsgraense", 25200),
        (2027, "restskat_indregningsgraense", 25900),
        (2026, "restskat_mindsterate", 500),
    ],
)
def test_pinned_values(year, key, value):
    from decimal import Decimal

    assert load_year(year)[key].value == Decimal(str(value))


def test_aarhus_rates():
    for year in (2025, 2026, 2027):
        aarhus = load_kommuner(year).kommuner["aarhus"]
        assert (str(aarhus.kommuneskat), str(aarhus.kirkeskat)) == ("24.52", "0.74")


def test_next_year_has_figures():
    """Figures for year N are published in autumn of N-1. From November, require them,
    so a stale package fails loudly instead of quietly answering with last year's rules."""
    today = date.today()
    if today.month >= 11:
        assert today.year + 1 in YEARS, f"Add figures for {today.year + 1} (see CONTRIBUTING.md)"


def test_unknown_kommune_year_lists_only_years_with_a_kommune_table():
    # 2023 has figures (for the svmn.dk example) but no kommune table.
    with pytest.raises(LookupError) as e:
        load_kommuner(2023)
    assert "2023" not in str(e.value).split("Available years:")[1]
    assert "2026" in str(e.value)


def test_loaded_figures_are_read_only():
    # load_year is cached and shared by every caller; a change would leak into later calls.
    with pytest.raises(TypeError):
        load_year(2026)["bundskat"] = None
    with pytest.raises(TypeError):
        load_kommuner(2026).kommuner["aarhus"] = None


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_aktiesparekonto_loft_is_a_value_limit(year):
    """Aktiesparekontoloven § 9, stk. 1: the account's value on 31 December plus the year's net
    deposits may not exceed the grænse; it is not a cap on total deposits (svmn.dk calls it
    'Værdigrænse for indskud'; skat.dk's examples). No unsourced claims in the note."""
    f = load_year(year)["aktiesparekonto_indskudsloft"]
    assert "Værdigrænse" in f.name
    assert "31 December" in f.note and "net deposits" in f.note
    assert "total deposits" not in f.note.replace("not a cap on total deposits", "")
    assert "500.000" not in f.note


def test_restskat_rates_2025_fit_the_law_and_skat_dk():
    """KSL § 59: dag-til-dag rente = OPKL § 7, stk. 2 rate - 0,5 points; § 61, stk. 2:
    procenttillæg = the same rate + 1,5 points (so they differ by 2,0). skat.dk quotes the
    indregningsgrænse with the tillæg added: 24.000 x 1,057 = 25.368 kr. for income year 2025."""
    f = load_year(2025)
    rente, tillaeg = f["restskat_dag_til_dag_rente"].value, f["restskat_procenttillaeg"].value
    assert tillaeg - rente == 2
    graense = f["restskat_indregningsgraense"].value
    assert graense * (1 + f["restskat_procenttillaeg"].rate()) == 25368


def test_restskat_rates_for_future_years_are_not_guessed():
    """svmn.dk: 'Fastlægges senere' for 2026 and 2027; SKAT sets them in December."""
    for year in (2026, 2027):
        assert "restskat_procenttillaeg" not in load_year(year)
        assert "December" in load_year(year)["restskat_indregningsgraense"].note


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_pension_caps_are_per_person_across_all_schemes(year):
    """PBL § 16, stk. 1 ('i alt'; employer payments to aldersopsparing reduce the grundbeløb;
    each institution only checks its own) and stk. 2 ('i alt ... for hver person')."""
    f = load_year(year)
    rate = f["ratepension_max_indskud"].note
    assert "§ 16, stk. 2" in rate and "per person" in rate and "all providers" in rate
    for key in ("aldersopsparing_max_indskud", "aldersopsparing_max_indskud_7aar"):
        note = f[key].note or ""
        assert "§ 16, stk. 1" in note and "per person" in note and "employer" in note
