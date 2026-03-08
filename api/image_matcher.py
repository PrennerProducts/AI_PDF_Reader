import base64
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

SUPPORTED_VLM_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end <= start:
        return None
    payload = raw_text[start : end + 1]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Unexpected non-object JSON response from VLM endpoint.")
    return parsed


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_image_for_vlm(path: Path, mime_type: str | None) -> tuple[str, bytes]:
    raw = path.read_bytes()
    if mime_type in SUPPORTED_VLM_MIME_TYPES:
        return mime_type, raw

    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        if suffix == ".png":
            return "image/png", raw
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg", raw
        return "image/webp", raw

    # Fallback conversion for formats like JP2.
    with Image.open(path) as img:
        converted = img.convert("RGB")
        buffer = BytesIO()
        converted.save(buffer, format="PNG")
        return "image/png", buffer.getvalue()


def _normalize_selected_indexes(payload: dict[str, Any], max_index: int) -> list[int]:
    raw_indexes = payload.get("selected_indexes")
    indexes: list[int] = []

    if isinstance(raw_indexes, list):
        for value in raw_indexes:
            index = _to_int(value)
            if index is None:
                continue
            if 1 <= index <= max_index:
                indexes.append(index)

    if not indexes:
        best_index = _to_int(payload.get("best_index"))
        if best_index is not None and 1 <= best_index <= max_index:
            indexes = [best_index]

    seen: set[int] = set()
    deduped: list[int] = []
    for index in indexes:
        if index in seen:
            continue
        seen.add(index)
        deduped.append(index)
    return deduped


def rank_line_item_candidates_with_vlm(
    *,
    line_item: dict[str, Any],
    candidate_images: list[dict[str, Any]],
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_VLM_MODEL", "qwen2.5vl:7b")
    if not candidate_images:
        return {
            "ok": False,
            "status": "no_candidates",
            "model": model,
            "error": None,
            "selected_image_ids": [],
            "scores": [],
            "confidence": None,
            "use_multiple": False,
            "raw_text": None,
        }

    encoded_images: list[str] = []
    image_lines: list[str] = []
    ordered_candidates: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidate_images, start=1):
        image_id = _to_int(candidate.get("id"))
        if image_id is None:
            continue
        path_text = str(candidate.get("storage_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            continue
        try:
            mime_type, data = _load_image_for_vlm(path, candidate.get("mime_type"))
        except Exception:
            continue
        encoded_images.append(base64.b64encode(data).decode("ascii"))
        image_lines.append(
            f"{idx}. image_id={image_id}, mime={mime_type}, size={candidate.get('width')}x{candidate.get('height')}, bytes={candidate.get('bytes_size')}"
        )
        ordered_candidates.append(candidate)

    if not encoded_images:
        return {
            "ok": False,
            "status": "no_readable_images",
            "model": model,
            "error": "Could not load candidate image files for VLM request.",
            "selected_image_ids": [],
            "scores": [],
            "confidence": None,
            "use_multiple": False,
            "raw_text": None,
        }

    prompt = (
        "You match a line item description to the most relevant candidate product image(s).\n"
        "Return ONLY valid JSON in this schema:\n"
        "{\n"
        '  "selected_indexes": [int],\n'
        '  "best_index": int|null,\n'
        '  "use_multiple": boolean,\n'
        '  "confidence": number,\n'
        '  "scores": [{"index": int, "score": number, "reason": string}]\n'
        "}\n"
        "Rules:\n"
        "- Indexes are 1-based and refer to the candidate order below.\n"
        "- score and confidence must be in range 0.0..1.0.\n"
        "- If uncertain, still provide best_index and confidence < 0.50.\n"
        "- Do not include any prose outside JSON.\n\n"
        f"Line item:\n"
        f"- position_no: {line_item.get('position_no')}\n"
        f"- lv_pos: {line_item.get('lv_pos')}\n"
        f"- description_short: {line_item.get('description_short')}\n"
        f"- description_long: {line_item.get('description_long')}\n"
        f"- quantity: {line_item.get('quantity')} {line_item.get('unit')}\n"
        f"- page_ref: {line_item.get('page_ref')}\n\n"
        "Candidates:\n"
        f"{chr(10).join(image_lines)}\n"
    )

    payload = {
        "model": model,
        "system": "You are a strict JSON image matcher. Return JSON only.",
        "prompt": prompt,
        "images": encoded_images,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        response = _post_json(f"{base_url}/api/generate", payload, timeout_seconds)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "error",
            "model": model,
            "error": str(exc),
            "selected_image_ids": [],
            "scores": [],
            "confidence": None,
            "use_multiple": False,
            "raw_text": None,
        }

    raw_text = str(response.get("response") or "")
    parsed = _extract_json_object(raw_text)
    if parsed is None:
        return {
            "ok": False,
            "status": "invalid_json",
            "model": model,
            "error": "Could not parse JSON from VLM response.",
            "selected_image_ids": [],
            "scores": [],
            "confidence": None,
            "use_multiple": False,
            "raw_text": raw_text[:2000],
        }

    selected_indexes = _normalize_selected_indexes(parsed, max_index=len(ordered_candidates))
    selected_image_ids: list[int] = []
    for index in selected_indexes:
        image_id = _to_int(ordered_candidates[index - 1].get("id"))
        if image_id is not None:
            selected_image_ids.append(image_id)

    score_rows: list[dict[str, Any]] = []
    raw_scores = parsed.get("scores")
    if isinstance(raw_scores, list):
        for row in raw_scores:
            if not isinstance(row, dict):
                continue
            index = _to_int(row.get("index"))
            if index is None or not (1 <= index <= len(ordered_candidates)):
                continue
            image_id = _to_int(ordered_candidates[index - 1].get("id"))
            if image_id is None:
                continue
            score_rows.append(
                {
                    "index": index,
                    "image_id": image_id,
                    "score": _to_float(row.get("score")),
                    "reason": str(row.get("reason") or "").strip() or None,
                }
            )

    confidence = _to_float(parsed.get("confidence"))
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    use_multiple = bool(parsed.get("use_multiple"))

    return {
        "ok": True,
        "status": "ok",
        "model": model,
        "error": None,
        "selected_image_ids": selected_image_ids,
        "scores": score_rows,
        "confidence": confidence,
        "use_multiple": use_multiple,
        "raw_text": raw_text[:2000],
    }
