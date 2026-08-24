#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CiteScan — poller de livraison Stripe → rapport par email.

Calqué sur /root/accessicheck-deliveries.py (même pattern : polling des sessions
Stripe payées, filtre par payment link, anti-doublon SQLite, email SMTP OVH,
log des ventes, notification Telegram 💰).

Différence avec AccessiCheck : pas de commande pré-enregistrée — le domaine à
auditer et la langue du parcours voyagent dans le client_reference_id Stripe
au format "<domaine>|<lang>" (ex. "example.com|fr"), posé par la page offre.
Pour chaque vente : lance le pipeline d'audit payant via l'API locale
(POST /api/report, token interne), puis envoie l'email avec le PDF en pièce
jointe + le lien vers la page HTML privée du rapport.

Usage:
  citescan-deliveries.py                  # traite les nouvelles ventes (cron)
  citescan-deliveries.py --dry-run        # simule, n'envoie aucun email
  citescan-deliveries.py --fake-session <id> --order-email <email> --domain <d> [--lang fr]
                                          # teste la chaîne (dev uniquement)

Config:
  /opt/data/citescan-links.json : {"links": {"<url courte Stripe>": ["audit", "Audit CiteScan 29 €"]}}
    Créé à l'activation du Payment Link (verrou Franck n°3). Tant que le fichier
    est absent/vide, toutes les sessions sont marquées "ignore" et rien n'est livré.
