"""Evals: does Claude pick the right dk-tax tool, with the right inputs, and cite it?

Each case sends a realistic question to Claude Code in headless mode with only this
clone's dk-tax server attached and no built-in tools, then checks the tool calls in the
stream-json output and the final answer. The wording of the answer is not graded.

It calls Claude with your Claude Code login and costs a little per run (capped per case
by --max-budget-usd), so it is run by hand before a release, not in CI:

    uv run python evals/run_evals.py            # all cases
    uv run python evals/run_evals.py abis jv    # some cases, by name
"""

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PREFIX = "mcp__dk-tax__"
BUDGET_USD = "0.50"
CITES = re.compile(r"svmn|skat\.dk|info\.skat|retsinformation|kilde|source|§|juridiske vejledning|JV", re.I)


@dataclass
class Case:
    name: str
    prompt: str
    tool: str
    """A tool that must be called (without the mcp__dk-tax__ prefix)."""
    inputs: dict = field(default_factory=dict)
    """Inputs one call of `tool` must have; a callable value is a test on the input."""
    forbid: list[str] = field(default_factory=list)
    year: str | None = None
    """The income year the answer must mention."""


CASES = [
    Case(
        "figures",
        "Hvad er topskattegrænsen i 2027?",
        tool="get_figures",
        inputs={"year": 2027},
        year="2027",
    ),
    Case(
        "payslip",
        "Jeg får 60.000 kr. om måneden i løn i 2026, bor i Aarhus og er ikke medlem af folkekirken. "
        "Hvad bliver min trækprocent og mit månedsfradrag?",
        tool="estimate_payslip",
        inputs={"year": 2026, "monthly_salary": 60000, "folkekirke_member": False},
        year="2026",
    ),
    Case(
        "unmarried",  # trap: cohabiting but not married is taxed as two singles
        "Min kæreste og jeg bor sammen i Odense, men vi er ikke gift. Jeg tjener 300.000 kr. om året og "
        "min kæreste 500.000 kr. Ingen af os er medlem af folkekirken. Hvad betaler vi hver i skat i 2026?",
        tool="estimate_salary_tax",
        inputs={"year": 2026},
        forbid=["estimate_couple_tax"],
        year="2026",
    ),
    Case(
        "couple",
        "Vi er gift og bor i København. Jeg tjener 700.000 kr. om året, min ægtefælle har ingen indkomst. "
        "Ingen af os er medlem af folkekirken. Hvad bliver vores samlede skat i 2026?",
        tool="estimate_couple_tax",
        inputs={"year": 2026, "spouse_2": lambda s: isinstance(s, dict) and s.get("gross_salary") == 0},
        year="2026",
    ),
    Case(
        "property",  # trap: the 2026 tax uses the 2025 valuation, not the 2026 one
        "Vi overtager en lejlighed i Aarhus den 1. april 2026. Den offentlige vurdering pr. 1. januar 2025 "
        "er en ejendomsværdi på 3.500.000 kr. og en grundværdi på 800.000 kr.; pr. 1. januar 2026 er den "
        "3.900.000 kr. og 850.000 kr. Hvad bliver ejendomsværdiskat og grundskyld for 2026?",
        tool="estimate_property_tax",
        inputs={"year": 2026, "ejendomsvaerdi": 3500000, "grundvaerdi": 800000, "overtagelsesdag": "2026-04-01"},
        year="2026",
    ),
    Case(
        "shares",
        "Jeg har solgt børsnoterede aktier med en gevinst på 120.000 kr. i 2026. Jeg er ugift. "
        "Hvad skal jeg betale i aktieskat?",
        tool="estimate_share_income_tax",
        inputs={"year": 2026, "boersnoteret_udbytte_gevinst": 120000},
        year="2026",
    ),
    Case(
        "abis",
        "Er ETF'en med ISIN IE00B4L5Y983 på positivlisten for 2026, og hvordan beskattes den så?",
        tool="lookup_abis",
        inputs={"query": "IE00B4L5Y983", "year": 2026},
        year="2026",
    ),
    Case(
        "lager",
        "Jeg ejer ETF'en iShares Core MSCI World (ISIN IE00B4L5Y983) i et almindeligt depot. Den var 200.000 kr. "
        "værd 1. januar 2026 og 230.000 kr. 31. december 2026, og jeg købte for 20.000 kr. mere i løbet af året. "
        "Hvad skal jeg beskattes af for 2026?",
        tool="estimate_lager_gains",
        inputs={"year": 2026},
        year="2026",
    ),
    Case(
        "jv",
        "Hvad står der i Den juridiske vejledning, afsnit C.A.8.2? Giv et kort resumé med link.",
        tool="get_jv_section",
        inputs={"section": lambda s: str(s).upper() == "C.A.8.2"},
    ),
]


def tool_calls(lines: list[str]) -> tuple[list[tuple[str, dict]], str, float]:
    """(tool name, input) for every dk-tax call, the final answer, and the cost in USD."""
    calls, answer, cost = [], "", 0.0
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name", "").startswith(PREFIX):
                    calls.append((block["name"].removeprefix(PREFIX), block.get("input") or {}))
        elif ev.get("type") == "result":
            answer = ev.get("result") or ""
            cost = float(ev.get("total_cost_usd") or 0)
    return calls, answer, cost


def _matches(expected, actual) -> bool:
    if callable(expected):
        return bool(expected(actual))
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            return int(actual) == expected
        except (TypeError, ValueError):
            return False
    return actual == expected


def check(case: Case, calls: list[tuple[str, dict]], answer: str) -> list[str]:
    """Problems found; an empty list means the case passed."""
    problems = []
    used = [name for name, _ in calls]
    wanted = [inp for name, inp in calls if name == case.tool]
    if not wanted:
        problems.append(f"did not call {case.tool} (called: {', '.join(used) or 'nothing'})")
    elif not any(all(_matches(v, inp.get(k)) for k, v in case.inputs.items()) for inp in wanted):
        problems.append(f"{case.tool} inputs {wanted} do not match {case.inputs}")
    for name in case.forbid:
        if name in used:
            problems.append(f"called {name}, which this case must not use")
    if not CITES.search(answer):
        problems.append("the answer cites no source")
    if case.year and case.year not in answer:
        problems.append(f"the answer does not mention the income year {case.year}")
    return problems


def run(case: Case, workdir: Path, config: Path) -> tuple[list[str], float]:
    cmd = [
        "claude", "-p", case.prompt,
        "--mcp-config", str(config), "--strict-mcp-config",
        "--tools", "", "--allowedTools", "mcp__dk-tax",
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--max-budget-usd", BUDGET_USD,
    ]  # fmt: skip
    out = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=600)
    calls, answer, cost = tool_calls(out.stdout.splitlines())
    problems = check(case, calls, answer)
    if out.returncode and not answer:
        problems.append(f"claude exited {out.returncode}: {out.stderr.strip()[:300]}")
    return problems, cost


def main(names: list[str]) -> int:
    cases = [c for c in CASES if not names or c.name in names]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)  # empty: no CLAUDE.md, no project settings
        config = workdir / "mcp.json"
        server = {"command": "uv", "args": ["run", "--directory", str(REPO), "dk-tax"]}
        config.write_text(json.dumps({"mcpServers": {"dk-tax": server}}))
        failed, total = 0, 0.0
        for case in cases:
            problems, cost = run(case, workdir, config)
            total += cost
            print(f"{'PASS' if not problems else 'FAIL'}  {case.name}  (${cost:.2f})")
            for p in problems:
                print(f"      {p}")
            failed += bool(problems)
    print(f"{len(cases) - failed}/{len(cases)} passed, ${total:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
