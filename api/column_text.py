"""SPIKE (ADR 0003): column-aware position-text extraction for SCHUCHTER.

This module is **additive and off-by-default**: nothing in the production parse
path imports it. It proves the target architecture of ADR 0003 — extracting the
position *Bezeichnung* (description) column directly from the table geometry so
that drawing dimensions (left columns) and prices (right columns) never enter
the text, instead of cleaning them out afterwards with template regexes
(ADR 0002, the current production approach).

The mechanic:

1.  Read the table header words and locate the left x of the ``Bezeichnung``
    column and the left x of the price column (SCHUCHTER labels it
    ``E-Preis``, i.e. *Einzelpreis*). That pair ``[bezeichnung_left,
    einzelpreis_left)`` is the description band.
2.  Read ``page.get_text("words")`` and keep only words whose *left edge* falls
    inside that band, grouped into visual lines by their y-coordinate, ordered
    top-to-bottom then left-to-right.

Word selection uses the word's **left edge (x0)**, not its center: SCHUCHTER
description tokens (e.g. ``DK-Links``) start inside the Bezeichnung column but
can overflow slightly past the price boundary, while prices are right-aligned
and start at/after the price column. Left-edge keeps the former and drops the
latter.

The spike intentionally stays SCHUCHTER-specific and does not reproduce the
production short/long split. Its point is to demonstrate that maße/preise never
enter the band. See ``tests/test_column_text_extraction_spike.py``.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

import fitz

from template_common import normalize_line

# How close two words' y0 may be and still count as the same visual line (pt).
_LINE_CLUSTER_TOLERANCE_PT = 3.0
# Inset (pt) on the RIGHT band boundary so a right-aligned price value whose left
# edge floats a hair below the price-column x is still excluded; the left
# boundary keeps a matching tolerance so description tokens that overflow
# slightly past the Bezeichnung column-left stay included.
_BAND_EPSILON_PT = 0.5

# Header tokens that mark the relevant columns. SCHUCHTER abbreviates the price
# column header to "E-Preis" (Einzelpreis); we accept both spellings.
_BEZEICHNUNG_TOKENS = ("bezeichnung",)
_PRICE_HEADER_TOKENS = ("einzelpreis", "e-preis", "epreis")

# Right-aligned currency value, e.g. "1.265,40" or "(517,35)". Used only to
# locate the *left edge of the price column* from real value tokens: the header
# word "E-Preis" is narrower than its widest values, so the value column starts
# left of the header word and would otherwise leak prices into the band.
_PRICE_VALUE_RE = re.compile(r"^\(?\d{1,3}(?:\.\d{3})*,\d{2}\)?$")


class ColumnBand(NamedTuple):
    """x-range [left, right) of the description column, in PDF points."""

    left: float
    right: float

    def contains_left_edge(self, x0: float) -> bool:
        return self.left - _BAND_EPSILON_PT <= x0 < self.right - _BAND_EPSILON_PT


def _words(page: Any) -> list[tuple]:
    try:
        raw = page.get_text("words")
    except Exception:
        return []
    out: list[tuple] = []
    for word in raw:
        if isinstance(word, (tuple, list)) and len(word) >= 5:
            out.append(tuple(word))
    return out


def _header_left_x(words: list[tuple], tokens: tuple[str, ...]) -> float | None:
    """Smallest x0 of any header word whose text matches one of ``tokens``."""
    candidates: list[float] = []
    for word in words:
        # Exact match (ignoring trailing punctuation like "Bezeichnung:") so a
        # word merely CONTAINING the token (e.g. "Artikelbezeichnung",
        # "Gesamt-E-Preis") cannot pull the column boundary left.
        text = str(word[4]).strip().lower().rstrip(":.")
        if text in tokens:
            try:
                candidates.append(float(word[0]))
            except (TypeError, ValueError):
                continue
    if not candidates:
        return None
    return min(candidates)


def _price_column_left(words: list[tuple]) -> float | None:
    """Left edge of the price-value column on a page (from its value tokens)."""
    candidates = [
        float(word[0])
        for word in words
        if _PRICE_VALUE_RE.match(str(word[4]).strip())
    ]
    return min(candidates) if candidates else None


def description_band(
    words: list[tuple], page_width: float, price_column_left: float | None = None
) -> ColumnBand | None:
    """Detect the description band ``[Bezeichnung-left, price-column-left)``.

    The right boundary is the left edge of the price column. It is taken as the
    smaller of (a) the ``E-Preis`` header word's left x and (b) the leftmost
    right-aligned price *value* on the page (or ``price_column_left`` when the
    caller has measured it document-wide) — because the header word is narrower
    than its widest value, so prices start left of the header.

    ``words`` is the page's pre-parsed ``get_text("words")`` list (parsed once by
    the caller). Returns ``None`` when the header columns cannot be located or
    the band is geometrically implausible, so callers fall back to flat text.

    NB: the Bezeichnung-left detection mirrors the production
    ``extractor._description_column_left_pt`` (used for the image crop); on full
    ADR-0003 integration the two should share one column-geometry primitive.
    """
    if page_width <= 0:
        return None

    bez_left = _header_left_x(words, _BEZEICHNUNG_TOKENS)
    price_header_left = _header_left_x(words, _PRICE_HEADER_TOKENS)
    if bez_left is None or price_header_left is None:
        return None

    price_value_left = price_column_left
    if price_value_left is None:
        price_value_left = _price_column_left(words)
    right = min(price_header_left, price_value_left) if price_value_left is not None else price_header_left

    # Plausibility: Bezeichnung sits right of the drawing/qty columns and left of
    # the prices, the price column sits in the right half of the page, and the
    # band is wide enough to hold text.
    if not (140.0 < bez_left < right):
        return None
    if right <= page_width * 0.45:
        return None
    if right - bez_left < 30.0:
        return None
    return ColumnBand(left=bez_left, right=right)


def _band_words(words: list[tuple], band: ColumnBand) -> list[tuple]:
    return [word for word in words if band.contains_left_edge(float(word[0]))]


def _group_into_lines(words: list[tuple]) -> list[tuple[float, str]]:
    """Cluster band words into visual lines, top-to-bottom, left-to-right.

    Returns ``(y0, line_text)`` tuples.
    """
    ordered = sorted(words, key=lambda w: (float(w[1]), float(w[0])))
    lines: list[list[tuple]] = []
    for word in ordered:
        y0 = float(word[1])
        if lines and abs(y0 - float(lines[-1][0][1])) <= _LINE_CLUSTER_TOLERANCE_PT:
            lines[-1].append(word)
            continue
        lines.append([word])

    rendered: list[tuple[float, str]] = []
    for group in lines:
        group.sort(key=lambda w: float(w[0]))
        text = normalize_line(" ".join(str(w[4]) for w in group))
        if text:
            rendered.append((float(group[0][1]), text))
    return rendered


# Separator row written by SCHUCHTER between positions (a run of dashes). Used to
# split the page's band lines into per-position chunks for the spike.
def _is_separator(line: str) -> bool:
    stripped = normalize_line(line)
    return len(stripped) >= 8 and set(stripped) <= {"-", "—", "_", "–"}


def _is_band_noise(line: str) -> bool:
    """Header/footer band lines that are not part of a position description."""
    lower = normalize_line(line).lower()
    if not lower:
        return True
    if lower in {".", "-"}:
        return True
    if _is_separator(line):
        return True
    if lower in {"bezeichnung", "e-preis", "g-preis", "einzelpreis"}:
        return True
    if lower.startswith(("übertrag:", "uebertrag:")):
        return True
    # Page header "Blatt <n>" / "Blatt <n> von <m>" caught in the band.
    if re.fullmatch(r"blatt(?:\s+\d+)?(?:\s+von\s+\d+)?", lower):
        return True
    return False


def _position_start_ys(words: list[tuple]) -> list[float]:
    """y0 of each position start on a page (the left-column ``Pos.`` marker).

    Mirrors the production anchor idea (``_position_line_art_boxes``): a ``Pos.``
    marker in the far-left column. The header row's ``Pos.`` (which sits on the
    same y as the ``Bezeichnung`` header word) is excluded.
    """
    header_ys = {
        round(float(word[1]), 1)
        for word in words
        if str(word[4]).strip().lower() in _BEZEICHNUNG_TOKENS
    }
    ys: list[float] = []
    for word in words:
        if str(word[4]).strip() != "Pos." or float(word[0]) >= 140.0:
            continue
        y0 = float(word[1])
        if round(y0, 1) in header_ys:
            continue
        ys.append(y0)
    return sorted(ys)


def _page_width(page: Any) -> float:
    rect = getattr(page, "rect", None)
    return float(getattr(rect, "width", 0.0) or 0.0)


def document_description_blocks(pdf_path: str) -> list[list[str]]:
    """Per-position description blocks across the whole document (spike output).

    Band lines are bucketed into the position whose ``[Pos.-start, next-start)``
    y-band they fall in, page by page. Header/separator/``Übertrag:`` noise is
    dropped. Lines above the first position on a page (page header / spec block)
    are not attributed to a position and are excluded from the blocks. A trailing
    position is closed at the next position start (across pages) or document end.
    """
    document = fitz.open(str(pdf_path))
    blocks: list[list[str]] = []
    current: list[str] | None = None
    try:
        # Parse each page's words ONCE; every downstream helper reuses the list.
        pages = [(_words(page), _page_width(page)) for page in document]
    finally:
        document.close()

    # Measure the price-column left edge document-wide so the band boundary is
    # stable across pages (some pages may have no prices).
    price_lefts = [value for value in (_price_column_left(words) for words, _ in pages) if value is not None]
    doc_price_left = min(price_lefts) if price_lefts else None

    for words, page_width in pages:
        band = description_band(words, page_width, price_column_left=doc_price_left)
        if band is None:
            continue
        start_ys = _position_start_ys(words)
        lines = _group_into_lines(_band_words(words, band))
        si = 0
        for y, line in lines:
            # Advance to the position whose band starts at/above this line.
            while si < len(start_ys) and y >= start_ys[si] - _LINE_CLUSTER_TOLERANCE_PT:
                if current is not None:
                    blocks.append(current)
                current = []
                si += 1
            if current is None:
                continue  # line precedes the first position on the page
            if _is_band_noise(line):
                continue
            current.append(line)
    if current:
        blocks.append(current)
    return [block for block in blocks if block]


def document_description_lines(pdf_path: str) -> list[str]:
    """Flat list of all per-position description-band lines (spike output)."""
    return [line for block in document_description_blocks(pdf_path) for line in block]
