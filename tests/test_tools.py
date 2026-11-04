"""Contract tests: the tools as an MCP client sees them, over the real protocol (in-process)."""

from decimal import Decimal

import pytest
from mcp import Client

from dk_tax.server import server

pytestmark = pytest.mark.anyio  # every test in this file is async


async def call(tool: str, **args):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


async def test_tool_surface():
    # Renaming or removing a tool breaks permission rules and Claude's habits: make it a conscious change.
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "list_figures",
        "get_figures",
        "get_kommune",
        "estimate_salary_tax",
        "estimate_payslip",
        "estimate_property_tax",
        "estimate_share_income_tax",
    }
    assert set(tools["get_figures"].input_schema["properties"]) == {"year", "keys"}


async def test_result_field_docstrings_reach_the_output_schema():
    # Claude reads field meanings from the outputSchema; pydantic drops attribute docstrings
    # unless use_attribute_docstrings is set.
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for tool, model, field, word in [
        ("estimate_property_tax", "PropertyTax", "vurderingsaar", "before the income year"),
        ("estimate_salary_tax", "SalaryTax", "marginalskat", ""),
        ("estimate_payslip", "YearEnd", "restskat", ""),
    ]:
        description = tools[tool].output_schema["$defs"][model]["properties"][field].get("description", "")
        assert description and word in description, (tool, field)


async def test_get_figures_returns_value_with_evidence():
    result = await call("get_figures", year=2026, keys=["personfradrag", "bundskat"])
    assert not result.is_error
    figures = result.structured_content["figures"]
    assert figures["bundskat"]["value"] == "12.01"  # exact string, not a float
    assert set(figures["personfradrag"]) >= {"value", "unit", "source", "verified", "status"}


async def test_unknown_key_suggests_the_right_one():
    result = await call("get_figures", year=2026, keys=["personfradag"])
    assert result.is_error
    assert "Did you mean: personfradrag" in result.content[0].text


async def test_unknown_year_lists_available_years():
    result = await call("list_figures", year=2031)
    assert result.is_error
    assert "2026" in result.content[0].text


@pytest.mark.parametrize("spelling", ["Aarhus", "aarhus", "Århus", " AARHUS "])
async def test_get_kommune_accepts_spellings(spelling):
    result = await call("get_kommune", year=2026, kommune=spelling)
    assert not result.is_error
    assert result.structured_content["kommune"]["kommuneskat"] == "24.52"


async def test_estimate_salary_tax_tool_matches_calculator():
    result = await call(
        "estimate_salary_tax",
        year=2026,
        gross_salary=900_000,
        kommune="Aarhus",
        folkekirke_member=False,
        atp_full_time=False,
    )
    assert not result.is_error
    tax = result.structured_content["tax"]
    assert tax["indkomstskat"] == "284191.89"  # same as tests/test_salary.py hand calculation
    assert "personfradrag" in tax["sources"]
    assert result.structured_content["kommune"]["kommune"]["name"] == "Aarhus"


async def test_estimate_salary_tax_church_member_pays_kirkeskat():
    args = {"year": 2026, "gross_salary": 900_000, "kommune": "Aarhus", "atp_full_time": False}
    without = await call("estimate_salary_tax", folkekirke_member=False, **args)
    with_ = await call("estimate_salary_tax", folkekirke_member=True, **args)
    diff = Decimal(with_.structured_content["tax"]["indkomstskat"]) - Decimal(
        without.structured_content["tax"]["indkomstskat"]
    )
    assert diff == Decimal("0.0074") * (761_600 - 54_100)  # 0,74 % kirkeskat on (skattepligtig - personfradrag)


async def test_estimate_salary_tax_full_time_atp_by_default():
    result = await call(
        "estimate_salary_tax", year=2026, gross_salary=900_000, kommune="Aarhus", folkekirke_member=False
    )
    tax = result.structured_content["tax"]
    assert tax["am_bidrag_grundlag"] == str(900_000 - 99 * 12)  # own ATP is kept out of the AM-bidrag base
    assert tax["sources"]["atp_loenmodtager_maaned"]["status"] == "verified"


