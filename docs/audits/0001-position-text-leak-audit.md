# Task A — Read-only Leak Audit (VenDoc description_short / description_long)

## Follow-up re-examination (2026-06-25)

**alu_one (rank 1) was re-examined manually and its flags are FALSE POSITIVES — do NOT clean it.**
Unlike SCHUCHTER, alu_one has no drawing/price-column bleed:
- The flagged `… EUR …` lines are **legitimate prose** (surcharge clauses:
  `Farbmindermengenzuschlag von 33,12 EUR pro RAL-Farbe berechnet.`,
  `… Kleinmengenzuschlag von 55,00 EUR berechnet.`) — only 2 lines, both real text. Stripping them
  would corrupt the description.
- The 49 leading-number/pipe lines (`20 StückU201 | Isolierglas 0,7`, `102 | ESG 4 wärmebesch`,
  `215 | VSG P5A wärmeb. ohne Statik`) are the **glass build-up specification table** — real spec data,
  just pipe-formatted.
- alu_one builds `description_long` from the raw, uncleaned block by design
  (`template_alu_one.extract_line_items`, `"\n".join(full_block_lines)`), so the verbose technical text is
  intentional, not bleed.

Decision (Lukas, 2026-06-25): **leave alu_one untouched** — no confirmed Dragan complaint and no genuine
artifact; cleaning would destroy legit prose + spec data. The heuristic ranking below over-states alu_one;
treat the per-supplier ranks as *candidates to inspect*, not confirmed leaks.

**entholzer (rank 2) re-examined — REAL leak, FIXED.** The drawing column bleeds dimension numbers in
front of description lines (`1750 Alu - Schale …`, `875 875 FLG 74 mm`, `1085 äußere Dichtungen …`).
Corpus split is clean: bled dimensions are always ≥3-digit integers; legitimate leading numbers are 1-2
digit counts (`2 flügeliges Fenster`, `3 Dichtungsebenen`, `2 x Entwässerung`, `1 Stk. …`). Fixed via
`_strip_leading_drawing_dimensions` in `template_entholzer`. Residual: a mid-line bleed `St 1095
Flügelfarbe` (starts with a letter token) is not caught.

**rieder (rank 3) re-examined — FALSE POSITIVES, do NOT clean.** No drawing/price-column bleed. The only
≥3-digit leading line is `100,2 kg / Elementumfang` (a legitimate weight, not a dimension); every other
flagged line is a legit `1 Stk. …` quantity or a `B/H: …,0` decimal that tripped the trailing-single
heuristic. The content is well-structured `Key: value` data; cleaning would risk corrupting it.

**schlotterer (rank 4) & koch (rank 5) re-examined — FALSE POSITIVES, do NOT clean.** Both are clean,
well-structured `Key:value` spec text: no ≥3-digit leading dimension, no trailing dimension pair, no price
token. schlotterer's flags (`10 Einzelkanäle`, `Anzahl Kanalträger:2`) are legit counts; koch's lone
"price" hit is `U-Wert: 1,44 W/m²K` — a thermal value the money heuristic misread as `n,nn` currency.

Net result: across the whole audit, only **SCHUCHTER** (fixed earlier, see [[schuchter-longtext-filtering]])
and **entholzer** had real drawing-column bleed. **alu_one, rieder, schlotterer, koch were all heuristic
false positives** (legit prose, spec tables, quantities, decimals/U-values). Always verify a genuine bleed
before cleaning; the heuristic ranking below is a list of *candidates to inspect*, not confirmed leaks.

## Summary

Parsed **16 PDFs across 8 suppliers** (alu_one 3, entholzer 2, koch 2, muigg 2, newo 1, rieder 1,
schlotterer 2, schuchter 3 — note: 6 PDFs exist for schuchter, capped at 3 per the run policy). **0 parse
failures** — every supplier was routed to its own dedicated template and all PDFs parsed cleanly.
Total positions inspected: **248**. Positions flagged by at least one leak heuristic: **100** (~40%).

The picture is sharply bimodal. **schuchter (0 flagged), muigg (0), newo (0)** are clean. **alu_one** is
by far the worst (48/54 positions, all four leak categories, including real `€`/EUR prices and drawing
dimension pairs). **entholzer (27/27)** and **rieder (9/9)** flag on every position but the bulk of those
are leading "1 Stk." quantity prefixes plus heuristic false positives on legitimate `B/H:` dimension lines.
**schlotterer (13/51)** and **koch (3/11)** are mostly heuristic noise on legit spec lines.

