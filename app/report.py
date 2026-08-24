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

PUBLIC_BASE = "https://citescan.brozapi.com"
RESCAN_DELAY_DAYS = 30


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
    # Re-scan gratuit J+30 (rapport niveau 2, t_a857e039) : un lien à token par
    # rapport payant, utilisable une seule fois, sans compte.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rescans (
            token TEXT PRIMARY KEY,
            parent_token TEXT NOT NULL,
            domain TEXT NOT NULL,
            lang TEXT NOT NULL,
            created_at TEXT NOT NULL,
            eligible_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            used_at TEXT,
            result_token TEXT,
            old_score INTEGER,
            new_score INTEGER
        )
    """)
    conn.commit()
    conn.close()


def create_report(domain: str, lang: str, audit: dict,
                  with_rescan: bool = True) -> dict:
    """Store an audit JSON as a report. Returns {token, domain, lang, created_at,
    rescan_token}. with_rescan=False for reports produced BY a rescan (no
    infinite chain of free audits)."""
    init_db()
    lang = lang if lang in ("fr", "en") else "en"
    token = secrets.token_urlsafe(24)  # 32 chars, unguessable
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO reports (token, domain, lang, audit, created_at) VALUES (?,?,?,?,?)",
        (token, domain, lang, json.dumps(audit, ensure_ascii=False), created),
    )
    rescan_token = None
    eligible = None
    if with_rescan:
        rescan_token = secrets.token_urlsafe(24)
        eligible = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + RESCAN_DELAY_DAYS * 86400))
        old_score = ((audit.get("score") or {}).get("total"))
        conn.execute(
            "INSERT INTO rescans (token, parent_token, domain, lang, created_at,"
            " eligible_at, status, old_score) VALUES (?,?,?,?,?,?,'pending',?)",
            (rescan_token, token, domain, lang, created, eligible, old_score),
        )
    conn.commit()
    conn.close()
    return {"token": token, "domain": domain, "lang": lang, "created_at": created,
            "rescan_token": rescan_token,
            "rescan_eligible": eligible if with_rescan else None}


def get_report(token: str) -> "dict | None":
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT token, domain, lang, audit, created_at FROM reports WHERE token = ?",
        (token,),
    ).fetchone()
    rrow = conn.execute(
        "SELECT token, eligible_at, status FROM rescans WHERE parent_token = ?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    rep = {"token": row[0], "domain": row[1], "lang": row[2],
           "audit": json.loads(row[3]), "created_at": row[4]}
    if rrow:
        rep["rescan"] = {"token": rrow[0], "eligible_at": rrow[1],
                         "status": rrow[2],
                         "url": f"{PUBLIC_BASE}/rescan/{rrow[0]}"}
    return rep


# ---------------------------------------------------------------- rescan J+30

def get_rescan(token: str) -> "dict | None":
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT token, parent_token, domain, lang, created_at, eligible_at,"
        " status, used_at, result_token, old_score, new_score"
        " FROM rescans WHERE token = ?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    keys = ("token", "parent_token", "domain", "lang", "created_at",
            "eligible_at", "status", "used_at", "result_token",
            "old_score", "new_score")
    return dict(zip(keys, row))


def set_rescan_status(token: str, status: str, result_token: "str | None" = None,
                      new_score: "int | None" = None):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    used_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) \
        if status in ("running", "done") else None
    conn.execute(
        "UPDATE rescans SET status = ?,"
        " used_at = COALESCE(?, used_at),"
        " result_token = COALESCE(?, result_token),"
        " new_score = COALESCE(?, new_score)"
        " WHERE token = ?",
        (status, used_at, result_token, new_score, token),
    )
    conn.commit()
    conn.close()


_RESCAN_TXT = {
    "fr": {
        "title": "Re-scan gratuit CiteScan",
        "early": "Votre re-scan gratuit sera disponible à partir du {date}. Revenez sur cette page à cette date — aucun compte n'est nécessaire.",
        "launched": "Votre re-scan est lancé ⏳ L'audit complet prend environ 3 minutes. Cette page se rafraîchit automatiquement.",
        "running": "Votre re-scan est en cours ⏳ Cette page se rafraîchit automatiquement.",
        "done": "Votre re-scan est terminé 🎉",
        "delta": "Score précédent : {old}/100 → nouveau score : {new}/100",
        "open": "Ouvrir le nouveau rapport →",
        "error": "Une erreur est survenue pendant le re-scan. Réessayez dans quelques minutes ou répondez à l'email de livraison.",
        "used": "Ce lien de re-scan a déjà été utilisé.",
    },
    "en": {
        "title": "CiteScan free re-scan",
        "early": "Your free re-scan will be available from {date}. Come back to this page on that date — no account needed.",
        "launched": "Your re-scan has started ⏳ The full audit takes about 3 minutes. This page refreshes automatically.",
        "running": "Your re-scan is running ⏳ This page refreshes automatically.",
        "done": "Your re-scan is complete 🎉",
        "delta": "Previous score: {old}/100 → new score: {new}/100",
        "open": "Open the new report →",
        "error": "Something went wrong during the re-scan. Try again in a few minutes or reply to the delivery email.",
        "used": "This re-scan link has already been used.",
    },
}


def render_rescan_page(rescan: dict) -> str:
    """Minimal bilingual status page for the free J+30 re-scan link (no account)."""
    lang = rescan["lang"] if rescan["lang"] in _RESCAN_TXT else "en"
    T = _RESCAN_TXT[lang]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    status = rescan["status"]
    refresh = '<meta http-equiv="refresh" content="20">' if status == "running" else ""

    if status == "done" and rescan.get("result_token"):
        delta = ""
        if rescan.get("old_score") is not None and rescan.get("new_score") is not None:
            delta = f"<p>{T['delta'].format(old=rescan['old_score'], new=rescan['new_score'])}</p>"
        body = (f"<h1>{T['done']}</h1>{delta}"
                f"<p><a class='btn' href='/rapports/{rescan['result_token']}'>{T['open']}</a></p>")
    elif status == "error":
        body = f"<h1>{T['title']}</h1><p>{T['error']}</p>"
    elif status == "running":
        body = f"<h1>{T['title']}</h1><p>{T['running']}</p>"
    elif now < rescan["eligible_at"]:
        date = (rescan.get("eligible_at") or "")[:10] or f"J+{RESCAN_DELAY_DAYS}"
        body = (f"<h1>{T['title']}</h1>"
                f"<p>{T['early'].format(date=date)}</p>")
    else:
        body = f"<h1>{T['title']}</h1><p>{T['launched']}</p>"
        refresh = '<meta http-equiv="refresh" content="20">'

    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">{refresh}
<title>{T['title']}</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#fafaf9;color:#1e293b;
margin:0;line-height:1.6}}.box{{max-width:560px;margin:10vh auto;background:#fff;
border:1px solid #e2e8f0;border-radius:12px;padding:32px}}h1{{color:#6d28d9;font-size:1.4rem}}
.btn{{display:inline-block;background:#6d28d9;color:#fff;padding:10px 18px;border-radius:8px;
text-decoration:none;margin-top:8px}}</style></head>
<body><div class="box">{body}</div></body></html>"""


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

    deliv = audit.get("deliverables") or {}
    cms = audit.get("cms") or {}
    rescan = report.get("rescan") or {}

    # --- multi-moteurs (t_9864864c) -----------------------------------------
    # Sections par moteur, matrice requête×moteur, analyse des écarts. Avec un
    # seul moteur, le gabarit historique est rendu à l'identique.
    import engines as _engines_mod
    engines_map = citations.get("engines") or {}
    engine_names = citations.get("engines_run") or list(engines_map)

    def _eng_label(n: str) -> str:
        r = engines_map.get(n) or {}
        return (r.get("engine_label")
                or (_engines_mod.ENGINES.get(n) or {}).get("label") or n)

    engine_cols = [{"name": n, "label": _eng_label(n)} for n in engine_names]
    engines_data = []
    for n in engine_names:
        r = engines_map.get(n) or {}
        engines_data.append({
            "name": n, "label": _eng_label(n),
            "status": r.get("status", "failed"),
            "cited_count": r.get("cited_count") or 0,
            "total": r.get("total") or 0,
            "queries": r.get("queries") or [],
        })
    matrix = citations.get("matrix") or []
    # Moteurs demandés mais sans clé + moteurs dont TOUTES les requêtes ont
    # échoué : mention explicite « moteur X indisponible lors de l'audit ».
    missing_labels = [_eng_label(n)
                      for n in (citations.get("engines_missing") or [])]
    failed_labels = [_eng_label(n) for n in engine_names
                     if (engines_map.get(n) or {}).get("status") == "failed"]
    engines_unavailable = missing_labels + [l for l in failed_labels
                                            if l not in missing_labels]

    def _join_labels(labels: list) -> str:
        if lang == "fr":
            return " et ".join([", ".join(labels[:-1]), labels[-1]]) \
                if len(labels) > 1 else (labels[0] if labels else "")
        return " and ".join([", ".join(labels[:-1]), labels[-1]]) \
            if len(labels) > 1 else (labels[0] if labels else "")

    engines_summary = _join_labels([c["label"] for c in engine_cols])
    # Analyse des écarts (déterministe, 0 appel LLM) : requêtes où les moteurs
    # ne s'accordent pas sur la citation du site.
    gaps = []
    for row in matrix:
        vals = row.get("by_engine") or {}
        yes = [_eng_label(n) for n, v in vals.items() if v == "yes"]
        no = [_eng_label(n) for n, v in vals.items() if v == "no"]
        if yes and no:
            if lang == "fr":
                gaps.append(f"« {row['query']} » : votre site est cité par "
                            f"{_join_labels(yes)} mais pas par {_join_labels(no)}.")
            else:
                gaps.append(f"\"{row['query']}\": your site is cited by "
                            f"{_join_labels(yes)} but not by {_join_labels(no)}.")
    n_queries = max((r.get("total") or 0) for r in engines_map.values()) \
        if engines_map else (citations.get("total") or 0)

    # Date d'activation du re-scan : si la ligne DB n'a pas d'eligible_at
    # (ne doit pas arriver, mais un trou dans la phrase est inacceptable a
    # 29 EUR — recette t_72143dd9), on recalcule J+30 depuis created_at.
    rescan_date = (rescan.get("eligible_at") or "")[:10]
    if rescan.get("url") and not rescan_date:
        try:
            created = time.strptime(report["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
            rescan_date = time.strftime(
                "%Y-%m-%d",
                time.gmtime(time.mktime(created) + RESCAN_DELAY_DAYS * 86400))
        except (ValueError, OverflowError):
            rescan_date = f"J+{RESCAN_DELAY_DAYS}"

    return {
        "lang": lang,
        "domain": report["domain"],
        "created_at": report["created_at"][:10],
        "score_total": score.get("total", 0),
        "score_technical": score.get("technical", 0),
        "score_citation": score.get("citation"),
        "mode": score.get("mode", "degraded"),
        "keyword": audit.get("keyword", ""),
        "synthese": audit.get("synthese"),
        "technical_error": technical.get("error"),
        "checks": checks,
        "citations_status": citations.get("status", "unavailable"),
        "citations_reason": citations.get("reason", ""),
        "cited_count": citations.get("cited_count") or 0,
        "citations_total": citations.get("total") or 0,
        "queries": citations.get("queries") or [],
        "competitors": citations.get("competitors") or [],
        # multi-moteurs (t_9864864c)
        "engine_cols": engine_cols,
        "engines_data": engines_data,
        "engines_summary": engines_summary,
        "engines_unavailable": engines_unavailable,
        "multi_engines": len(engine_cols) > 1,
        "matrix": matrix,
        "gaps": gaps,
        "n_queries": n_queries,
        "action_plan": audit.get("action_plan") or [],
        "top_actions": (audit.get("action_plan") or [])[:3],
        # rapport niveau 2 (t_a857e039)
        "pourquoi_cites": deliv.get("pourquoi_cites") or [],
        "actions_contenu": deliv.get("actions_contenu") or [],
        "faq": deliv.get("faq") or [],
        "faq_jsonld": deliv.get("faq_jsonld") or "",
        "roadmap": deliv.get("roadmap") or {},
        "competitor_pages": deliv.get("competitor_pages") or [],
        "platforms": audit.get("platforms") or [],
        "cms_label": cms.get("label", ""),
        "cms_instruction": cms.get("instruction", ""),
        "rescan_url": rescan.get("url", ""),
        "rescan_date": rescan_date,
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