async def test_estimate_payslip_tool():
    result = await call(
        "estimate_payslip",
        year=2026,
        monthly_salary=60_000,
        kommune="Aarhus",
        folkekirke_member=False,
        pension_own_pct=4,
        pension_employer_pct=8,
    )
    assert not result.is_error
    p = result.structured_content["payslip"]
    assert Decimal(p["normal_month"]["pension_own"]) == 2400  # 4 % of 60.000
    assert 30 < p["traekprocent"] < 50


async def test_estimate_payslip_rejects_2025():
    result = await call("estimate_payslip", year=2025, monthly_salary=60_000, kommune="Aarhus", folkekirke_member=False)
    assert result.is_error
    assert "2026" in result.content[0].text


async def test_estimate_payslip_withhold_to_cover():
    result = await call(
        "estimate_payslip",
        year=2026,
        monthly_salary=60_000,
        kommune="Aarhus",
        folkekirke_member=False,
        share_compensation=200_000,
        share_withholding="traekprocent",
    )
    assert not result.is_error
    assert Decimal(result.structured_content["payslip"]["share_vest"]["per_vest"]) == 50_000


async def test_estimate_property_tax_tool():
    """Same case as tests/test_property.py: Aarhus 6 promille, 4.000.000 / 1.000.000, capped grundskyld."""
    result = await call(
        "estimate_property_tax",
        year=2026,
        kommune="Aarhus",
        ejendomsvaerdi=4_000_000,
        grundvaerdi=1_000_000,
        grundskyld_forrige_aar=4_000,
    )
    assert not result.is_error
    tax = result.structured_content["tax"]
    assert tax["ejendomsvaerdiskat"] == "16320.00"
    assert tax["grundskyld"] == "4228.00"
    assert result.structured_content["kommune"]["kommune"]["grundskyldspromille"] == "6"
    assert tax["sources"]["ejendomsvaerdiskat_sats"]["status"] == "verified"
    assert tax["vurderingsaar"] == 2025


async def test_estimate_property_tax_rejects_2025():
    result = await call(
        "estimate_property_tax", year=2025, kommune="Aarhus", ejendomsvaerdi=4_000_000, grundvaerdi=1_000_000
    )
    assert result.is_error
    assert "2026" in result.content[0].text


async def test_estimate_property_tax_purchase_year():
    """Dates arrive as ISO strings over JSON. Bought 1 April: 270/360 of 16.320 and 4.800."""
    result = await call(
        "estimate_property_tax",
        year=2026,
        kommune="Aarhus",
        ejendomsvaerdi=4_000_000,
        grundvaerdi=1_000_000,
        overtagelsesdag="2026-04-01",
    )
    assert not result.is_error
    tax = result.structured_content["tax"]
    assert (tax["ejendomsvaerdiskat"], tax["grundskyld"]) == ("12240.00", "3600.00")
    assert tax["ejendomsvaerdiskat_dage"] == 270


async def test_estimate_share_income_tax_tool():
    """JV C.E.3.2.4.1.2, eksempel 3 over the protocol: -150.000 kr. gives 51.090 negative tax."""
    result = await call("estimate_share_income_tax", year=2026, oevrig_aktieindkomst=-150_000, oevrig_slutskat=30_000)
    assert not result.is_error
    tax = result.structured_content
    assert tax["negativ_skat"] == "51090.00"
    assert tax["negativ_skat_fremfoert_naeste_aar"] == "21090.00"
    assert tax["sources"]["aktieindkomst_progressionsgraense"]["status"] == "verified"


async def test_estimate_share_income_tax_rejects_negative_loss():
    result = await call("estimate_share_income_tax", year=2026, boersnoteret_tab=-5_000)
    assert result.is_error
    assert "positive amounts" in result.content[0].text


async def test_estimate_share_income_tax_unknown_year():
    result = await call("estimate_share_income_tax", year=1999, boersnoteret_udbytte_gevinst=1_000)
    assert result.is_error
    assert "1999" in result.content[0].text
