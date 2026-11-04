"""Fetching official pages, and a small on-disk cache for what was fetched.

Used by the lookups that read skat.dk and info.skat.dk at call time (abis.py, jv.py).
The cache lives in $XDG_CACHE_HOME/dk-tax (default ~/.cache/dk-tax) and only holds public
data from those sites.
"""

import os
import urllib.request
from pathlib import Path

USER_AGENT = "dk-tax (https://github.com/mikaelbdj/danish-tax-mcp)"
TIMEOUT = 30


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    path = Path(base) / "dk-tax"
    path.mkdir(parents=True, exist_ok=True)
    return path
