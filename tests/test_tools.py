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
        "estimate_couple_tax",
        "lookup_abis",
        "get_jv_section",
        "estimate_lager_gains",
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
    tax = result.structured_content["person"]
    assert result.structured_content["spouse"] is None
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


async def test_estimate_couple_tax_tool():
    """Spouse 2 without income: their whole personfradrag value goes to spouse 1 (§ 10, stk. 2)."""
    result = await call(
        "estimate_couple_tax",
        year=2026,
        kommune="Aarhus",
        spouse_1={"gross_salary": 600_000, "folkekirke_member": False},
        spouse_2={"gross_salary": 0, "folkekirke_member": False, "atp_full_time": False},
    )
    assert not result.is_error, result.content[0].text
    tax = result.structured_content["tax"]
    assert Decimal(tax["overfoert_personfradrag_2_til_1"]) > 0
    assert tax["spouse_2"]["indkomstskat"] == "0.00"
    assert Decimal(tax["skat_i_alt"]) == Decimal(tax["spouse_1"]["skat_i_alt"]) + Decimal(tax["spouse_2"]["skat_i_alt"])


async def test_estimate_couple_tax_rejects_unknown_fields():
    result = await call(
        "estimate_couple_tax",
        year=2026,
        kommune="Aarhus",
        spouse_1={"gross_salary": 600_000, "folkekirke_member": False, "salary": 1},
        spouse_2={"gross_salary": 0, "folkekirke_member": False},
    )
    assert result.is_error
    assert "salary" in result.content[0].text  # names the unknown field


async def test_estimate_share_income_tax_with_spouse():
    """§ 8 a, stk. 4: spouse with 20.000 lends 59.400 of grænse: 63.180 instead of 72.090."""
    result = await call(
        "estimate_share_income_tax",
        year=2026,
        boersnoteret_udbytte_gevinst=200_000,
        spouse={"boersnoteret_udbytte_gevinst": 20_000},
    )
    assert not result.is_error, result.content[0].text
    assert result.structured_content["person"]["skat"] == "63180.00"
    assert result.structured_content["spouse"]["skat"] == "5400.00"


async def test_estimate_property_tax_sale_year():
    """Sold, buyer takes over 6 May: the seller pays 125 of 360 days (LSF 113 2022/23, § 72)."""
    result = await call(
        "estimate_property_tax",
        year=2026,
        kommune="Aarhus",
        ejendomsvaerdi=4_000_000,
        grundvaerdi=1_000_000,
        salg_overtagelsesdag="2026-05-06",
    )
    assert not result.is_error, result.content[0].text
    tax = result.structured_content["tax"]
    assert (tax["ejendomsvaerdiskat_dage"], tax["grundskyld_dage"]) == (125, 125)


async def test_lookup_abis_tool(monkeypatch):
    from datetime import date

    from dk_tax import abis

    def fake(query, year):
        entry = abis.AbisEntry(
            isin="IE00B4L5Y983", name="iShares Core MSCI World UCITS ETF", company="iShares plc",
            tax_residence="Ireland (IE)", registered_years=[2026], deregistered_years=[],
        )  # fmt: skip
        return abis.AbisResult(year=year, query=query, on_list=True, matches=[entry],
                               published=date(2026, 11, 3), source="https://skat.dk/media/x/abis.xlsx")  # fmt: skip

    monkeypatch.setattr(abis, "lookup", fake)
    result = await call("lookup_abis", query="IE00B4L5Y983", year=2026)
    assert not result.is_error, result.content[0].text
    assert result.structured_content["on_list"] is True


async def test_lookup_abis_tool_reports_network_errors(monkeypatch):
    from dk_tax import abis

    def fail(query, year):
        raise OSError("connection refused")

    monkeypatch.setattr(abis, "lookup", fail)
    result = await call("lookup_abis", query="IE00B4L5Y983", year=2026)
    assert result.is_error
    assert "skat.dk" in result.content[0].text


