from fastapi import FastAPI

app = FastAPI(title="KI PDF Reader PoC API")


@app.get("/health")
def health():
    return {"ok": True, "service": "pdr-api"}


@app.get("/")
def root():
    return {
        "name": "KI-PDF-Reader On-Prem PoC",
        "status": "running",
        "next": [
            "Implement upload endpoint",
            "Implement extraction pipeline",
            "Implement JSON/CSV/SQL export",
        ],
    }
