"""The eval checker (evals/run_evals.py) on canned Claude Code stream-json output.

The evals themselves call Claude and are run by hand; this only tests the checking logic.
"""

import importlib.util
import json
from pathlib import Path

_path = Path(__file__).parent.parent / "evals" / "run_evals.py"
_spec = importlib.util.spec_from_file_location("run_evals", _path)
run_evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_evals)


def stream(*tool_uses, answer="Ifølge svmn.dk er det 800.500 kr. i 2027.", cost=0.04):
    lines = [json.dumps({"type": "system", "subtype": "init"})]
    for name, inp in tool_uses:
        block = {"type": "tool_use", "name": f"mcp__dk-tax__{name}", "input": inp}
        lines.append(json.dumps({"type": "assistant", "message": {"content": [block]}}))
    lines.append(json.dumps({"type": "result", "result": answer, "total_cost_usd": cost}))
    return lines


CASES = {c.name: c for c in run_evals.CASES}


def test_parses_calls_answer_and_cost():
    calls, answer, cost = run_evals.tool_calls(stream(("get_figures", {"year": 2027, "keys": ["topskat_graense"]})))
    assert calls == [("get_figures", {"year": 2027, "keys": ["topskat_graense"]})]
    assert "800.500" in answer
    assert cost == 0.04


def test_a_good_run_passes():
    calls, answer, _ = run_evals.tool_calls(stream(("list_figures", {"year": 2027}), ("get_figures", {"year": 2027})))
    assert run_evals.check(CASES["figures"], calls, answer) == []


def test_wrong_tool_wrong_input_forbidden_tool_and_no_citation_are_reported():
    calls, _, _ = run_evals.tool_calls(stream(("get_figures", {"year": 2026})))
    assert "do not match" in run_evals.check(CASES["figures"], calls, "Det er 2027.")[0]
    calls, _, _ = run_evals.tool_calls(stream(("estimate_couple_tax", {"year": 2026})))
    problems = run_evals.check(CASES["unmarried"], calls, "Det bliver en del i 2026.")
    assert any("did not call estimate_salary_tax" in p for p in problems)
    assert any("must not use" in p for p in problems)
    assert any("cites no source" in p for p in problems)


def test_numbers_may_arrive_as_strings_and_callables_check_inputs():
    calls, answer, _ = run_evals.tool_calls(
        stream(
            ("estimate_couple_tax", {"year": "2026", "spouse_2": {"gross_salary": 0}}),
            answer="Kilde: svmn.dk, indkomståret 2026.",
        )
    )
    assert run_evals.check(CASES["couple"], calls, answer) == []


def test_property_trap_wants_the_2025_valuation():
    calls, answer, _ = run_evals.tool_calls(
        stream(
            (
                "estimate_property_tax",
                {"year": 2026, "ejendomsvaerdi": 3900000, "grundvaerdi": 850000, "overtagelsesdag": "2026-04-01"},
            ),
            answer="Kilde: ejendomsskatteloven § 13, 2026.",
        )
    )
    assert run_evals.check(CASES["property"], calls, answer)  # used the 2026 valuation: fails
