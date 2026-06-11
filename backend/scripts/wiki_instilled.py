"""Shared wiki parser for Instilled Notables tables."""
import re

import requests
from bs4 import BeautifulSoup

WIKI_URL = "https://www.poe2wiki.net/wiki/Instilling"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _clean_wiki_text(text: str) -> str:
    text = re.sub(r"File:[^\s\]]+", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _cell_text(cell) -> str:
    for a in cell.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/wiki/") and not href.startswith("/wiki/File:"):
            t = a.get_text(strip=True)
            if t and len(t) > 2:
                return _clean_wiki_text(t)
    return _clean_wiki_text(cell.get_text(" ", strip=True))


def scrape_instilled_notables() -> list[tuple[str, str]]:
    """Return (name, effect) pairs from poe2wiki Instilling page."""
    r = requests.get(WIKI_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("div", class_="mw-parser-output")
    tables = content.find_all("table") if content else []

    seen: set[str] = set()
    notables: list[tuple[str, str]] = []
    for table in tables:
        header = table.find("th")
        if not header or header.get_text(strip=True).lower() != "name":
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            name = _cell_text(cells[0])
            effect = _clean_wiki_text(cells[1].get_text(" ", strip=True)) if len(cells) > 1 else ""
            if not name or len(name) < 3 or name in seen:
                continue
            if name.lower().startswith("file:"):
                continue
            seen.add(name)
            notables.append((name, effect))
    return notables
