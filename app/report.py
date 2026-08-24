"""CiteScan — paid report storage + rendering (carte 3.4).

A paid audit (app/audit.py JSON) is rendered into:
  - a private HTML page served at /rapports/<token> (unguessable token, noindex)
  - a PDF served at /rapports/<token>/pdf (WeasyPrint, CiteScan branding)
both in the journey language (fr or en).

Storage: SQLite (/data/citescan.db in the container, ./citescan.db in dev).
The buyer email is never stored in the report nor rendered (token page privacy).
"""
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = "/data/citescan.db" if os.path.isdir("/data") else str(_HERE.parent / "citescan.db")
DB_PATH = os.environ.get("CITESCAN_DB", _DEFAULT_DB)
TEMPLATE_DIR = _HERE / "templates"

_jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

CHECK_META = {
    "robots": {"max": 30, "fr": "Bots IA dans robots.txt", "en": "AI bots in robots.txt"},
    "extract": {"max": 30, "fr": "Extractabilité du contenu", "en": "Content extractability"},
    "jsonld": {"max": 20, "fr": "Données structurées (JSON-LD)", "en": "Structured data (JSON-LD)"},
    "eeat": {"max": 20, "fr": "Signaux de confiance (E-E-A-T)", "en": "Trust signals (E-E-A-T)"},
}

# ---------------------------------------------------------------- storage

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            token TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            lang TEXT NOT NULL,
            audit TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_report(domain: str, lang: str, audit: dict) -> dict:
    """Store an audit JSON as a report. Returns {token, domain, lang, created_at}."""
    init_db()
    lang = lang if lang in ("fr", "en") else "en"
    token = secrets.token_urlsafe(24)  # 32 chars, unguessable
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO reports (token, domain, lang, audit, created_at) VALUES (?,?,?,?,?)",
        (token, domain, lang, json.dumps(audit, ensure_ascii=False), created),
    )
    conn.commit()
    conn.close()
    return {"token": token, "domain": domain, "lang": lang, "created_at": created}


def get_report(token: str) -> "dict | None":
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT token, domain, lang, audit, created_at FROM reports WHERE token = ?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"token": row[0], "domain": row[1], "lang": row[2],
            "audit": json.loads(row[3]), "created_at": row[4]}

# ---------------------------------------------------------------- rendering

def _build_context(report: dict) -> dict:
    """Flatten the audit JSON into a template-ready context (bilingual labels)."""
    audit = report["audit"]
    lang = report["lang"]
    technical = audit.get("technical") or {}
    citations = audit.get("citations") or {}
    score = audit.get("score") or {}

    checks = []
    for key, meta in CHECK_META.items():
        c = (technical.get("checks") or {}).get(key)
        if not c:
            continue
        checks.append({
            "key": key,
            "label": meta[lang],
            "status": c.get("status", "warn"),
            "points": c.get("points", 0),
            "max": meta["max"],
            "detail": c.get("detail", ""),
            "bots": c.get("bots") or {},
            "types": c.get("types") or [],
            "signals": c.get("signals") or [],
            "missing": c.get("missing") or [],
        })

    return {
        "lang": lang,
        "domain": report["domain"],
        "created_at": report["created_at"][:10],
        "score_total": score.get("total", 0),
        "score_technical": score.get("technical", 0),
        "score_citation": score.get("citation"),
        "mode": score.get("mode", "degraded"),
        "keyword": audit.get("keyword", ""),
        "word_count": technical.get("word_count", 0),
        "technical_error": technical.get("error"),
        "checks": checks,
        "citations_status": citations.get("status", "unavailable"),
        "citations_reason": citations.get("reason", ""),
        "cited_count": citations.get("cited_count", 0),
        "citations_total": citations.get("total", 0),
        "queries": citations.get("queries") or [],
        "competitors": citations.get("competitors") or [],
        "action_plan": audit.get("action_plan") or [],
        "year": time.strftime("%Y"),
    }


def render_html(report: dict) -> str:
    """Render the private HTML report in the report language."""
    template = _jinja.get_template(f"report_{report['lang']}.html")
    return template.render(**_build_context(report))


def render_pdf(report: dict) -> bytes:
    """Render the PDF version (WeasyPrint). Raises RuntimeError if unavailable."""
    try:
        from weasyprint import HTML
    except Exception as e:  # ImportError or missing system libs (pango)
        raise RuntimeError(f"WeasyPrint unavailable: {e}") from e
    html = render_html(report)
    return HTML(string=html).write_pdf()
