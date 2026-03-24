import re

SPACE_CHARS_RE = re.compile(r"[\u00a0\u2007\u202f]")
MULTI_SPACE_RE = re.compile(r"[ \t]+")
AMOUNT_TOKEN_RE = re.compile(
    r"-?\s*(?:EUR|\u20ac)?\s*[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|-?\s*(?:EUR|\u20ac)?\s*[0-9]+,[0-9]{2}"
)
TWO_AMOUNTS_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})\s+(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})"
)


def normalize_text(text: str) -> str:
    return SPACE_CHARS_RE.sub(" ", text.replace("\r", ""))


def normalize_line(text: str) -> str:
    return MULTI_SPACE_RE.sub(" ", normalize_text(text)).strip()


def extract_amount_tokens(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [MULTI_SPACE_RE.sub(" ", token).strip() for token in AMOUNT_TOKEN_RE.findall(normalized)]


def extract_lv_pos(text: str) -> str | None:
    match = re.search(r"([0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[A-Z])", text)
    if match:
        return match.group(1)
    return None


def extract_dimensions(text: str) -> tuple[str | None, str | None]:
    match_bh = re.search(r"B/H:\s*([0-9.,]+)\s*x\s*([0-9.,]+)", text)
    if match_bh:
        return match_bh.group(1), match_bh.group(2)
    match_newo = re.search(r"Elementbreite:\s*([0-9]+)\s*mm,\s*Elementh[o\u00f6]he:\s*([0-9]+)\s*mm", text)
    if match_newo:
        return match_newo.group(1), match_newo.group(2)
    return None, None


def is_decorative_or_footer(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return True
    if set(lower) <= {"_", "-", "=", " "}:
        return True
    if lower in {"ansicht von außen", "ansicht von innen"}:
        return True
    if lower.startswith(("lupre ai solutions", "webseite:", "e-mail:", "telefon:")):
        return True
    if lower.startswith(("alu-one metallbaupartner gmbh", "heroalstraße", "office@alu-one.at")):
        return True
    if lower.startswith("tel 07682"):
        return True
    if lower.startswith(("rekord vomp gmbh", "au 48, 6134 vomp", "vomp@rekord-fenster.com", "fn 623494d", "kto-nr.")):
        return True
    if lower.startswith("pos.") and "anzahl" in lower and "einzelpreis" in lower:
        return True
    if lower.startswith("bankverbindung"):
        return True
    if lower.startswith(("bankverbindung:", "geschaeftsfuehrer:", "geschäftsführer:", "firmenbuchnr:", "firmengericht:", "uid-nr:")):
        return True
    if lower.startswith(("iban:", "bic:", "blz:", "konto:", "bank:", "kontoinhaber:", "oberbank", "raiba")):
        return True
    if lower.startswith("angebotsnummer:") and "seite" in lower:
        return True
    if lower.startswith("angebot n") and "seite" in lower:
        return True
    if lower.startswith("angebot :") and "seite" in lower:
        return True
    if lower.startswith("angebot ") and any(ch.isdigit() for ch in lower):
        return True
    if lower.startswith("angebot") and "seite" in lower:
        return True
    if lower.startswith("seite ") and " von " in lower:
        return True
    return False


def trim_block_lines(block_lines: list[str], stop_markers: tuple[str, ...]) -> list[str]:
    trimmed: list[str] = []
    for raw in block_lines:
        line = normalize_line(raw)
        if not line:
            continue
        lower = line.lower()
        if any(marker in lower for marker in stop_markers):
            break
        if is_decorative_or_footer(line):
            continue
        trimmed.append(line)
    return trimmed


def extract_first_description(lines: list[str], skip_prefixes: tuple[str, ...], preferred_words: tuple[str, ...] = ()) -> str | None:
    candidates: list[str] = []
    for line in lines:
        clean = normalize_line(line)
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


def page_ref_from_offset(text: str, offset: int) -> int:
    return text[:offset].count("\f") + 1
