import re
from typing import Any

SPACE_CHARS_RE = re.compile(r"[\u00a0\u2007\u202f]")
MULTI_SPACE_RE = re.compile(r"[ \t]+")
AMOUNT_TOKEN_RE = re.compile(
    r"-?\s*(?:EUR|\u20ac)?\s*[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|-?\s*(?:EUR|\u20ac)?\s*[0-9]+,[0-9]{2}"
)
TWO_AMOUNTS_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})\s+(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})"
)
PERCENT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*%")
ENTHOLZER_LV_RE = re.compile(r"LV-Pos:\s*([0-9A-Za-z .\-/]+)", flags=re.IGNORECASE)
ENTHOLZER_PRICE_PAIR_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?\s+"
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?"
)


def _normalize_text(text: str) -> str:
    return SPACE_CHARS_RE.sub(" ", text.replace("\r", ""))


def _normalize_line(text: str) -> str:
    return MULTI_SPACE_RE.sub(" ", _normalize_text(text)).strip()


def _extract_amount_tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [MULTI_SPACE_RE.sub(" ", token).strip() for token in AMOUNT_TOKEN_RE.findall(normalized)]


def _classify_amount_line(label: str) -> str:
    lower = label.lower()
    if "mehrwertsteuer" in lower:
        return "vat"
    if "rabatt" in lower or "abzug" in lower:
        return "discount"
    if "zuschlag" in lower or "frachtkosten" in lower or "zustellung" in lower:
        return "surcharge"
    if "angebotssumme" in lower or "gesamtsumme" in lower:
        return "total"
    if "nettosumme" in lower:
        return "net_total"
    if "zwischensumme" in lower or "summe ohne montagekosten" in lower or lower.startswith("summe"):
        return "subtotal"
    return "other"


def _has_amount_trigger(line: str) -> bool:
    lower = line.lower()
    return any(
        word in lower
        for word in (
            "summe",
            "nettosumme",
            "angebotssumme",
            "gesamtsumme",
            "mehrwertsteuer",
            "rabatt",
            "zuschlag",
            "frachtkosten",
            "zustellung",
        )
    )


def _candidate_amount_for_trigger(lines: list[str], idx: int, line: str) -> tuple[str | None, str | None]:
    lower = line.lower()
    direct_tokens = _extract_amount_tokens(line)
    if direct_tokens:
        base = direct_tokens[-2] if len(direct_tokens) > 1 else None
        return direct_tokens[-1], base

    merged: list[str] = []
    for step in range(1, 4):
        if idx + step >= len(lines):
            break
        next_line = lines[idx + step]
        if next_line:
            merged.append(next_line)
    if merged:
        merged_tokens = _extract_amount_tokens(f"{line} {' '.join(merged)}")
        if merged_tokens:
            if "angebotssumme" in lower or "gesamtsumme" in lower:
                return merged_tokens[-1], None
            if "%" in lower or any(word in lower for word in ("rabatt", "zuschlag", "mehrwertsteuer")):
                base = merged_tokens[1] if len(merged_tokens) > 1 else None
                return merged_tokens[0], base
            base = merged_tokens[-2] if len(merged_tokens) > 1 else None
            return merged_tokens[0], base

    lookahead_tokens: list[str] = []
    for step in range(1, 8):
        if idx + step >= len(lines):
            break
        probe = lines[idx + step]
        if not probe:
            continue
        if step > 1 and _has_amount_trigger(probe) and lookahead_tokens:
            break
        tokens = _extract_amount_tokens(probe)
        if tokens:
            lookahead_tokens.extend(tokens)

    if not lookahead_tokens:
        return None, None
    if "angebotssumme" in lower or "gesamtsumme" in lower:
        return lookahead_tokens[-1], None
    return lookahead_tokens[0], None


