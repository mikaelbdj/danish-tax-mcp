"""Positivliste (ABIS) and Den juridiske vejledning lookups, offline.

The network is replaced by fixtures with the same structure as the real pages and file
(skat.dk IFPA page and ABIS Excel, info.skat.dk JV pages, as fetched 2026-11-04).
"""

from datetime import date

import openpyxl
import pytest

from dk_tax import abis, jv, online

IFPA_HTML = """<html><body>
<p>Liste over aktiebaserede investeringsselskaber</p>
<a href="/media/ej3fviwc/november-2026-abis-liste-2021-2026.xlsx">
Liste over aktiebaserede investeringsselskaber (offentliggjort den 3. november 2026)</a>
</body></html>"""

HEADER = (
    "Skattemæssigt hjemsted/Tax residence",
    "ISIN-kode/-Code",
    "Navn andelsklasse/Name Shareclass",
    "LEI-kode/-Code",
    "CVR/SE/TIN",
    "Navn afdeling/Name Sub-fund",
    "TIN",
    "Navn/Name",
    "Registrerede år/Registered ",
    "Ikke registrerede år/Deregistered",
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def abis_xlsx(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Forside"
    ws = wb.create_sheet("2026")
    ws.append(HEADER)
    # values as in the real file: '[tom]' for empty, years as text, int or (Excel's doing) a float
    ws.append(("Denmark (DK)", "DK0060502631", "Formuepleje LimiTTellus", "[tom]", 39757206,
               "Formuepleje LimiTTellus", "[tom]", "[tom]", "2020,2021,2022,2023,2024,2025,2026", None))  # fmt: skip
    ws.append(("Ireland (IE)", "IE00B4L5Y983", "iShares Core MSCI World UCITS ETF", "[tom]", "[tom]",
               "[tom]", "[tom]", "iShares plc", 2026, 2020.2021))  # fmt: skip
    ws.append(("Denmark (DK)", "DK0060096030", "Nordea Invest Stabile Aktier Akkumulerende KL", "[tom]", 30170954,
               "[tom]", "[tom]", "[tom]", 2020.2021, "2022,2023,2024,2025,2026"))  # fmt: skip
    path = tmp_path / "abis.xlsx"
    wb.save(path)
    return path.read_bytes()


@pytest.fixture
def fake_net(monkeypatch, abis_xlsx):
    calls = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if url == abis.IFPA_URL:
            return IFPA_HTML.encode()
        if url.endswith(".xlsx"):
            return abis_xlsx
        if "info.skat.dk" in url:
            return JV_PAGES[int(url.split("oid=")[1])].encode()
        raise AssertionError(url)

    monkeypatch.setattr(online, "fetch", fetch)
    return calls


# --- ABIS -----------------------------------------------------------------------------


def test_finds_the_current_list_on_the_ifpa_page():
    link, published = abis.find_list(IFPA_HTML)
    assert link == "https://skat.dk/media/ej3fviwc/november-2026-abis-liste-2021-2026.xlsx"
    assert published == date(2026, 11, 3)


def test_isin_on_the_list(cache, fake_net):
    r = abis.lookup("IE00B4L5Y983", 2026)
    assert r.on_list is True
    assert r.matches[0].registered_years == [2026]
    assert r.matches[0].deregistered_years == [2020, 2021]  # 2020.2021 in the cell
    assert r.published == date(2026, 11, 3)
    assert r.source.endswith(".xlsx")


def test_deregistered_fund_is_not_on_the_list_for_the_year(cache, fake_net):
    r = abis.lookup("DK0060096030", 2026)
    assert r.matches and r.on_list is False


def test_unknown_isin(cache, fake_net):
    r = abis.lookup("US0378331005", 2026)
    assert r.matches == [] and r.on_list is False


def test_name_search(cache, fake_net):
    r = abis.lookup("limittellus", 2026)
    assert [m.isin for m in r.matches] == ["DK0060502631"]
    assert r.on_list is None  # a name search does not decide one fund


def test_year_without_a_sheet(cache, fake_net):
    with pytest.raises(LookupError, match="2026"):
        abis.lookup("IE00B4L5Y983", 2019)


def test_list_is_cached(cache, fake_net):
    abis.lookup("IE00B4L5Y983", 2026)
    abis.lookup("DK0060096030", 2026)
    assert sum(u.endswith(".xlsx") for u in fake_net) == 1


# --- Den juridiske vejledning ----------------------------------------------------------


def jv_page(code_title, links=(), body=()):
    a = "".join(f'<a href="data.aspx?oid={oid}&amp;vid=0">{label}</a>' for label, oid in links)
    b = "".join(f"<p>{p}</p>" for p in body)
    return f"""<html><head><title>{code_title} - info.skat.dk</title></head><body>
<p>Den juridiske vejledning 2026-2</p><p>{code_title}</p><div id="nav">{a}</div>
<h1>{code_title}</h1>{b}<a href="#">Print aktuel side</a><p>Kolofon</p></body></html>"""


JV_PAGES = {
    1920415: jv_page("C.A Personbeskatning", [("C.A.8", 1976881), ("C.A.9", 1976904)]),
    # 1948975 is a cross-reference also labelled C.A.8.2 in the menu: the title check rejects it
    1976881: jv_page("C.A.8 Beskatning af ægtefæller", [("C.A.8.2", 1948975), ("C.A.8.2", 1976883)]),
    1948975: jv_page("C.H.3 Ejendomsavancebeskatning"),
    1976883: jv_page(
        "C.A.8.2 Ægtefællers skatteberegning",
        body=["Som udgangspunkt beregnes ægtefællers skat efter samme regler", "Se <a>PSL § 8 a</a>, stk. 4."],
    ),
}


def test_walks_down_to_a_section_and_checks_titles(cache, fake_net):
    s = jv.get_section("c.a.8.2")
    assert s.section == "C.A.8.2"
    assert s.title == "Ægtefællers skatteberegning"
    assert s.edition == "Den juridiske vejledning 2026-2"
    assert s.url == "https://info.skat.dk/data.aspx?oid=1976883"
    assert s.text.startswith("Som udgangspunkt beregnes")
    assert "Se PSL § 8 a, stk. 4." in s.text  # links do not break lines
    assert "Print aktuel side" not in s.text


def test_resolved_sections_are_cached(cache, fake_net):
    jv.get_section("C.A.8.2")
    fake_net.clear()
    jv.get_section("C.A.8.2")
    assert fake_net == ["https://info.skat.dk/data.aspx?oid=1976883"]


def test_unknown_section(cache, fake_net):
    with pytest.raises(LookupError, match="C.A.8.7"):
        jv.get_section("C.A.8.7")
    with pytest.raises(LookupError, match="main part"):
        jv.get_section("B.A.1")  # well formed, but JV has no B parts
