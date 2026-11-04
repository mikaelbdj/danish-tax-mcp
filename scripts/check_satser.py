"""Compare the figures in src/dk_tax/figures/<year>.yaml with skat.dk's rate overview.

skat.dk/hjaelp/satser renders its tables in the browser, but the data is in the page as
JSON (the __NEXT_DATA__ script): one block per year, each item a name and a value such as
"54.100 kr." or "7,5 % / 641.200 kr.". This script maps those items to our figure keys and
prints one line per key: ok, DIFF, missing (mapped, but skat.dk shows no number) or
unmapped (skat.dk has no matching item; check the figure's own source).

A DIFF is a reason to look, not to copy: the YAML cites svmn.dk or the law, which win over
this overview. Exit code 1 if any line is a DIFF.

Usage (from the repository root):
    uv run python scripts/check_satser.py            # every year in both
    uv run python scripts/check_satser.py 2026 2027
"""

import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from dk_tax.loader import Figure, available_years, load_year

URL = "https://skat.dk/hjaelp/satser"
REFORM_YEAR = 2026
AFTER_AM = "skattegrænse efter am-bidrag er fratrukket"


def _mapping(year: int) -> list[tuple[str, list[str]]]:
    """skat.dk item name -> our keys, in the order the values appear in the item."""
    old = year < REFORM_YEAR
    m = [
        ("Personfradrag (fyldt 18 år)", ["personfradrag"]),
        ("Am-bidrag (arbejdsmarkedsbidrag)", ["am_bidrag"]),
        ("Bundskat", ["bundskat"]),
        ("Skatteloft (personlig indkomst)", ["skatteloft"]),
        ("Skatteloft (positiv nettokapitalindkomst)", ["skatteloft_kapitalindkomst"]),
        ("Beskæftigelsesfradrag (procent)", ["beskaeftigelsesfradrag"]),
        ("Beskæftigelsesfradrag (maksimalt)", ["beskaeftigelsesfradrag_max"]),
        ("Jobfradrag (procent)", ["jobfradrag"]),
        ("Jobfradrag (maksimalt)", ["jobfradrag_max"]),
        ("Aktieindkomst (progressionsgrænse)", ["aktieindkomst_progressionsgraense"]),
        (
            "Aktieindkomst (skattesatser under/over progressionsgrænsen)",
            ["aktieindkomst_lav_sats", "aktieindkomst_hoej_sats"],
        ),
        ("Ratepension og ophørende alderspension (maksimumgrænse)", ["ratepension_max_indskud"]),
        ("Aldersopsparing - indtil 7 år før folkepensionsalderen", ["aldersopsparing_max_indskud"]),
        ("Aldersopsparing - fra og med det 7. år før folkepensionsalderen", ["aldersopsparing_max_indskud_7aar"]),
        ("Fradrag for pensionsindbetalinger, mere end 15 år til pension (procent)", ["ekstra_pensionsfradrag"]),
        (
            "Fradrag for pensionsindbetalinger, 15 år eller mindre til folkepension (procent)",
            ["ekstra_pensionsfradrag_15aar"],
        ),
        ("Ejendomsværdiskattesats (indtil progressionsgrænse)", ["ejendomsvaerdiskat_sats"]),
        ("Ejendomsværdiskattesats (over progressionsgrænse)", ["ejendomsvaerdiskat_progressiv_sats"]),
        ("Ejendomsværdiskattesats (progressionsgrænse)", ["ejendomsvaerdiskat_progressionsgraense"]),
        ("Restskat (grænse for indregning)", ["restskat_indregningsgraense"]),
        ("Restskat: Dag-til-dag-rente", ["restskat_dag_til_dag_rente"]),
        ("Restskat: Procenttillæg", ["restskat_procenttillaeg"]),
        (
            "Bundfradrag i positiv nettokapitalindkomst i topskattegrundlaget",
            ["topskat_kapitalindkomst_bundfradrag" if old else "mellemskat_kapitalindkomst_bundfradrag"],
        ),
    ]
    if old:
        m += [
            ("Topskat (til og med 2025)", ["topskat"]),
            ("Topskat (topskattegrænse til og med 2025 efter am-bidrag er fratrukket)", ["topskat_graense"]),
        ]
    else:
        m += [
            (
                "Mellemskat (fra 2026) / skattegrænse efter am-bidrag er fratrukket",
                ["mellemskat", "mellemskat_graense"],
            ),
            ("Topskat (fra 2026) / skattegrænse efter am-bidrag er fratrukket", ["topskat", "topskat_graense"]),
            (
                "Toptopskat (fra 2026) / skattegrænse efter am-bidrag er fratrukket",
                ["toptopskat", "toptopskat_graense"],
            ),
        ]
    return m