Caveat on heuristics: detectors 2/3 (trailing numbers) produce false positives on legitimate
dimension/decimal lines such as `B/H: 950,0 x 1000,0` (trailing `,0` triggers the single-digit rule) and
`Anzahl Kanalträger:2`. These are noted per supplier and excluded from the "true leak" judgement.

## Ranked table (most-affected first)

| Rank | Supplier | PDFs | Positions | Flagged | Leak types seen | Example leak (verbatim · field) |
|---|---|---|---|---|---|---|
| 1 | **alu_one** | 3 | 54 | 48 | leading, trailing_pair, trailing_single, **price** | `Farbmindermengenzuschlag von 33,12 EUR pro RAL-Farbe berechnet.` · description_long |
| 2 | **entholzer** | 2 | 27 | 27 | leading, trailing_single, price | `1 Stk. Koppeldicht. G022 grau; Maß:1667` · description_long |
| 3 | **rieder** | 1 | 9 | 9 | leading, trailing_single | `1 Stk. Schiene EHCGS BC02 mit Di FSD002AL, Maß: 1042` · description_long |
| 4 | **schlotterer** | 2 | 51 | 13 | leading, trailing_single | `10 Einzelkanäle, 2 Gruppenkanäle, + 1 Zentralkanal` · description_long |
| 5 | **koch** | 2 | 11 | 3 | trailing_single, price | `Objektposition: Sanitärbereich 1` · description_long |
| 6 | muigg | 2 | 10 | 0 | — | (clean) |
| 7 | newo | 1 | 10 | 0 | — | (clean) |
| 8 | schuchter | 3 | 76 | 0 | — | (clean — already treated) |

## Per-supplier notes

### alu_one — template `alu_one` — WORST, genuine multi-category leaks
- **price (real):** `€`/EUR money and m² area lines leak heavily into description_long:
  `Farbmindermengenzuschlag von 33,12 EUR pro RAL-Farbe berechnet.`, `wird ein Kleinmengenzuschlag von
  55,00 EUR berechnet.`, plus dozens of `Fläche RAL: 107,327 m²` / `Wärmedurchgangskoeffizient (Uw/Ud):
  1,00 W/(m²K)` lines (the `1,00` money-shaped token trips the price rule; the area lines are arguably
  spec, but the EUR surcharge lines are unambiguous price leaks).
- **trailing_pair (real, drawing artifact):** position titles carry a trailing element-number pair, e.g.
  `Fensterelement 27200 mm x 2800 mm 1.1`, `Türelement 4500 mm x 3000 mm 1.3`,
  `Festfeld 23200 mm x 1950 mm 1.10`, `Türelement 2000 mm x 2525 mm 03.02.01` — the `1.1 / 03.02.01`
  drawing position code is leaking into both description_short and description_long.
- **leading (real, quantity prefix glued to text):** `20 StückU201 | Isolierglas 0,7`,
  `102 | ESG 4 wärmebesch`, `215 | VSG P5A wärmeb. ohne Statik`, `22030 Rahmen 72/200_m.PU`. The "Stück"
  count and glass-code numbers are glued to the front of the article text (also missing a space:
  `StückU201`).
- This is the supplier that most clearly needs the SCHUCHTER-style cleaning treatment.

### entholzer — template `entholzer` — every position flagged, mostly leading "1 Stk." prefixes
- **leading:** `1 Stk. Koppeldicht. G022 grau; Maß:1667`, `1 Stck Set für J093 T-Verbinder 88373`,
  `1040 Olive:1 x Fenstergriff weiß`. Quantity-and-code prefixes leak at line start.
- **trailing_single:** `LV-Pos: KiZi 1`, `LV-Pos: KiZi 2` — a position/LV reference number leaking (real).
- **price:** only `Uw = 0,75 W/m2K` (a U-value, money-shaped false positive, not a true price).

### rieder — template `rieder` — all 9 positions, but largely heuristic noise
- **leading (real):** `1 Stk. Schiene EHCGS BC02 mit Di FSD002AL, Maß: 1042`, `1 Stk. Frachtkostenbeitrag`,
  `1 Stk. Baustellenanlieferung bis 50km zzgl.` — "1 Stk." quantity prefix at line start.