"""

import argparse
import base64
import json
import os
import smtplib
import ssl
import sqlite3
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone

DB = "/root/citescan-deliveries.db"
LOG = "/root/citescan-deliveries.log"
SALES_LOG = "/opt/data/citescan-sales.log"
LINKS_JSON = "/opt/data/citescan-links.json"
STRIPE_ENV = "/root/stripe.env"            # STRIPE_RESTRICTED_KEY=rk_live_...
MAIL_ENV = "/root/.hermes/badgeia-mail.env"
TELEGRAM_ENV = "/root/.hermes/.env"        # TELEGRAM_BOT_TOKEN=...
CONTAINER_ENV = "/root/.hermes/citescan.env"  # CITESCAN_INTERNAL_TOKEN=...
CHAT_ID = "7750866970"

LOCAL_API = "http://127.0.0.1:8083"
PRODUCT_KEY = "audit"
PRODUCT_TITLE = "Audit CiteScan 29 €"

SENDER_NAME = "CiteScan"
SENDER_EMAIL = "contact@brozapi.com"


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except OSError:
        pass


def read_env(path):
    vals = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip("'").strip('"')
    except FileNotFoundError:
        pass
    return vals


def load_payment_links():
    """Charge les payment links CiteScan (créés à l'activation, verrou Franck n°3).
    Retourne {url_courte: (offre, intitulé)} — vide tant que non activé."""
    try:
        data = json.load(open(LINKS_JSON))
        links = {}
        for url, val in (data.get("links") or {}).items():
            if isinstance(val, (list, tuple)) and len(val) == 2:
                links[url] = (val[0], val[1])
        return links
    except (OSError, json.JSONDecodeError):
        return {}


def stripe_get(path, key):
    req = urllib.request.Request(
        "https://api.stripe.com" + path,
        headers={"Authorization": "Basic " + base64.b64encode((key + ":").encode()).decode()},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def local_api(method, path, body=None, timeout=120, token="", raw=False):
    """Appelle l'API CiteScan en local (conteneur docker, port 8083)."""
    url = f"{LOCAL_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Internal-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = r.read()
        return payload if raw else json.loads(payload)


def parse_client_reference(ref):
    """client_reference_id = "<domaine>|<lang>" (lang optionnelle, défaut en)."""
    if not ref:
        return None, None
    parts = ref.strip().split("|")
    domain = parts[0].strip() or None
    lang = parts[1].strip().lower() if len(parts) > 1 else ""
    if lang not in ("fr", "en"):
        lang = "fr" if (domain or "").endswith(".fr") else "en"
    return domain, lang


def send_mail(env, to, subject, text_body, html_body=None, pdf=None,
              pdf_name="rapport-citescan.pdf", dry_run=False):
    """Envoie l'email de livraison via SMTP OVH (ssl0.ovh.net:587 STARTTLS).
    Le PDF du rapport est joint (pattern spec écran 3 : PDF + lien page privée)."""
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = to
    msg["Subject"] = subject
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)
    if pdf:
        part = MIMEBase("application", "pdf")
        part.set_payload(pdf)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=pdf_name)
        msg.attach(part)

    if dry_run:
        print(f"=== DRY-RUN (début du message) ===\n{msg.as_string()[:1500]}\n...[tronqué]...")
        return True

    try:
        with smtplib.SMTP("ssl0.ovh.net", 587, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(env["MAIL_USER"], env["MAIL_PASS"])
            s.send_message(msg)
        return True
    except Exception as e:
        log(f"ERREUR envoi email {to}: {e}")
        print(f"ERREUR envoi email {to}: {e}", file=sys.stderr)
        return False


def telegram(token, text):
    """Notification Telegram (résolution IP forcée, pattern BadgeIA)."""
    try:
        subprocess.run(
            [
                "curl", "-s", "--resolve", "api.telegram.org:443:149.154.166.110",
                "-d", f"chat_id={CHAT_ID}",
                "--data-urlencode", f"text={text}",
                f"https://api.telegram.org/bot{token}/sendMessage",
            ],
            capture_output=True, timeout=20,
        )
    except Exception as e:
        log(f"ERREUR telegram: {e}")


# ---------------------------------------------------------------------------
# Construction des emails (bilingue, langue du parcours)
# ---------------------------------------------------------------------------

def email_body(domain, lang, url_html, score, mode, top_actions=None,
               url_rescan=None, rescan_date=None):
    """Retourne (sujet, texte, html) pour la livraison d'un rapport CiteScan.
    Rapport niveau 2 (t_a857e039) : l'email contient le score + le top 3 des
    actions en clair + le lien de re-scan gratuit J+30, PDF en pièce jointe."""
    top_actions = [a for a in (top_actions or []) if a][:3]
    degraded_note_fr = (
        "\nNote : la détection de citations Perplexity était indisponible lors de la "
        "génération — le rapport est en mode dégradé (audit technique seul). "
        "Répondez à cet email pour une regénération complète gratuite.\n"
    )
    degraded_note_en = (
        "\nNote: Perplexity citation detection was unavailable at generation time — "
        "the report is in degraded mode (technical audit only). "
        "Reply to this email for a free full regeneration.\n"
    )
    if lang == "fr":
        subject = "Votre rapport CiteScan est prêt 🎉"
        actions_txt = ""
        if top_actions:
            actions_txt = "\nVos 3 actions prioritaires :\n" + "\n".join(
                f"{i}. {a}" for i, a in enumerate(top_actions, 1)) + "\n"
        rescan_txt = ""
        if url_rescan:
            rescan_txt = (
                f"\nMesurez vos progrès dans 30 jours — gratuitement. Votre re-scan "
                f"(sans compte) sera actif à partir du {rescan_date or 'J+30'} :\n"
                f"{url_rescan}\nIl relance un audit complet et compare votre nouveau "
                f"score à celui d'aujourd'hui.\n"
            )
        text = (
            f"Bonjour,\n\n"
            f"Votre audit CiteScan pour {domain} est terminé.\n\n"
            f"Score global de visibilité IA : {score}/100\n"
            f"{actions_txt}\n"
            f"1. Votre rapport PDF complet est en pièce jointe de cet email (FAQ prête "
            f"à publier, bloc JSON-LD à copier-coller, feuille de route 30/60/90 jours).\n"
            f"2. Version navigateur (page privée, à ne pas partager publiquement) :\n"
            f"{url_html}\n"
            f"{rescan_txt}"
            f"{degraded_note_fr if mode == 'degraded' else ''}\n"
            f"Garantie satisfait ou remboursé 7 jours : répondez simplement à cet email.\n\n"
            f"Des questions ? Répondez directement à cet email.\n\n"
            f"—\nCiteScan par Brozapi\ncontact@brozapi.com\nhttps://citescan.brozapi.com\n"
        )
        actions_html = ""
        if top_actions:
            lis = "".join(f"<li style='margin:6px 0;'>{a}</li>" for a in top_actions)
            actions_html = (f"<p style='margin-bottom:4px;'><strong>Vos 3 actions prioritaires :</strong></p>"
                            f"<ol style='margin-top:4px;'>{lis}</ol>")
        rescan_html = ""
        if url_rescan:
            rescan_html = (
                f"<p style='background:#f5f3ff;border:1px solid #ddd6fe;border-radius:8px;"
                f"padding:12px 16px;'>📅 <strong>Mesurez vos progrès dans 30 jours — gratuit.</strong><br>"
                f"Votre re-scan (sans compte) sera actif à partir du {rescan_date or 'J+30'} :<br>"
                f"<a href='{url_rescan}'>{url_rescan}</a><br>"
                f"<span style='font-size:0.85rem;color:#6b7280;'>Il relance un audit complet et "
                f"compare votre nouveau score à celui d'aujourd'hui.</span></p>"
            )
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Votre rapport CiteScan</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;line-height:1.6;color:#1a1a1a;max-width:600px;margin:0 auto;padding:24px;">
  <p style="margin-top:0;">Bonjour,</p>
  <p><strong>Votre audit CiteScan pour {domain} est terminé.</strong></p>
  <table style="border-collapse:collapse;margin:1rem 0;">
    <tr><td style="padding:6px 12px;border:1px solid #e5e7eb;">Score global de visibilité IA</td>
        <td style="padding:6px 12px;border:1px solid #e5e7eb;"><strong>{score}/100</strong></td></tr>
  </table>
  {actions_html}
  <p>📎 Le <strong>rapport PDF complet</strong> est en pièce jointe de cet email : FAQ prête à publier,
  bloc JSON-LD à copier-coller et feuille de route 30/60/90 jours inclus.</p>
  <p><a href="{url_html}" style="background:#6d28d9;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none;">Ouvrir la page privée du rapport →</a></p>
  <p style="font-size:0.85rem;color:#6b7280;">Cette page est privée (lien à token) — ne la partagez pas publiquement.</p>
  {rescan_html}
  {"<p style='background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:10px 14px;font-size:0.9rem;'>⚠ Rapport en mode dégradé (audit technique seul) — répondez à cet email pour une regénération complète gratuite.</p>" if mode == "degraded" else ""}
  <hr style="border:0;border-top:1px solid #e5e7eb;margin:1.5rem 0;">
  <p style="font-size:0.875rem;color:#6b7280;">
    Garantie satisfait ou remboursé 7 jours : répondez simplement à cet email.<br><br>
    — CiteScan par Brozapi · <a href="mailto:contact@brozapi.com">contact@brozapi.com</a> · <a href="https://citescan.brozapi.com">citescan.brozapi.com</a>
  </p>
</body>
</html>"""
    else:
        subject = "Your CiteScan report is ready 🎉"
        actions_txt = ""
        if top_actions:
            actions_txt = "\nYour top 3 priority actions:\n" + "\n".join(
                f"{i}. {a}" for i, a in enumerate(top_actions, 1)) + "\n"
        rescan_txt = ""
        if url_rescan:
            rescan_txt = (
                f"\nMeasure your progress in 30 days — free. Your re-scan (no account) "
                f"becomes active on {rescan_date or 'day 30'}:\n"
                f"{url_rescan}\nIt re-runs a full audit and compares your new score "
                f"with today's.\n"
            )
        text = (
            f"Hello,\n\n"
            f"Your CiteScan audit for {domain} is complete.\n\n"
            f"Overall AI visibility score: {score}/100\n"
            f"{actions_txt}\n"
            f"1. Your full PDF report is attached to this email (ready-to-publish FAQ, "
            f"copy-paste JSON-LD block, 30/60/90-day roadmap).\n"
            f"2. Browser version (private page, please do not share publicly):\n"
            f"{url_html}\n"
            f"{rescan_txt}"
            f"{degraded_note_en if mode == 'degraded' else ''}\n"
            f"7-day money-back guarantee: simply reply to this email.\n\n"
            f"Questions? Just reply to this email.\n\n"
            f"—\nCiteScan by Brozapi\ncontact@brozapi.com\nhttps://citescan.brozapi.com\n"
        )
        actions_html = ""
        if top_actions:
            lis = "".join(f"<li style='margin:6px 0;'>{a}</li>" for a in top_actions)
            actions_html = (f"<p style='margin-bottom:4px;'><strong>Your top 3 priority actions:</strong></p>"
                            f"<ol style='margin-top:4px;'>{lis}</ol>")
        rescan_html = ""
        if url_rescan:
            rescan_html = (
                f"<p style='background:#f5f3ff;border:1px solid #ddd6fe;border-radius:8px;"
                f"padding:12px 16px;'>📅 <strong>Measure your progress in 30 days — free.</strong><br>"
                f"Your re-scan (no account) becomes active on {rescan_date or 'day 30'}:<br>"
                f"<a href='{url_rescan}'>{url_rescan}</a><br>"
                f"<span style='font-size:0.85rem;color:#6b7280;'>It re-runs a full audit and "
                f"compares your new score with today's.</span></p>"
            )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Your CiteScan report</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;line-height:1.6;color:#1a1a1a;max-width:600px;margin:0 auto;padding:24px;">
  <p style="margin-top:0;">Hello,</p>
  <p><strong>Your CiteScan audit for {domain} is complete.</strong></p>
  <table style="border-collapse:collapse;margin:1rem 0;">
    <tr><td style="padding:6px 12px;border:1px solid #e5e7eb;">Overall AI visibility score</td>
        <td style="padding:6px 12px;border:1px solid #e5e7eb;"><strong>{score}/100</strong></td></tr>
  </table>
  {actions_html}
  <p>📎 The <strong>full PDF report</strong> is attached to this email: ready-to-publish FAQ,
  copy-paste JSON-LD block and 30/60/90-day roadmap included.</p>
  <p><a href="{url_html}" style="background:#6d28d9;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none;">Open the private report page →</a></p>
  <p style="font-size:0.85rem;color:#6b7280;">This page is private (token link) — please do not share it publicly.</p>
  {rescan_html}
  {"<p style='background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:10px 14px;font-size:0.9rem;'>⚠ Degraded-mode report (technical audit only) — reply to this email for a free full regeneration.</p>" if mode == "degraded" else ""}
  <hr style="border:0;border-top:1px solid #e5e7eb;margin:1.5rem 0;">
  <p style="font-size:0.875rem;color:#6b7280;">
    7-day money-back guarantee: simply reply to this email.<br><br>
    — CiteScan by Brozapi · <a href="mailto:contact@brozapi.com">contact@brozapi.com</a> · <a href="https://citescan.brozapi.com">citescan.brozapi.com</a>
  </p>
</body>
</html>"""
    return subject, text, html


# ---------------------------------------------------------------------------
# Base SQLite (anti-doublon)
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            session_id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            offer TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            domain TEXT,
            lang TEXT,
            token TEXT,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()


def already_processed(session_id):
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT 1 FROM deliveries WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row is not None


def record_delivery(session_id, email, offer, status, domain=None, lang=None, token=None, error=None):
    """Insère ou met à jour la ligne de livraison (upsert par session_id)."""
    conn = sqlite3.connect(DB)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO deliveries (session_id, email, offer, status, created_at, domain, lang, token, error) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, email, offer, status, now, domain, lang, token, error),
    )
    conn.execute(
        "UPDATE deliveries SET email=?, offer=?, status=?, domain=?, lang=?, token=?, error=? WHERE session_id=?",
        (email, offer, status, domain, lang, token, error, session_id),
    )
    conn.commit()
    conn.close()


