#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
  echo "[error] API health check failed on http://localhost:8000/health"
  echo "Start the stack first, for example with ./infra/dev-watch.sh"
  exit 1
fi

python - <<'PY'
import json
import mimetypes
import urllib.request
import uuid
from pathlib import Path

API_BASE = "http://127.0.0.1:8000"
ROOT = Path.cwd()
CASES = [
    {
        "provider": "alu_one",
        "path": ROOT / "samples/pdfs/regression/offers/alu_one/Angebot C2509283TB.pdf",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "C2509283TB",
        "document_date": "2025-11-10",
        "position_count": 9,
        "validation_status": "auto_accept",
    },
    {
        "provider": "entholzer",
        "path": ROOT / "samples/pdfs/regression/offers/entholzer/Angebot 12600422.00 Bernsteiner.pdf",
        "supplier_name": "Entholzer",
        "document_number": "12600422.00",
        "document_date": "2026-02-03",
        "position_count": 18,
        "validation_status": "auto_accept",
    },
    {
        "provider": "rieder",
        "path": ROOT / "samples/pdfs/regression/offers/rieder/AN Rieder F 20252082 BV Achhorner.pdf",
        "supplier_name": "Rieder",
        "document_number": "20252082",
        "document_date": "2025-09-05",
        "position_count": 5,
        "validation_status": "auto_accept",
    },
    {
        "provider": "sr_schauraum",
        "path": ROOT / "samples/pdfs/regression/offers/sr_schauraum/Angebotsnr AN-2025-113 - SR Schauraum GmbH (2).pdf",
        "supplier_name": "Lupre AI Solutions",
        "document_number": "AN-2025-113",
        "document_date": "2025-12-08",
        "position_count": 3,
        "validation_status": "auto_accept",
    },
    {
        "provider": "newo",
        "path": ROOT / "samples/pdfs/regression/offers/newo/AN NEWO BVH Projekt 353 Achhorner.pdf",
        "supplier_name": "NeWo",
        "document_number": "25002995",
        "document_date": "2025-09-04",
        "position_count": 8,
        "validation_status": "auto_accept",
    },
    {
        "provider": "rekord_vomp",
        "path": ROOT / "samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX60326.pdf",
        "supplier_name": "Rekord Vomp GmbH",
        "document_number": "VAX60326",
        "document_date": "2026-02-02",
        "position_count": 14,
        "validation_status": "auto_accept",
    },
    {
        "provider": "schuchter_composite",
        "path": ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260344.pdf",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "A260344",
        "document_date": "2026-03-25",
        "position_count": 4,
        "validation_status": "auto_accept",
    },
    {
        "provider": "schuchter_accessory",
        "path": ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260396.pdf",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "A260396",
        "document_date": "2026-04-03",
        "position_count": 13,
        "validation_status": "auto_accept",
    },
]


def _json_request(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def _upload_pdf(pdf_path: Path) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Sample PDF not found: {pdf_path}")

    boundary = f"----api-canary-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"
    file_bytes = pdf_path.read_bytes()
    payload = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{pdf_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    response = _json_request(
        f"{API_BASE}/upload",
        method="POST",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return int(response["document_id"])


def _process_and_fetch(document_id: int) -> dict:
    _json_request(f"{API_BASE}/process/{document_id}?process_mode=parser_only", method="POST")
    return _json_request(f"{API_BASE}/result/{document_id}")


rows: list[dict[str, object]] = []
errors: list[str] = []

for case in CASES:
    document_id = _upload_pdf(case["path"])
    result = _process_and_fetch(document_id)
    document = result.get("document") or {}
    validation = result.get("validation") or {}
    row = {
        "provider": case["provider"],
        "document_id": document_id,
        "supplier_name": document.get("supplier_name"),
        "document_number": document.get("document_number"),
        "document_date": document.get("document_date"),
        "position_count": len(result.get("line_items") or []),
        "status": document.get("status"),
        "validation_status": validation.get("status"),
    }
    rows.append(row)

    for key in ("supplier_name", "document_number", "document_date", "validation_status"):
        if row[key] != case[key]:
            errors.append(
                f"{case['provider']}: {key}={row[key]!r} expected {case[key]!r}"
            )
    if row["position_count"] != case["position_count"]:
        errors.append(
            f"{case['provider']}: position_count={row['position_count']!r} expected {case['position_count']!r}"
        )
    if row["status"] != "processed":
        errors.append(f"{case['provider']}: status={row['status']!r} expected 'processed'")

for row in rows:
    print(
        f"[ok] {row['provider']:<12} doc={row['document_id']} "
        f"nr={row['document_number']} positions={row['position_count']} validation={row['validation_status']}"
    )

if errors:
    print("\n[error] API canary failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print(f"\n[ok] API canary passed for {len(rows)} providers")
PY
