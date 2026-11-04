"""SKAT's list of aktiebaserede investeringsselskaber (the ABIS list, "positivlisten").

An investeringsselskab (ABL § 19) on the list for a year is aktiebaseret: gains and
dividends are aktieindkomst, taxed yearly on the change in value (ABL § 19 B), and it can
be held on an aktiesparekonto. An investeringsselskab that is not on the list is taxed as
kapitalindkomst. The list says nothing about ordinary shares or about Danish
investeringsforeninger with their own tax rules (minimumsbeskattede, ABL § 21).

Source: skat.dk, "Beviser og aktier i investeringsforeninger og selskaber (IFPA)", which
links one Excel file with a sheet per year. SKAT updates it about monthly and the file's
address changes each time, so the link is read from the page and the file cached a day.
"""

import io
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

from pydantic import BaseModel

from dk_tax import online

IFPA_URL = "https://skat.dk/erhverv/ekapital/vaerdipapirer/beviser-og-aktier-i-investeringsforeninger-og-selskaber-ifpa"
MAX_AGE = 24 * 3600
MAX_MATCHES = 20
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")
MONTHS = ["januar", "februar", "marts", "april", "maj", "juni"]
MONTHS += ["juli", "august", "september", "oktober", "november", "december"]


class AbisEntry(BaseModel):
    isin: str | None
    name: str
    """Share class name, else sub-fund, else company name, as on the list."""
    company: str | None
    tax_residence: str | None
    registered_years: list[int]
    deregistered_years: list[int]


class AbisResult(BaseModel):
    year: int
    query: str
    on_list: bool | None
    """ISIN query: True if the fund is registered as aktiebaseret for the year. None for a
    name search, which can match several funds."""
    matches: list[AbisEntry]
    published: date | None
    """The date SKAT published this version of the list."""
    source: str
    from_cache_after_error: bool = False
    """True if skat.dk could not be reached and an older cached copy was used."""


@dataclass
class _List:
    link: str
    published: date | None
    content: bytes


def find_list(html: str) -> tuple[str, date | None]:
    """The Excel link and its publication date on the IFPA page."""
    m = re.search(r'href="([^"]*abis-liste[^"]*\.xlsx)"', html, re.I)
    if not m:
        raise LookupError(f"No ABIS list link on {IFPA_URL}: the page has changed")
    link = urljoin(IFPA_URL, m.group(1))
    d = re.search(r"offentliggjort den (\d{1,2})\. (\w+) (\d{4})", html[m.start() :], re.I)
    published = None
    if d and d.group(2).lower() in MONTHS:
        published = date(int(d.group(3)), MONTHS.index(d.group(2).lower()) + 1, int(d.group(1)))
    return link, published


def _load() -> tuple[_List, bool]:
    folder = online.cache_dir()
    meta_path, data_path = folder / "abis.json", folder / "abis.xlsx"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() and data_path.exists() else None
    if meta and time.time() - meta["fetched"] < MAX_AGE:
        return _List(meta["link"], _date(meta["published"]), data_path.read_bytes()), False
    try:
        link, published = find_list(online.fetch(IFPA_URL).decode("utf-8"))
        content = data_path.read_bytes() if meta and meta["link"] == link else online.fetch(link)
    except OSError:
        if meta:  # offline: an older copy is better than nothing, and the result says so
            return _List(meta["link"], _date(meta["published"]), data_path.read_bytes()), True
        raise
    data_path.write_bytes(content)
    meta_path.write_text(
        json.dumps({"link": link, "published": published.isoformat() if published else None, "fetched": time.time()})
    )
    return _List(link, published, content), False


def _date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _cell(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "[tom]") else s


def _years(v) -> list[int]:
    if v is None:
        return []
    if isinstance(v, float):  # Excel turned "2020,2021" into 2020.2021
        v = f"{v:.4f}"
    return sorted({int(y) for y in re.findall(r"\d{4}", str(v))})


def _entries(content: bytes, year: int) -> list[AbisEntry]:
    import openpyxl  # here, not at import time: only this lookup needs it

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if str(year) not in wb.sheetnames:
        years = ", ".join(s for s in wb.sheetnames if s.isdigit())
        raise LookupError(f"The ABIS list has no sheet for {year}; it has {years}")
    rows = wb[str(year)].iter_rows(values_only=True)
    next(rows)  # header
    out = []
    for r in rows:
        r = (list(r) + [None] * 10)[:10]
        residence, isin, shareclass, _lei, _cvr, subfund, _tin, company = (_cell(x) for x in r[:8])
        name = shareclass or subfund or company
        if not (isin or name):
            continue
        out.append(
            AbisEntry(
                isin=isin if isin and ISIN.fullmatch(isin) else None,
                name=name or "",
                company=company or subfund,
                tax_residence=residence,
                registered_years=_years(r[8]),
                deregistered_years=_years(r[9]),
            )
        )
    return out


def lookup(query: str, year: int) -> AbisResult:
    """Look up an ISIN (exact) or a fund name (case-insensitive part) in the year's list."""
    lst, stale = _load()
    entries = _entries(lst.content, year)
    q = query.strip()
    if ISIN.fullmatch(q.upper()):
        matches = [e for e in entries if e.isin == q.upper()]
        on_list = any(year in e.registered_years for e in matches)
    else:
        needle = q.lower()
        matches = [e for e in entries if needle in e.name.lower() or needle in (e.company or "").lower()]
        on_list = None
    return AbisResult(
        year=year,
        query=q,
        on_list=on_list,
        matches=matches[:MAX_MATCHES],
        published=lst.published,
        source=lst.link,
        from_cache_after_error=stale,
    )
