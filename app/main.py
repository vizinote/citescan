"""CiteScan API — free technical scan, score /100."""
import asyncio
import os
import re
import sys
import time
import traceback

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(__file__))
from audit import run_paid_audit  # noqa: E402
import report as reports  # noqa: E402

app = FastAPI()
AI_BOTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot"]

# rate limit: 1 scan / IP / hour
_ip_last_scan: dict = {}
CACHE_TTL = 86400  # 24 h
_cache: dict = {}
RATE_LIMIT_SECONDS = 3600

INTERNAL_TOKEN = os.environ.get("CITESCAN_INTERNAL_TOKEN", "").strip()

# Free-scan finding texts, localized (journey language via ?lang=fr|en).
SCAN_TEXTS = {
    "fr": {
        "robots_pass": "robots.txt autorise les bots IA",
        "robots_fail": "robots.txt bloque : {bots}",
        "robots_warn": "robots.txt introuvable",
        "extract_pass": "contenu extractible sans JavaScript",
        "extract_fail": "site inaccessible",
        "jsonld_pass": "JSON-LD détecté : {types}",
        "jsonld_warn": "aucune donnée structurée JSON-LD",
        "eeat_about": "page à propos",
        "eeat_dates": "dates de publication",
        "eeat_https_only": "HTTPS uniquement",
        "eeat_no_https": "pas de HTTPS",
        "no_detail": "aucun détail",
        "invalid_url": "URL invalide",
        "unreachable": "site temporairement inaccessible",
    },
    "en": {
        "robots_pass": "robots.txt allows AI bots",
        "robots_fail": "robots.txt blocks: {bots}",
        "robots_warn": "robots.txt not found",
        "extract_pass": "content extractable without JS",
        "extract_fail": "site unreachable",
        "jsonld_pass": "JSON-LD found: {types}",
        "jsonld_warn": "no JSON-LD structured data",
        "eeat_about": "about page",
        "eeat_dates": "publish dates",
        "eeat_https_only": "HTTPS only",
        "eeat_no_https": "no HTTPS",
        "no_detail": "no detail",
        "invalid_url": "invalid URL",
        "unreachable": "site temporarily unreachable",
    },
}