- **trailing_single (FALSE POSITIVE):** the 10 flagged lines are all legitimate `B/H: 950,0 x 1000,0`
  dimension lines — the trailing `,0` decimal trips the single-digit rule. Not a real leak.

### schlotterer — template `schlotterer` — 13/51, mixed
- **leading (real):** `10 Einzelkanäle, 2 Gruppenkanäle, + 1 Zentralkanal`, `1 waagrechte Sprosse` —
  borderline; these read as legitimate sentences that happen to start with a count.
- **trailing_single:** `Anzahl Kanalträger:2`, `Gesamtstückzahl IGI Schieberahmen:1` (real reference
  numbers); `Gesamtgewicht in kg:164.910, 0` (false positive — trailing `, 0` of a weight value).

### koch — template `koch` — 3/11, minor
- **trailing_single (real-ish):** `Objektposition: Sanitärbereich 1` (an object/section index).
- **price (false positive):** `... Schalldämmwert RW: 41 dB, ..., U-Wert: 1,44 W/m²K` — the `1,44`
  money-shaped token, not an actual price.

### muigg — template `muigg` — CLEAN (0 flagged across 10 positions).
### newo — template `newo` — CLEAN (0 flagged across 10 positions).
### schuchter — template `schuchter` — CLEAN (0 flagged across 76 positions, 3 PDFs). The existing
SCHUCHTER cleaning (leading-number strip, B/H normalization, trailing drawing-number strip) is holding.

## Worst examples (verbatim, grouped by leak category)

**PRICE (most serious — real money leaking):**
1. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 30 · description_long — `Farbmindermengenzuschlag von 33,12 EUR pro RAL-Farbe berechnet.`
2. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 31 · description_long — `wird ein Kleinmengenzuschlag von 55,00 EUR berechnet.`

**TRAILING_PAIR (drawing position-code / dimension pair leaking):**
3. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 1 · description_short — `Fensterelement 27200 mm x 2800 mm 1.1`
4. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 11 · description_short — `Fensterelemente 23200 mm x 1950 mm 1.10`
5. alu_one · `Angebot A2506340MC-1.pdf` · pos 0 · description_short — `Türelement 2000 mm x 2525 mm 03.02.01`

**LEADING (bare number/code glued to start of article text):**
6. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 1 · description_long — `20 StückU201 | Isolierglas 0,7`
7. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 1 · description_long — `215 | VSG P5A wärmeb. ohne Statik`
8. alu_one · `Angebot 2400061DL-1_i.pdf` · pos 11 · description_long — `22030 Rahmen 72/200_m.PU`
9. entholzer · pos n · description_long — `1 Stk. Koppeldicht. G022 grau; Maß:1667`
10. entholzer · pos n · description_long — `1040 Olive:1 x Fenstergriff weiß`
11. rieder · pos n · description_long — `1 Stk. Schiene EHCGS BC02 mit Di FSD002AL, Maß: 1042`
12. schlotterer · pos n · description_long — `10 Einzelkanäle, 2 Gruppenkanäle, + 1 Zentralkanal`

**TRAILING_SINGLE (lone trailing index/reference number):**
13. entholzer · pos n · description_long — `LV-Pos: KiZi 1`
14. koch · pos n · description_long — `Objektposition: Sanitärbereich 1`
15. schlotterer · pos n · description_long — `Anzahl Kanalträger:2`

## Closing assessment — clean vs. needs SCHUCHTER-style treatment

- **CLEAN (no action):** schuchter (already treated), muigg, newo.
- **NEEDS the SCHUCHTER treatment (priority order):**
  1. **alu_one** — the only supplier with genuine leaks in all four categories, including real EUR
     price/surcharge lines, drawing position codes (`1.1`, `03.02.01`) trailing the title, and
     count/glass-code numbers glued to the front of article text. Highest priority.
  2. **entholzer** — pervasive leading `1 Stk./1040`-style quantity-code prefixes and `LV-Pos` index
     leaks; warrants a leading-token strip similar to SCHUCHTER.
  3. **rieder** — needs a leading "1 Stk." strip, BUT first tighten the trailing-single heuristic so it
     stops false-flagging legitimate `B/H: …,0 x …,0` lines.
  4. **schlotterer / koch** — low volume; mostly heuristic noise on legit spec/weight lines. A couple of
     real index leaks (`Anzahl Kanalträger:2`, `Objektposition: … 1`) but minor — review after the big two.