def log_sale(offer, email, extra=""):
    try:
        with open(SALES_LOG, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {offer} {email} {extra}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Traitement des ventes
# ---------------------------------------------------------------------------

def process_session(session, plink_map, payment_links, mail, tg, internal_token, dry_run):
    sid = session["id"]
    email = (session.get("customer_details") or {}).get("email")
    plink_id = session.get("payment_link") or ""
    url_short = plink_map.get(plink_id, "")
    if url_short not in payment_links:
        record_delivery(sid, email or "-", "ignore", "ignore")
        log(f"IGNORE {sid}: pas un lien CiteScan (compte Stripe partagé)")
        return
    offer, intitule = payment_links[url_short]
    if not email:
        log(f"WARN: session {sid} payée sans email")
        return

    # 1. Domaine + langue du parcours via client_reference_id ("<domaine>|<lang>").
    domain, lang = parse_client_reference(session.get("client_reference_id"))
    if not domain:
        record_delivery(sid, email, offer, "no-ref")
        log(f"NO-REF {sid} {offer} {email}")
        if tg and not dry_run:
            telegram(tg, f"⚠️ CiteScan : paiement {intitule} ({email}) SANS client_reference_id — domaine manquant.")
        return

    # 2. Lancer le pipeline d'audit payant + créer le rapport (page token + PDF).
    try:
        rep = local_api("POST", "/api/report",
                        {"url": domain, "lang": lang},
                        timeout=600, token=internal_token)
    except Exception as e:
        log(f"ERROR audit/report {sid} {domain}: {e}")
        record_delivery(sid, email, offer, "failed", domain, lang, error=str(e)[:300])
        if tg and not dry_run:
            telegram(tg, f"⚠️ CiteScan : échec génération rapport pour {domain} ({email}) — {e}")
        return

    token = rep["token"]
    url_html = rep["url_html"]
    mode = rep.get("mode", "degraded")

    # 3. Récupérer le PDF pour la pièce jointe.
    try:
        pdf = local_api("GET", f"/rapports/{token}/pdf", timeout=180, raw=True)
        if not pdf.startswith(b"%PDF"):
            raise ValueError("réponse PDF invalide")
    except Exception as e:
        log(f"ERROR fetch pdf {token}: {e}")
        record_delivery(sid, email, offer, "pdf-failed", domain, lang, token, error=str(e)[:300])
        return

    # 4. Envoyer l'email de livraison (PDF joint + lien page privée + top 3
    # actions + lien de re-scan gratuit J+30 — rapport niveau 2, t_a857e039).
    # Le score exact est relu depuis l'audit stocké : on le récupère via la page
    # (le score est dans l'email informatif, pas contractuel).
    score = rep.get("score") or "—"
    subject, text, html = email_body(
        domain, lang, url_html, score, mode,
        top_actions=rep.get("top_actions"),
        url_rescan=rep.get("url_rescan"),
        rescan_date=rep.get("rescan_date"))
    slug = domain.replace("https://", "").replace("http://", "").replace("/", "_")
    ok = send_mail(mail, email, subject, text, html, pdf=pdf,
                   pdf_name=f"citescan-rapport-{slug}.pdf", dry_run=dry_run)

    status = "sent" if ok else "failed"
    record_delivery(sid, email, offer, status, domain, lang, token, None if ok else "mail")
    log(f"LIVRE {sid} {offer} -> {email} domaine={domain} lang={lang} token={token[:8]}… "
        f"(mail={'dry' if dry_run else ('ok' if ok else 'ko')})")

    if ok and not dry_run:
        log_sale(offer, email, f"domaine={domain} session={sid} token={token}")
        if tg:
            telegram(tg, f"💰 VENTE CiteScan !\n{intitule}\nClient : {email}\nDomaine : {domain} ({lang})\nRapport livré par email ✓")


def main():
    ap = argparse.ArgumentParser(description="Livraison CiteScan (Stripe → email)")
    ap.add_argument("--dry-run", action="store_true", help="Simuler sans envoyer")
    ap.add_argument("--fake-session", default=None, help="ID de session à traiter manuellement (dev)")
    ap.add_argument("--order-email", default=None, help="Email pour --fake-session")
    ap.add_argument("--domain", default=None, help="Domaine à auditer pour --fake-session")
    ap.add_argument("--lang", default="fr", choices=["fr", "en"], help="Langue pour --fake-session")
    args = ap.parse_args()

    init_db()
    stripe = (read_env(STRIPE_ENV) or {}).get("STRIPE_RESTRICTED_KEY", "")
    mail = read_env(MAIL_ENV)
    tg = (read_env(TELEGRAM_ENV) or {}).get("TELEGRAM_BOT_TOKEN", "")
    internal_token = (read_env(CONTAINER_ENV) or {}).get("CITESCAN_INTERNAL_TOKEN", "")
    payment_links = load_payment_links()

    if not stripe:
        log("ERREUR: pas de STRIPE_RESTRICTED_KEY dans " + STRIPE_ENV)
        print("ERREUR: pas de STRIPE_RESTRICTED_KEY", file=sys.stderr)
        sys.exit(1)

    # Mapping payment_link id → url courte.
    try:
        links = stripe_get("/v1/payment_links?limit=100&active=true", stripe)
        plink_map = {l["id"]: l["url"] for l in links.get("data", [])}
    except Exception as e:
        log(f"ERREUR list payment_links: {e}")
        print(f"ERREUR Stripe payment_links: {e}", file=sys.stderr)
        sys.exit(1)

    dry_run = args.dry_run

    if not payment_links and not args.fake_session:
        log("INFO: aucun payment link CiteScan configuré "
            f"({LINKS_JSON} absent/vide) — verrou Franck n°3 actif, rien à livrer.")

    if args.fake_session and args.order_email and args.domain:
        # Mode dev : simule une session payée pour tester la chaîne.
        sid = args.fake_session
        if already_processed(sid):
            print("Session déjà traitée, suppression pour retest...")
            conn = sqlite3.connect(DB)
            conn.execute("DELETE FROM deliveries WHERE session_id = ?", (sid,))
            conn.commit()
            conn.close()
        fake = {
            "id": sid,
            "payment_status": "paid",
            "payment_link": None,
            "client_reference_id": f"{args.domain}|{args.lang}",
            "customer_details": {"email": args.order_email},
        }
        # Forcer le mapping : utiliser le 1er lien configuré, ou un lien fictif.
        if payment_links:
            plink_map[""] = next(iter(payment_links))
        else:
            payment_links["fake://citescan-audit"] = (PRODUCT_KEY, PRODUCT_TITLE)
            plink_map[""] = "fake://citescan-audit"
        process_session(fake, plink_map, payment_links, mail, tg, internal_token, dry_run)
        return

    # Mode normal : lister les sessions récentes payées.
    try:
        sessions = stripe_get("/v1/checkout/sessions?limit=50", stripe)
    except Exception as e:
        log(f"ERREUR list sessions: {e}")
        print(f"ERREUR Stripe sessions: {e}", file=sys.stderr)
        sys.exit(1)

    for s in sessions.get("data", []):
        if s.get("payment_status") != "paid":
            continue
        if already_processed(s["id"]):
            continue
        try:
            process_session(s, plink_map, payment_links, mail, tg, internal_token, dry_run)
        except Exception as e:
            log(f"ERREUR session {s['id']}: {e}")
            record_delivery(s["id"], "-", "-", "error", error=str(e)[:300])

    print("done")


if __name__ == "__main__":
    main()
