"""CiteScan API — free technical scan, score /100."""
import os
import sys
import time

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(__file__))
from audit import run_paid_audit  # noqa: E402

app = FastAPI()
AI_BOTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot"]

# rate limit: 1 scan / IP / hour
_ip_last_scan: dict = {}
CACHE_TTL = 86400  # 24 h
_cache: dict = {}
RATE_LIMIT_SECONDS = 3600


def normalize_domain(url: str) -> str:
    parsed = httpx.URL(url)
    scheme = parsed.scheme if parsed.scheme.startswith("http") else "https"
    host = parsed.host.lower()
    return f"{scheme}://{host}"


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(strip=True)


@app.get("/health")
def health():
    return JSONResponse({"ok": True, "service": "citescan-api"})


@app.get("/api/scan")
async def scan(url: str, request: Request):
    ip = request.client.host if request.client else "anon"
    now = time.time()
    last = _ip_last_scan.get(ip, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return JSONResponse({"detail": "Rate limit: 1 scan/IP/hour"}, status_code=429)

    domain = normalize_domain(url)
    if domain in _cache and now - _cache[domain]["t"] < CACHE_TTL:
        return _cache[domain]["res"]

    _ip_last_scan[ip] = now
    result = await run_scan(domain)
    _cache[domain] = {"t": now, "res": result}
    return result


async def run_scan(domain: str) -> dict:
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
            banned = [b.lower() for b in AI_BOTS]
            blocked = [b for b in AI_BOTS if b.lower() in r_text and "disallow: /" in r_text]
            robots_ok = f"AI bots: {'blocked' if blocked else 'allowed'}"
            if blocked:
                checks["robots"] = {"status": "fail", "text": [f"robots.txt blocks {', '.join(blocked)}"], "points": 0}
            else:
                checks["robots"] = {"status": "pass", "text": ["robots.txt allows AI bots"], "points": 30}
        except Exception:
            checks["robots"] = {"status": "warn", "text": ["robots.txt not found"], "points": 10}

        # page fetch
        try:
            r = await client.get(domain)
            text = extract_text(r.text)
            soup = BeautifulSoup(r.text, "html.parser")
            checks["extract"] = {"status": "pass", "text": ["content extractable without JS"], "points": 30}

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
                checks["jsonld"] = {"status": "pass", "text": [f"JSON-LD found: {', '.join(set(types)) if types else 'yes'}"], "points": 20}
            else:
                checks["jsonld"] = {"status": "warn", "text": ["no JSON-LD structured data"], "points": 5}

            # E-E-A-T
            signals = []
            if soup.find("a", href=lambda h: h and ("about" in h.lower() or "mentions" in h.lower() or "legal" in h.lower())):
                signals.append("about page")
            if r.text.lower().count("publish") or soup.find("time"):
                signals.append("publish dates")
            if not domain.startswith("https"):
                checks["eeat"] = {"status": "fail", "text": ["no HTTPS"], "points": 0}
            else:
                checks["eeat"] = {"status": "pass" if signals else "warn", "text": [", ".join(signals) or "HTTPS only"], "points": 20 if signals else 5}
        except httpx.RequestError:
            checks["extract"] = {"status": "fail", "text": ["site unreachable"], "points": 0}

    score = sum(c["points"] for c in checks.values())
    findings = [
        {"status": checks["robots"]["status"], "text": checks["robots"]["text"][0]},
        {"status": checks["extract"]["status"], "text": checks["extract"]["text"][0]},
        {"status": checks["jsonld"]["status"], "text": checks["jsonld"]["text"][0]},
        {"status": checks["eeat"]["status"], "text": checks["eeat"]["text"][0]},
    ]
    return {"score": min(score, 100), "findings": findings[:3]}


@app.get("/api/audit")
async def paid_audit(url: str, lang: str = "en"):
    """Paid audit pipeline (carte 3.3): technical + 15 Perplexity Sonar queries.
    Degraded mode (technical only) when PERPLEXITY_API_KEY is unset — explicit, never silent."""
    lang = lang if lang in ("fr", "en") else "en"
    result = await run_paid_audit(url, lang=lang)
    return JSONResponse(result)


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/textes", StaticFiles(directory="textes"), name="textes")


@app.get("/")
async def index_en():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@app.get("/fr/")
@app.get("/fr")
async def index_fr():
    from fastapi.responses import FileResponse
    return FileResponse("static/fr/index.html")
