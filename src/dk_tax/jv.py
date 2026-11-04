"""Den juridiske vejledning (JV): fetch one section's current text from info.skat.dk.

info.skat.dk addresses pages by an internal oid, not by section number, and the menu
loads in the browser. Each section page links its subsections, though, so a section is
found by walking down from its main part (C.A, C.B, ...), checking every step against the
page title (menu labels can also point at cross-references). The oids of the 22 main
parts were looked up and checked by title on 2026-11-04; an oid stays the same across
editions. Resolved oids are cached on disk; the text itself is always fetched live, so
it is the current edition.

The text belongs to Skatteforvaltningen: it is returned for quoting and citing, not
stored or shipped.
"""

import html
import json
import re

from pydantic import BaseModel

from dk_tax import online

BASE = "https://info.skat.dk/data.aspx?oid="
MAIN_PARTS = {
    "A.A": 74261, "A.B": 2061657, "A.C": 1919724, "A.D": 2048228,
    "C.A": 1920415, "C.B": 1945976, "C.C": 1920857, "C.D": 1899816, "C.E": 125, "C.F": 1977250,
    "C.G": 5585, "C.H": 1948070, "C.I": 934, "C.J": 68675, "C.K": 69325,
    "D.A": 1921126, "D.B": 1976930, "E.A": 1921338, "E.B": 2048578,
    "F.A": 2229597, "G.A": 9672, "H.A": 2048240,
}  # fmt: skip
SECTION = re.compile(r"[A-H]\.[A-K](\.\d+)*")
MAX_CHARS = 20_000


class JvSection(BaseModel):
    section: str
    title: str
    edition: str | None
    """E.g. 'Den juridiske vejledning 2026-2' (two editions a year)."""
    url: str
    text: str
    """The section text without the site's navigation, cut at MAX_CHARS."""
    truncated: bool


def _page(oid: int) -> str:
    return online.fetch(BASE + str(oid)).decode("utf-8")


def _title(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    t = " ".join(html.unescape(m.group(1)).split()) if m else ""
    return t.removesuffix(" - info.skat.dk")


def _is(page: str, code: str) -> bool:
    return _title(page).startswith(code + " ")


def _children(page: str, code: str) -> list[int]:
    """oids of links labelled exactly `code`, in page order, without repeats."""
    found = []
    for oid, label in re.findall(r'<a[^>]+href="[^"]*oid=(\d+)[^"]*"[^>]*>(.*?)</a>', page, re.S):
        label = " ".join(html.unescape(re.sub("<[^>]+>", " ", label)).split())
        if label == code and int(oid) not in found:
            found.append(int(oid))
    return found


def _cache() -> dict[str, int]:
    path = online.cache_dir() / "jv_oids.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _remember(code: str, oid: int) -> None:
    path = online.cache_dir() / "jv_oids.json"
    known = _cache()
    known[code] = oid
    path.write_text(json.dumps(known, indent=0, sort_keys=True))


def _resolve(code: str) -> tuple[int, str]:
    """The oid and page of a section, walking down from its main part."""
    known = _cache()
    if code in known:
        page = _page(known[code])
        if _is(page, code):
            return known[code], page
    main = ".".join(code.split(".")[:2])
    if main not in MAIN_PARTS:
        raise LookupError(f"{code}: unknown main part {main}; JV has {', '.join(MAIN_PARTS)}")
    oid, page = MAIN_PARTS[main], _page(MAIN_PARTS[main])
    parts = code.split(".")
    for depth in range(3, len(parts) + 1):
        step = ".".join(parts[:depth])
        for candidate in _children(page, step):
            candidate_page = _page(candidate)
            if _is(candidate_page, step):
                oid, page = candidate, candidate_page
                break
        else:
            raise LookupError(f"{code}: no section {step} under {_title(page)} ({BASE}{oid})")
    _remember(code, oid)
    return oid, page


def _text(page: str, heading: str) -> str:
    end = page.find("Print aktuel side")
    seg = page[:end] if end >= 0 else page
    seg = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", seg)
    seg = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|table|ul|ol)>", "\n", seg)
    seg = html.unescape(re.sub(r"<[^>]+>", "", seg))
    lines = [line for line in (" ".join(x.split()) for x in seg.splitlines()) if line]
    starts = [i for i, line in enumerate(lines) if line == heading]
    body = lines[starts[-1] + 1 :] if starts else lines
    return "\n".join(line for line in body if "data hentes fra serveren" not in line)


def get_section(section: str) -> JvSection:
    code = section.strip().upper()
    if not SECTION.fullmatch(code):
        raise LookupError(f"{section!r} is not a JV section number like C.A.8.2")
    oid, page = _resolve(code)
    heading = _title(page)
    edition = re.search(r"Den juridiske vejledning \d{4}-\d", page)
    text = _text(page, heading)
    return JvSection(
        section=code,
        title=heading.removeprefix(code).strip(),
        edition=edition.group(0) if edition else None,
        url=BASE + str(oid),
        text=text[:MAX_CHARS],
        truncated=len(text) > MAX_CHARS,
    )