def normalize_domain(url: str) -> str:
    """Normalize user input to https://<host>. Accepts bare domains.
    Raises ValueError on anything unusable — the endpoint turns it into a 400,
    never a 500."""
    url = (url or "").strip()
    if not url or len(url) > 300:
        raise ValueError("empty or too long")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    try:
        parsed = httpx.URL(url)
    except Exception as e:
        raise ValueError(f"unparseable: {e}") from e
    host = (parsed.host or "").lower()
    if not host or "." not in host or any(c in host for c in " /?#@"):
        raise ValueError("invalid host")
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    return f"{scheme}://{host}"


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(strip=True)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Franck must never see a bare 'Internal Server Error'."""
    traceback.print_exc()
    return JSONResponse({"detail": "temporary server error"}, status_code=502)


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return JSONResponse({"ok": True, "service": "citescan-api"})


@app.get("/api/scan")
async def scan(url: str, request: Request, lang: str = "en"):
    lang = lang if lang in SCAN_TEXTS else "en"
    T = SCAN_TEXTS[lang]

    try:
        domain = normalize_domain(url)
    except ValueError:
        return JSONResponse({"detail": T["invalid_url"]}, status_code=400)

    # Internal token (poller, test script) bypasses the public rate limit.
    internal = bool(INTERNAL_TOKEN) and \
        request.headers.get("X-Internal-Token", "") == INTERNAL_TOKEN
    ip = request.client.host if request.client else "anon"
    now = time.time()
    if not internal:
        last = _ip_last_scan.get(ip, 0)
        if now - last < RATE_LIMIT_SECONDS:
            return JSONResponse({"detail": "Rate limit: 1 scan/IP/hour"}, status_code=429)

    if domain in _cache and now - _cache[domain]["t"] < CACHE_TTL:
        res = _cache[domain]["res"]
        if res.get("lang") == lang:
            return res

    if not internal:
        _ip_last_scan[ip] = now
    try:
        result = await run_scan(domain, T)
    except Exception:
        traceback.print_exc()
        return JSONResponse({"detail": T["unreachable"]}, status_code=502)
    result["lang"] = lang
    _cache[domain] = {"t": now, "res": result}
    return result


async def run_scan(domain: str, T: dict) -> dict:
    checks = {
        "robots": {"status": "fail", "text": [], "points": 0},
        "extract": {"status": "fail", "text": [], "points": 0},
        "jsonld": {"status": "warn", "text": [], "points": 0},
        "eeat": {"status": "warn", "text": [], "points": 0},
    }
    score = 0
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        # robots.txt
        try:
            r = await client.get(f"{domain}/robots.txt")
            r_text = r.text.lower()
            blocked = [b for b in AI_BOTS if b.lower() in r_text and "disallow: /" in r_text]
            if blocked:
                checks["robots"] = {"status": "fail",
                                    "text": [T["robots_fail"].format(bots=", ".join(blocked))],
                                    "points": 0}
            else:
                checks["robots"] = {"status": "pass", "text": [T["robots_pass"]], "points": 30}
        except Exception:
            checks["robots"] = {"status": "warn", "text": [T["robots_warn"]], "points": 10}

        # page fetch
        try:
            r = await client.get(domain)
            soup = BeautifulSoup(r.text, "html.parser")
            checks["extract"] = {"status": "pass", "text": [T["extract_pass"]], "points": 30}

            # JSON-LD
            if soup.find("script", type="application/ld+json"):
                types = []
                for s in soup.find_all("script", type="application/ld+json"):
                    t = s.string or ""
                    if "@type" in t:
                        # crude extraction
                        for frag in t.split("@type")[1].split(",")[0].split():
                            frag = frag.strip('"{}:.,')
                            if frag:
                                types.append(frag)
                checks["jsonld"] = {"status": "pass",
                                    "text": [T["jsonld_pass"].format(
                                        types=", ".join(sorted(set(types))) if types else "yes")],
                                    "points": 20}
            else:
                checks["jsonld"] = {"status": "warn", "text": [T["jsonld_warn"]], "points": 5}

            # E-E-A-T
            signals = []
            if soup.find("a", href=lambda h: h and ("about" in h.lower() or "mentions" in h.lower() or "legal" in h.lower())):
                signals.append(T["eeat_about"])
            if r.text.lower().count("publish") or soup.find("time"):
                signals.append(T["eeat_dates"])
            if not domain.startswith("https"):
                checks["eeat"] = {"status": "fail", "text": [T["eeat_no_https"]], "points": 0}
            else:
                checks["eeat"] = {"status": "pass" if signals else "warn",
                                  "text": [", ".join(signals) or T["eeat_https_only"]],
                                  "points": 20 if signals else 5}
        except httpx.RequestError:
            checks["extract"] = {"status": "fail", "text": [T["extract_fail"]], "points": 0}

    score = sum(c["points"] for c in checks.values())
    # Never index an empty text list — fall back to an explicit placeholder.
    def _first(key: str) -> str:
        return checks[key]["text"][0] if checks[key]["text"] else T["no_detail"]

    findings = [
        {"status": checks["robots"]["status"], "text": _first("robots")},
        {"status": checks["extract"]["status"], "text": _first("extract")},
        {"status": checks["jsonld"]["status"], "text": _first("jsonld")},
        {"status": checks["eeat"]["status"], "text": _first("eeat")},
    ]
    return {"score": min(score, 100), "findings": findings[:3]}


@app.get("/api/audit")
async def paid_audit(url: str, lang: str = "en", engines: str = ""):
    """Paid audit pipeline (carte 3.3 + multi-moteurs t_9864864c): technical +
    15 requêtes buyer-intent par moteur. engines = CSV optionnel
    (ex. "perplexity,gemini,chatgpt") ; défaut = tous les moteurs dont la clé
    est présente. Mode dégradé explicite si aucun moteur disponible."""
    lang = lang if lang in ("fr", "en") else "en"
    engines_sel = [e.strip() for e in engines.split(",") if e.strip()] or None
    result = await run_paid_audit(url, lang=lang, engines_sel=engines_sel)
    return JSONResponse(result)


# ---------------------------------------------------------------- paid reports (carte 3.4)

PUBLIC_BASE = "https://citescan.brozapi.com"


def _check_internal(request: Request):
    """POST /api/report runs the paid pipeline (~$0.15/audit): internal token required."""
    if not INTERNAL_TOKEN:
        return JSONResponse({"detail": "report creation disabled (no internal token)"},
                            status_code=503)
    if request.headers.get("X-Internal-Token", "") != INTERNAL_TOKEN:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    return None


@app.post("/api/report")
async def create_report(request: Request):
    """Create a private report (HTML token page + PDF) from a paid audit.

    Body: {"url": "...", "lang": "fr|en"} — or pass a precomputed "audit" dict.
    Called by the delivery poller on localhost; protected by X-Internal-Token.
    """
    denied = _check_internal(request)
    if denied:
        return denied
    body = await request.json()
    lang = body.get("lang") if body.get("lang") in ("fr", "en") else "en"
    audit = body.get("audit")
    url = body.get("url", "")
    engines_sel = body.get("engines")
    if not isinstance(engines_sel, list) or not engines_sel:
        engines_sel = None
    if not audit:
        if not url:
            return JSONResponse({"detail": "url or audit required"}, status_code=400)
        audit = await run_paid_audit(url, lang=lang, engines_sel=engines_sel)
    domain = audit.get("domain") or url
    rep = reports.create_report(domain, lang, audit)
    token = rep["token"]
    rescan_url = (f"{PUBLIC_BASE}/rescan/{rep['rescan_token']}"
                  if rep.get("rescan_token") else None)
    return JSONResponse({
        "token": token,
        "domain": domain,
        "lang": lang,
        "mode": (audit.get("score") or {}).get("mode", "degraded"),
        "score": (audit.get("score") or {}).get("total"),
        "top_actions": [a.get("action", "")
                        for a in (audit.get("action_plan") or [])[:3]],
        "cost_usd": (audit.get("cost_usd") or {}).get("total"),
        "url_html": f"{PUBLIC_BASE}/rapports/{token}",
        "url_pdf": f"{PUBLIC_BASE}/rapports/{token}/pdf",
        "url_rescan": rescan_url,
        "rescan_date": (rep.get("rescan_eligible") or "")[:10] or None,
    })


@app.get("/rapports/{token}", response_class=HTMLResponse)
def report_html(token: str):
    rep = reports.get_report(token)
    if not rep:
        return HTMLResponse("Rapport introuvable / Report not found.", status_code=404)
    return HTMLResponse(
        reports.render_html(rep),
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@app.get("/rapports/{token}/pdf")
def report_pdf(token: str):
    rep = reports.get_report(token)
    if not rep:
        return JSONResponse({"detail": "not found"}, status_code=404)
    try:
        pdf = reports.render_pdf(rep)
    except RuntimeError as e:
        return JSONResponse({"detail": str(e)}, status_code=503)
    slug = rep["domain"].replace("https://", "").replace("http://", "").replace("/", "_")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="citescan-rapport-{slug}.pdf"',
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


# ---------------------------------------------------------------- free re-scan J+30 (rapport niveau 2)

async def _run_rescan(token: str):
    """Background task: full fresh audit for a re-scan link, then a new report
    (with_rescan=False — one free re-scan per paid report, no infinite chain)."""
    rescan = reports.get_rescan(token)
    if not rescan:
        return
    try:
        # Re-scan J+30 : mêmes moteurs que l'audit initial (t_9864864c) —
        # relus depuis le rapport parent ; défaut = moteurs disponibles.
        engines_sel = None
        parent = reports.get_report(rescan["parent_token"])
        if parent:
            engines_sel = (parent["audit"].get("engines") or None)
        audit = await run_paid_audit(rescan["domain"], lang=rescan["lang"],
                                     engines_sel=engines_sel)
        rep = reports.create_report(rescan["domain"], rescan["lang"], audit,
                                    with_rescan=False)
        new_score = (audit.get("score") or {}).get("total")
        reports.set_rescan_status(token, "done", rep["token"], new_score)
    except Exception:
        traceback.print_exc()
        reports.set_rescan_status(token, "error")


@app.get("/rescan/{token}", response_class=HTMLResponse)
async def rescan_page(token: str):
    """Free J+30 re-scan link (no account): shows availability, launches the
    audit in the background when eligible, auto-refreshes until done."""
    rescan = reports.get_rescan(token)
    if not rescan:
        return HTMLResponse("Lien introuvable / Link not found.", status_code=404)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if rescan["status"] == "pending" and now >= rescan["eligible_at"]:
        reports.set_rescan_status(token, "running")
        rescan["status"] = "running"
        asyncio.create_task(_run_rescan(token))
    elif rescan["status"] == "running":
        # Crash/restart recovery: a 'running' state older than 15 min is
        # considered dead — allow one relaunch instead of being stuck forever.
        used_at = rescan.get("used_at") or ""
        if used_at and (time.time() - time.mktime(
                time.strptime(used_at, "%Y-%m-%dT%H:%M:%SZ"))) > 900:
            reports.set_rescan_status(token, "running")  # refresh used_at
            asyncio.create_task(_run_rescan(token))
    return HTMLResponse(
        reports.render_rescan_page(rescan),
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/textes", StaticFiles(directory="textes"), name="textes")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# Pages d'offre / légales (racine du repo). Le CTA de commande reste verrouillé
# côté HTML tant que les Payment Links ne sont pas activés (verrou Franck n°3).
_STATIC_PAGES = {
    "/offre.html": "offre.html",
    "/merci.html": "merci.html",
    "/cgv.html": "cgv.html",
    "/mentions-legales.html": "mentions-legales.html",
    "/en/offer.html": "en/offer.html",
    "/en/thanks.html": "en/thanks.html",
    "/en/cgv.html": "en/cgv.html",
    "/en/legal.html": "en/legal.html",
}

for _route, _file in _STATIC_PAGES.items():
    async def _serve(_f=_file):
        from fastapi.responses import FileResponse
        return FileResponse(_f)
    app.api_route(_route, methods=["GET", "HEAD"])(_serve)


@app.api_route("/", methods=["GET", "HEAD"])
async def index_en():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@app.api_route("/fr/", methods=["GET", "HEAD"])
@app.api_route("/fr", methods=["GET", "HEAD"])
async def index_fr():
    from fastapi.responses import FileResponse
    return FileResponse("static/fr/index.html")


# ---------------------------------------------------------------- SEO (carte 3.5)

# Cle IndexNow partagee avec les autres domaines brozapi (cf. /root/indexnow_ping.py).
INDEXNOW_KEY = "a9e8fc609645365e02a9b0e2703de984"

# Pages publiques indexables (les rapports /rapports/<token> sont noindex,
# /merci et l'offre restent hors sitemap tant que le paiement n'est pas actif).
SITEMAP_URLS = [
    ("https://citescan.brozapi.com/", "1.0"),
    ("https://citescan.brozapi.com/fr/", "0.9"),
]


@app.get("/sitemap.xml")
def sitemap():
    from fastapi.responses import Response
    urls = "".join(
        f"  <url><loc>{loc}</loc><changefreq>weekly</changefreq>"
        f"<priority>{prio}</priority></url>\n"
        for loc, prio in SITEMAP_URLS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt")
def robots():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /rapports/\n"
        "Disallow: /rescan/\n"
        "\n"
        "Sitemap: https://citescan.brozapi.com/sitemap.xml\n"
    )


@app.get(f"/{INDEXNOW_KEY}.txt")
def indexnow_key():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(INDEXNOW_KEY)