async def test_get_jv_section_tool(monkeypatch):
    from dk_tax import jv

    def fake(section):
        if section != "C.A.8.2":
            raise LookupError(f"{section}: no such section")
        return jv.JvSection(section="C.A.8.2", title="Ægtefællers skatteberegning",
                            edition="Den juridiske vejledning 2026-2",
                            url="https://info.skat.dk/data.aspx?oid=1976883", text="...", truncated=False)  # fmt: skip

    monkeypatch.setattr(jv, "get_section", fake)
    ok = await call("get_jv_section", section="C.A.8.2")
    assert not ok.is_error
    assert ok.structured_content["url"].endswith("oid=1976883")
    bad = await call("get_jv_section", section="C.A.8.99")
    assert bad.is_error and "C.A.8.99" in bad.content[0].text


async def test_estimate_payslip_with_spouse():
    """A spouse without income raises the fradrag (their personfradrag moves across)."""
    args = {"year": 2026, "monthly_salary": 50_000, "kommune": "Aarhus", "folkekirke_member": False}
    single = await call("estimate_payslip", **args)
    married = await call(
        "estimate_payslip",
        **args,
        spouse={"gross_salary": 0, "folkekirke_member": False, "atp_full_time": False},
    )
    assert not married.is_error, married.content[0].text
    s, m = single.structured_content["payslip"], married.structured_content["payslip"]
    assert Decimal(m["overfoert_fra_aegtefaelle"]) > 0
    assert Decimal(m["fradrag_aar"]) > Decimal(s["fradrag_aar"])
    assert m["traekprocent"] == s["traekprocent"]


async def test_server_reports_the_package_version():
    from importlib.metadata import version

    async with Client(server) as client:
        assert client.server_info.version == version("danish-tax-mcp")


async def test_estimate_lager_gains_classifies_by_isin(monkeypatch):
    from datetime import date

    from dk_tax import abis

    looked_up = []

    def fake(query, year):
        looked_up.append((query, year))
        on = query == "IE00B4L5Y983"
        # the bond ETF is on the list but not registered for 2026: a known investeringsselskab
        entry = abis.AbisEntry(isin=query, name="x", company=None, tax_residence=None,
                               registered_years=[2026] if on else [2021], deregistered_years=[])  # fmt: skip
        return abis.AbisResult(year=year, query=query, on_list=on, matches=[entry], published=date(2026, 11, 3),
                               source="https://skat.dk/media/x/abis.xlsx")  # fmt: skip

    monkeypatch.setattr(abis, "lookup", fake)
    result = await call(
        "estimate_lager_gains",
        year=2026,
        funds=[
            {"name": "World ETF", "isin": "IE00B4L5Y983", "value_start": 100_000, "value_end": 125_000},
            {"name": "Bond ETF", "isin": "IE00B3F81R35", "value_start": 50_000, "value_end": 51_000},
        ],
    )
    assert not result.is_error, result.content[0].text
    tax = result.structured_content["tax"]
    assert (tax["aktieindkomst"], tax["kapitalindkomst"]) == ("25000.00", "1000.00")
    assert len(looked_up) == 2
    assert result.structured_content["abis_published"] == "2026-11-03"


async def test_estimate_lager_gains_needs_a_classification():
    result = await call("estimate_lager_gains", year=2026, funds=[{"name": "Some fund", "value_end": 10}])
    assert result.is_error
    assert "aktiebaseret" in result.content[0].text


async def test_estimate_lager_gains_refuses_to_guess_an_isin_not_on_the_list(monkeypatch):
    """Not on the ABIS list at all could be an ordinary share (taxed when sold), not a
    § 19 C fund: ask instead of classifying it as kapitalindkomst."""
    from datetime import date

    from dk_tax import abis

    def fake(query, year):
        return abis.AbisResult(year=year, query=query, on_list=False, matches=[], published=date(2026, 11, 3),
                               source="https://skat.dk/media/x/abis.xlsx")  # fmt: skip

    monkeypatch.setattr(abis, "lookup", fake)
    result = await call(
        "estimate_lager_gains",
        year=2026,
        funds=[{"name": "Apple", "isin": "US0378331005", "value_start": 10_000, "value_end": 12_000}],
    )
    assert result.is_error
    assert "not on SKAT's ABIS list" in result.content[0].text