def extract_amount_lines(text: str) -> list[dict[str, Any]]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    amount_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    sort_order = 0

    for idx, line in enumerate(lines):
        if not line or not _has_amount_trigger(line):
            continue

        amount_raw, base_amount_raw = _candidate_amount_for_trigger(lines, idx, line)
        if not amount_raw:
            continue

        line_type = _classify_amount_line(line)
        if (
            line_type == "surcharge"
            and "zustellung" in line.lower()
            and not _extract_amount_tokens(line)
        ):
            continue
        if line_type == "discount" and not amount_raw.strip().startswith("-"):
            amount_raw = f"-{amount_raw.strip()}"

        key = (line.lower(), amount_raw, line_type)
        if key in seen:
            continue
        seen.add(key)

        percent_match = PERCENT_RE.search(line)
        percent_raw = percent_match.group(1) if percent_match else None
        amount_rows.append(
            {
                "line_type": line_type,
                "label_raw": line,
                "percent_raw": percent_raw,
                "base_amount_raw": base_amount_raw,
                "amount_raw": amount_raw,
                "sort_order": sort_order,
            }
        )
        sort_order += 1

    return amount_rows


def _extract_lv_pos(text: str) -> str | None:
    match = re.search(r"([0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[A-Z])", text)
    if match:
        return match.group(1)
    return None


def _extract_dimensions(text: str) -> tuple[str | None, str | None]:
    match_bh = re.search(r"B/H:\s*([0-9.,]+)\s*x\s*([0-9.,]+)", text)
    if match_bh:
        return match_bh.group(1), match_bh.group(2)
    match_newo = re.search(r"Elementbreite:\s*([0-9]+)\s*mm,\s*Elementh[o\u00f6]he:\s*([0-9]+)\s*mm", text)
    if match_newo:
        return match_newo.group(1), match_newo.group(2)
    return None, None


