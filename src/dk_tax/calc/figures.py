"""Figure access for calculators: records every figure read, so results can cite them."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from dk_tax.loader import Figure, Status, load_year


class FigureRef(BaseModel):
    """The evidence for one figure used in a calculation."""

    source: str
    verified: date
    status: Status


class Figures:
    """One year's figures. Every lookup is recorded in `used`, so a result's sources are
    exactly the figures the calculation read."""

    def __init__(self, year: int):
        self._all = load_year(year)
        self.used: dict[str, Figure] = {}

    def __getitem__(self, key: str) -> Figure:
        self.used[key] = self._all[key]
        return self._all[key]

    def value(self, key: str) -> Decimal:
        return self[key].value

    def rate(self, key: str) -> Decimal:
        return self[key].rate()

    def sources(self) -> dict[str, FigureRef]:
        return {k: FigureRef(source=f.source, verified=f.verified, status=f.status) for k, f in self.used.items()}

    def all_verified(self) -> bool:
        return all(f.status == "verified" for f in self.used.values())
