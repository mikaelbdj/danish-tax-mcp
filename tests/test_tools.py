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
    assert set(tools) == {"list_figures", "get_figures", "get_kommune", "estimate_salary_tax"}
    assert set(tools["get_figures"].input_schema["properties"]) == {"year", "keys"}


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
    result = await call("estimate_salary_tax", year=2026, gross_salary=900_000, kommune="Aarhus", folkekirke_member=False)
    assert not result.is_error
    tax = result.structured_content["tax"]
    assert tax["indkomstskat"] == "284191.89"  # same as tests/test_salary.py hand calculation
    assert "personfradrag" in tax["sources"]
    assert result.structured_content["kommune"]["kommune"]["name"] == "Aarhus"


async def test_estimate_salary_tax_church_member_pays_kirkeskat():
    args = dict(year=2026, gross_salary=900_000, kommune="Aarhus")
    without = await call("estimate_salary_tax", folkekirke_member=False, **args)
    with_ = await call("estimate_salary_tax", folkekirke_member=True, **args)
    diff = Decimal(with_.structured_content["tax"]["indkomstskat"]) - Decimal(without.structured_content["tax"]["indkomstskat"])
    assert diff == Decimal("0.0074") * (761_600 - 54_100)  # 0,74 % kirkeskat on (skattepligtig - personfradrag)
