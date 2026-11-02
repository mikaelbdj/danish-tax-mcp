"""Load and validate the yearly tax figures shipped in dk_tax/figures/.

Plain Python, no MCP: importable from calculators, tests and notebooks.
"""

from datetime import date
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

Status = Literal["verified", "secondary", "unverified", "proposed"]

FIGURES_DIR = files("dk_tax") / "figures"


class Figure(BaseModel):
    """One tax figure with its evidence. `value` is as printed in the source."""

    # extra="forbid": a typo like `sorce:` in the YAML is an error, not silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: Decimal
    unit: Literal["percent", "DKK"]
    source: str
    verified: date
    status: Status
    note: str | None = None

    def rate(self) -> Decimal:
        """The value as a fraction for calculations: 12.01 percent -> 0.1201."""
        if self.unit != "percent":
            raise ValueError(f"{self.name} is in {self.unit}, not a percentage")
        return self.value / 100


class Kommune(BaseModel):
    """One municipality's rates. Percentages as printed; grundskyld in per mille."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kode: int
    kommuneskat: Decimal
    kirkeskat: Decimal
    skatteloftsnedslag: Decimal
    grundskyldspromille: Decimal


class KommuneTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    verified: date
    status: Status
    kommuner: dict[str, Kommune]


def slug(name: str) -> str:
    """'Lyngby-Taarbæk' -> 'lyngby_taarbaek'. The ASCII rule used for all keys."""
    s = name.strip().lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("-", "_"), (" ", "_"), (".", "")):
        s = s.replace(a, b)
    return s


def available_years() -> list[int]:
    return sorted(int(f.name.removesuffix(".yaml")) for f in FIGURES_DIR.iterdir() if f.name.endswith(".yaml"))


@cache
def load_year(year: int) -> dict[str, Figure]:
    """All figures for an income year, validated. Raises LookupError for unknown years."""
    path = FIGURES_DIR / f"{year}.yaml"
    if not path.is_file():
        raise LookupError(f"No figures for {year}. Available years: {available_years()}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {key: Figure(**record) for key, record in raw.items()}


@cache
def load_kommuner(year: int) -> KommuneTable:
    """The municipal rate table for an income year. Raises LookupError for unknown years."""
    path = FIGURES_DIR / "kommuner" / f"{year}.yaml"
    if not path.is_file():
        raise LookupError(f"No municipal rates for {year}. Available years: {available_years()}")
    return KommuneTable(**yaml.safe_load(path.read_text(encoding="utf-8")))