# skat.dk shows the maximum ekstra pensionsfradrag as an amount: max grundlag x rate.
DERIVED = [
    (
        "Fradrag for pensionsindbetalinger, mere end 15 år til pension (maksimalt)",
        "ekstra_pensionsfradrag_max_grundlag",
        "ekstra_pensionsfradrag",
    ),
    (
        "Fradrag for pensionsindbetalinger, 15 år eller mindre til folkepension (maksimalt)",
        "ekstra_pensionsfradrag_max_grundlag",
        "ekstra_pensionsfradrag_15aar",
    ),
]


@dataclass
class Row:
    key: str
    status: str  # ok | DIFF | missing | unmapped
    ours: Decimal | None = None
    skat: Decimal | None = None
    item: str = ""


def parse_page(html: str) -> dict[str, dict[str, str]]:
    """{year: {item name: value text}} from the page's __NEXT_DATA__ JSON."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("No __NEXT_DATA__ in the page: the layout of skat.dk/hjaelp/satser has changed")
    out: dict[str, dict[str, str]] = {}

    def walk(o, year=None):
        if isinstance(o, dict):
            if o.get("contentType") == "comparisonIdentifiers":
                year = o.get("name")
            if o.get("contentType") == "comparisionIdentifierItem":  # sic, as on skat.dk
                p = o.get("properties") or {}
                name = ((p.get("subjectLabel") or [{}])[0]).get("name")
                if year and name:
                    out.setdefault(year, {})[name.strip()] = p.get("value") or ""
            for v in o.values():
                walk(v, year)
        elif isinstance(o, list):
            for v in o:
                walk(v, year)

    walk(json.loads(m.group(1)))
    return out


def parse_value(text: str) -> list[Decimal] | None:
    """Numbers in a value text, Danish style ("641.200", "7,5"); None if there are none."""
    text = text.replace("\xa0", " ")
    if re.search(r"[A-Za-zæøåÆØÅ]{3,}", text) and not re.search(r"kr\.|%", text):
        return None  # words without a unit, e.g. "Fastlægges sidst i 2026": not a value yet
    numbers = re.findall(r"\d[\d.]*(?:,\d+)?", text)
    if not numbers:
        return None
    return [Decimal(n.replace(".", "").replace(",", ".")) for n in numbers]


def _ours(figure: Figure) -> Decimal:
    # Rates compare as fractions (skat.dk shows promille rates in percent), amounts as kroner.
    return figure.rate() if figure.unit in ("percent", "permille") else figure.value


def _theirs(figure: Figure, number: Decimal) -> Decimal:
    return number / 100 if figure.unit in ("percent", "permille") else number


def compare(year: int, items: dict[str, str]) -> list[Row]:
    figures = load_year(year)
    rows: dict[str, Row] = {}
    for item, keys in _mapping(year):
        numbers = parse_value(items[item]) if item in items else None
        for i, key in enumerate(keys):
            if key not in figures:
                continue
            ours = _ours(figures[key])
            if numbers is None or len(numbers) != len(keys):
                rows[key] = Row(key, "missing", ours, None, item)
                continue
            theirs = _theirs(figures[key], numbers[i])
            rows[key] = Row(key, "ok" if ours == theirs else "DIFF", ours, theirs, item)
    for item, grundlag, rate in DERIVED:
        if grundlag not in figures or rate not in figures:
            continue
        key = f"{grundlag} x {rate}"
        ours = figures[grundlag].value * figures[rate].rate()
        numbers = parse_value(items[item]) if item in items else None
        if numbers is None:
            rows[key] = Row(key, "missing", ours, None, item)
        else:
            rows[key] = Row(key, "ok" if ours == numbers[0] else "DIFF", ours, numbers[0], item)
    checked_via_derived = {g for _, g, r in DERIVED if f"{g} x {r}" in rows}
    for key in figures:
        if key not in checked_via_derived:
            rows.setdefault(key, Row(key, "unmapped", _ours(figures[key])))
    return list(rows.values())


def main(argv: list[str]) -> int:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = parse_page(resp.read().decode("utf-8"))
    years = [int(a) for a in argv] or [y for y in available_years() if str(y) in items]
    diffs = 0
    for year in years:
        if str(year) not in items:
            print(f"{year}: not on {URL}")
            continue
        print(f"== {year} ({URL})")
        for row in sorted(compare(year, items[str(year)]), key=lambda r: (r.status != "DIFF", r.status, r.key)):
            detail = "" if row.status == "unmapped" else f"  ours {row.ours}  skat.dk {row.skat}"
            print(f"  {row.status:9} {row.key}{detail}")
            diffs += row.status == "DIFF"
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
