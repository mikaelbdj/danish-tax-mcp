"""Load and validate the yearly tax figures shipped in dk_tax/figures/.

Plain Python, no MCP: importable from calculators, tests and notebooks.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

Status = Literal["verified", "secondary", "unverified", "proposed"]

FIGURES_DIR = files("dk_tax") / "figures"


class Figure(BaseModel):
    """One tax figure with its evidence. `value` is as printed in the source."""

    # extra="forbid": a typo like `sorce:` in the YAML is an error, not silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: Decimal
    unit: Literal["percent", "permille", "DKK"]
    source: str
    verified: date
    status: Status
    note: str | None = None

    def rate(self) -> Decimal:
        """The value as a fraction for calculations: 12.01 percent -> 0.1201, 5.1 permille -> 0.0051."""
        if self.unit == "percent":
            return self.value / 100
        if self.unit == "permille":
            return self.value / 1000
        raise ValueError(f"{self.name} is in {self.unit}, not a rate")


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
    kommuner: Mapping[str, Kommune]

    @field_validator("kommuner", mode="after")
    @classmethod
    def _read_only(cls, v: Mapping[str, Kommune]) -> Mapping[str, Kommune]:
        # frozen stops reassigning the field, not changing the dict; load_kommuner is cached
        return MappingProxyType(dict(v))


def slug(name: str) -> str:
    """'Lyngby-Taarbæk' -> 'lyngby_taarbaek'. The ASCII rule used for all keys."""
    s = name.strip().lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("-", "_"), (" ", "_"), (".", "")):
        s = s.replace(a, b)
    return s


def _years_in(directory) -> list[int]:
    return sorted(int(f.name.removesuffix(".yaml")) for f in directory.iterdir() if f.name.endswith(".yaml"))


def available_years() -> list[int]:
    """Income years with a figures file."""
    return _years_in(FIGURES_DIR)


def available_kommune_years() -> list[int]:
    """Income years with a kommune table (2023 has figures only)."""
    return _years_in(FIGURES_DIR / "kommuner")


@cache
def load_year(year: int) -> Mapping[str, Figure]:
    """All figures for an income year, validated and read-only (the result is cached and
    shared). Raises LookupError for unknown years."""
    path = FIGURES_DIR / f"{year}.yaml"
    if not path.is_file():
        raise LookupError(f"No figures for {year}. Available years: {available_years()}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return MappingProxyType({key: Figure(**record) for key, record in raw.items()})


@cache
def load_kommuner(year: int) -> KommuneTable:
    """The municipal rate table for an income year. Raises LookupError for unknown years."""
    path = FIGURES_DIR / "kommuner" / f"{year}.yaml"
    if not path.is_file():
        raise LookupError(f"No municipal rates for {year}. Available years: {available_kommune_years()}")
    return KommuneTable(**yaml.safe_load(path.read_text(encoding="utf-8")))