def _is_decorative_or_footer(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return True
    if set(lower) <= {"_", "-", "=", " "}:
        return True
    if lower.startswith(("bankverbindung:", "geschaeftsfuehrer:", "geschäftsführer:", "firmenbuchnr:", "firmengericht:", "uid-nr:")):
        return True
    if lower.startswith(("iban:", "bic:", "blz:", "konto:", "oberbank", "raiba")):
        return True
    if lower.startswith("angebotsnummer:") and "seite" in lower:
        return True
    if lower.startswith("angebot n") and "seite" in lower:
        return True
    if lower.startswith("seite ") and " von " in lower:
        return True
    return False


def _trim_block_lines(block_lines: list[str], stop_markers: tuple[str, ...]) -> list[str]:
    trimmed: list[str] = []
    for raw in block_lines:
        line = _normalize_line(raw)
        if not line:
            continue
        lower = line.lower()
        if any(marker in lower for marker in stop_markers):
            break
        if _is_decorative_or_footer(line):
            continue
        trimmed.append(line)
    return trimmed


def _extract_first_description(lines: list[str], skip_prefixes: tuple[str, ...], preferred_words: tuple[str, ...] = ()) -> str | None:
    candidates: list[str] = []
    for line in lines:
        clean = _normalize_line(line)
        if not clean:
            continue
        lower = clean.lower()
        if lower.startswith(skip_prefixes):
            continue
        if "b/h:" in lower or "flgnr" in lower:
            continue
        if re.match(r"^[0-9]+(?:[.,][0-9]+)?\s*(stk|st[e\u00fc]ck|lfm)\b", lower):
            continue
        if TWO_AMOUNTS_RE.search(clean):
            continue
        clean = re.sub(r"^(?:EUR|\u20ac)?\s*[0-9][0-9 .]*,[0-9]{2}\s*", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"\s+(?:EUR|\u20ac)?\s*[0-9][0-9 .]*,[0-9]{2}$", "", clean, flags=re.IGNORECASE).strip()
        if clean and re.search(r"[A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc]", clean):
            candidates.append(clean)

    if not candidates:
        return None
    for candidate in candidates:
        lower = candidate.lower()
        if preferred_words and any(word in lower for word in preferred_words):
            return candidate
    return candidates[0]


def _page_ref_from_offset(text: str, offset: int) -> int:
    return text[:offset].count("\f") + 1


def _extract_newo_items(lines: list[str], page_ref: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_indices: list[int] = []

    for idx, line in enumerate(lines):
        if re.match(r"^\d{3}\s+[0-9]+,[0-9]{2}\s+[A-Za-z]+", _normalize_line(line)):
            start_indices.append(idx)

    for offset, start in enumerate(start_indices):
        end = start_indices[offset + 1] if offset + 1 < len(start_indices) else len(lines)
        raw_block = lines[start:end]
        block_lines = _trim_block_lines(
            raw_block,
            (
                "zwischensumme",
                "gesamtsumme",
                "angebotssumme",
                "lieferkondition:",
                "zahlungskondition:",
                "mit sonnigen gru",
            ),
        )
        if not block_lines:
            continue

        header = block_lines[0]
        header_match = re.match(r"^(\d{3})\s+([0-9]+,[0-9]{2})\s+([A-Za-z]+)\s+(.+)$", header)
        if not header_match:
            continue

        position_no = header_match.group(1)
        quantity_raw = header_match.group(2)
        unit = header_match.group(3)
        header_tail = header_match.group(4).strip()
        full_block = "\n".join(block_lines)
        width_raw, height_raw = _extract_dimensions(full_block)
        lv_pos = _extract_lv_pos(header_tail) or _extract_lv_pos(full_block)
        is_alternative = "alternativ" in full_block.lower()

        unit_price_raw = None
        line_total_raw = None
        price_pair = TWO_AMOUNTS_RE.search(header)
        if price_pair:
            unit_price_raw = price_pair.group(1)
            line_total_raw = price_pair.group(2)
            header_tail = TWO_AMOUNTS_RE.sub("", header_tail).strip(" :")
        else:
            for line in block_lines[1:16]:
                price_match = TWO_AMOUNTS_RE.search(line)
                if price_match:
                    unit_price_raw = price_match.group(1)
                    line_total_raw = price_match.group(2)
                    break

        description_short = header_tail
        if re.match(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[A-Z]$", description_short):
            description_short = ""
        if not description_short or description_short.endswith(":") or len(description_short) < 5:
            description_short = _extract_first_description(
                block_lines[1:24],
                skip_prefixes=(
                    "elementbreite:",
                    "modell:",
                    "lamellentyp:",
                    "lamellenfarbe:",
                    "teilung:",
                    "teilbreite",
                    "teilh",
                    "angebotnummer:",
                    "angebotsnummer:",
                ),
                preferred_words=("raffstore", "insektenschutz", "schiebeplissee", "putzkasten"),
            )

        items.append(
            {
                "position_no": position_no,
                "lv_pos": lv_pos,
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": unit,
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": full_block[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )

    return items


def _extract_rieder_prices(block_lines: list[str]) -> tuple[str | None, str | None]:
    for idx, line in enumerate(block_lines):
        if "ep:" in line.lower() or "gp:" in line.lower() or "alternative:" in line.lower():
            start = max(0, idx - 1)
            end = min(len(block_lines), idx + 2)
            snippet = " ".join(block_lines[start:end])
            tokens = _extract_amount_tokens(snippet)
            if len(tokens) >= 2:
                return tokens[0], tokens[-1]

    for line in block_lines:
        pair = TWO_AMOUNTS_RE.search(line)
        if pair:
            return pair.group(1), pair.group(2)

    all_tokens = _extract_amount_tokens("\n".join(block_lines))
    if len(all_tokens) >= 2:
        return all_tokens[-2], all_tokens[-1]
    if len(all_tokens) == 1:
        return all_tokens[0], all_tokens[0]
    return None, None


def _extract_rieder_items(text: str) -> list[dict[str, Any]]:
    normalized_text = _normalize_text(text)
    items: list[dict[str, Any]] = []
    for match in re.finditer(r"(?ms)^Position:\s*(\d+)(.*?)(?=^Position:\s*\d+|\Z)", normalized_text):
        page_ref = _page_ref_from_offset(normalized_text, match.start())
        position_no = match.group(1)
        block = match.group(2).strip()
        if not block:
            continue

        block_lines = _trim_block_lines(
            block.splitlines(),
            (
                "summe ",
                "zwischensumme",
                "nettosumme",
                "angebotssumme",
                "gesamtsumme",
            ),
        )
        if not block_lines:
            continue

        block_text = "\n".join(block_lines)
        qty_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(St[ue\u00fc]ck|Stk\.?|Stk)\b", block_text, flags=re.IGNORECASE)
        quantity_raw = qty_match.group(1) if qty_match else None
        unit = qty_match.group(2).replace(".", "") if qty_match else None

        width_raw = None
        height_raw = None
        bh_match = re.search(r"B/H:\s*([0-9.,]+)\s*x\s*([0-9.,]+)", block_text)
        if bh_match:
            width_raw = bh_match.group(1)
            height_raw = bh_match.group(2)

        description_short = _extract_first_description(
            block_lines,
            skip_prefixes=("ku.pos", "ep:", "gp:", "flgnr", "summe", "zwischensumme"),
            preferred_words=("fenster", "tuer", "t\u00fcre", "fixfenster", "brandschutz", "schema", "dreh", "kipp"),
        )
        unit_price_raw, line_total_raw = _extract_rieder_prices(block_lines)
        is_alternative = "alternativ" in block_text.lower() or "alternative" in block_text.lower()

        items.append(
            {
                "position_no": position_no,
                "lv_pos": None,
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": unit,
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": block_text[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )

    return items


def _extract_entholzer_prices(block_lines: list[str]) -> tuple[str | None, str | None]:
    pair: tuple[str | None, str | None] = (None, None)
    for line in block_lines:
        match = ENTHOLZER_PRICE_PAIR_RE.search(line)
        if match:
            pair = (match.group(1), match.group(2))
    if pair[0] and pair[1]:
        return pair

    all_tokens = _extract_amount_tokens("\n".join(block_lines))
    if len(all_tokens) >= 2:
        return all_tokens[-2], all_tokens[-1]
    return None, None


def _extract_entholzer_items(text: str) -> list[dict[str, Any]]:
    normalized_text = _normalize_text(text)
    items: list[dict[str, Any]] = []
    for match in re.finditer(r"(?ms)^Pos\.\:\s*(\d+)(.*?)(?=^Pos\.\:\s*\d+|\Z)", normalized_text):
        page_ref = _page_ref_from_offset(normalized_text, match.start())
        position_no = match.group(1)
        block = match.group(2).strip()
        if not block:
            continue

        block_lines = _trim_block_lines(
            block.splitlines(),
            (
                "summe ohne montagekosten",
                "zwischensumme",
                "nettosumme",
                "angebotssumme",
                "zahlungsbedingungen:",
            ),
        )
        if not block_lines:
            continue

        block_text = "\n".join(block_lines)
        qty_match = re.search(
            r"([0-9]+(?:[.,][0-9]+)?)\s*(Stk\.?|Stk|St[ue\u00fc]ck|LFM|lfm)\b",
            block_text,
            flags=re.IGNORECASE,
        )
        quantity_raw = qty_match.group(1) if qty_match else None
        unit = qty_match.group(2).replace(".", "") if qty_match else None

        width_raw = None
        height_raw = None
        bh_match = re.search(r"B/H:\s*([0-9.,]+)\s*x\s*([0-9.,]+)", block_text)
        if bh_match:
            width_raw = bh_match.group(1)
            height_raw = bh_match.group(2)

        lv_pos_match = ENTHOLZER_LV_RE.search(block_text)
        lv_pos = lv_pos_match.group(1).strip() if lv_pos_match else None
        is_alternative = "alternativ" in block_text.lower()

        description_short = _extract_first_description(
            block_lines,
            skip_prefixes=(
                "lv-pos:",
                "ep:",
                "gp:",
                "(innenansicht)",
                "angebot n",
            ),
            preferred_words=("aluclip", "festverglasung", "balkont", "dreh-kipp", "kopplungselement"),
        )
        unit_price_raw, line_total_raw = _extract_entholzer_prices(block_lines)

        items.append(
            {
                "position_no": position_no,
                "lv_pos": lv_pos,
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": unit,
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": block_text[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )

    return items


def extract_line_items(text: str, template: str) -> list[dict[str, Any]]:
    normalized_text = _normalize_text(text)
    normalized_lines = [line for line in normalized_text.splitlines() if line.strip()]
    if template == "newo":
        items: list[dict[str, Any]] = []
        pages = normalized_text.split("\f")
        for page_idx, page_text in enumerate(pages, start=1):
            page_lines = [line for line in page_text.splitlines() if line.strip()]
            items.extend(_extract_newo_items(page_lines, page_ref=page_idx))
        return items
    if template == "rieder":
        return _extract_rieder_items(normalized_text)
    if template == "entholzer":
        return _extract_entholzer_items(normalized_text)
    return []
