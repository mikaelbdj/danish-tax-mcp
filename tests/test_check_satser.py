"""scripts/check_satser.py: parsing skat.dk/hjaelp/satser and comparing with the YAML.

The page itself is not fetched here (no network in tests); SAMPLE has the same structure
as its embedded __NEXT_DATA__ JSON, with values copied from the page on 2026-11-04.
"""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

_path = Path(__file__).parent.parent / "scripts" / "check_satser.py"
_spec = importlib.util.spec_from_file_location("check_satser", _path)
check_satser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_satser)


def _item(name, value):
    return {
        "contentType": "comparisionIdentifierItem",
        "properties": {"subjectLabel": [{"name": name}], "value": value},
    }


SAMPLE = {
    "props": {
        "children": [
            {
                "contentType": "comparisonIdentifiers",
                "name": "2026",
                "children": [
                    {
                        "contentType": "comparisonIdentifier",
                        "name": "Skat",
                        "properties": {
                            "items": {
                                "items": [
                                    {"content": _item("Personfradrag (fyldt 18 år)", "54.100 kr.")},
                                    {"content": _item("Bundskat", "12,01%")},
                                    {"content": _item("Am-bidrag (arbejdsmarkedsbidrag)", "8 %\t")},
                                    {
                                        "content": _item(
                                            "Mellemskat (fra 2026) / skattegrænse efter am-bidrag er fratrukket",
                                            "7,5 % / 641.200 kr.",
                                        )
                                    },
                                    {"content": _item("Restskat: Procenttillæg", "Fastlægges sidst i 2026")},
                                ]
                            }
                        },
                    }
                ],
            }
        ]
    }
}


def page(data=SAMPLE):
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_items_are_grouped_by_year():
    items = check_satser.parse_page(page())
    assert items["2026"]["Personfradrag (fyldt 18 år)"] == "54.100 kr."
    assert len(items["2026"]) == 5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("54.100 kr.", [Decimal("54100")]),
        ("12,01%", [Decimal("12.01")]),
        ("8 %\t", [Decimal("8")]),
        ("7,5 % / 641.200 kr.", [Decimal("7.5"), Decimal("641200")]),
        ("27/42 %", [Decimal("27"), Decimal("42")]),
        (" 21.480 kr.", [Decimal("21480")]),
        ("Ikke aktuel", None),
        ("Fastlægges sidst i 2026", None),
    ],
)
def test_parse_value(text, expected):
    assert check_satser.parse_value(text) == expected


def test_compare_reports_matches_differences_and_missing():
    rows = check_satser.compare(2026, check_satser.parse_page(page())["2026"])
    by_key = {r.key: r for r in rows}
    assert by_key["personfradrag"].status == "ok"
    assert by_key["mellemskat_graense"].status == "ok"
    assert by_key["bundskat"].status == "ok"
    assert by_key["topskat_graense"].status == "missing"  # not in SAMPLE
    assert by_key["pal_skat"].status == "unmapped"  # skat.dk has no such item


def test_compare_flags_a_difference():
    data = json.loads(json.dumps(SAMPLE))
    data["props"]["children"][0]["children"][0]["properties"]["items"]["items"][0]["content"]["properties"]["value"] = (
        "54.200 kr."
    )
    rows = check_satser.compare(2026, check_satser.parse_page(page(data))["2026"])
    row = next(r for r in rows if r.key == "personfradrag")
    assert row.status == "DIFF"
    assert (row.ours, row.skat) == (Decimal("54100"), Decimal("54200"))
