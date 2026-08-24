#!/usr/bin/env python3
"""
CiteScan — Création des 3 Stripe Payment Links multi-moteurs (29/39/49 €).

⚠ VERROU FRANCK (n°3) — deux phases distinctes :

  1. CRÉATION (ce script, mode `create`) : autorisée par le GO pricing de Franck
     (2026-08-24, t_9864864c). Les liens sont créés **INACTIFS** (active=false) :
     aucun encaissement possible, page Stripe "lien désactivé" pour tout visiteur.
     → statut "pending_activation" dans /opt/data/citescan-links.json.

  2. ACTIVATION (mode `activate`) : VERROU MANUEL. Ne s'exécute qu'après saisie
     interactive de la phrase exacte 'OUI-FRANCK-A-VALIDE'. Bascule les 3 liens
     en active=true → encaissement réel possible à partir de cet instant.

Grille validée par Franck (2026-08-24, t_9864864c) :
  - 29 € : Perplexity + Gemini
  - 39 € : 29 € + ChatGPT OU Claude au choix (choix côté client)
  - 49 € : les 4 IA (« audit complet »)
Re-scan J+30 gratuit conservé sur tous les paliers (mêmes moteurs).

Prérequis :
  - Clé Stripe LIVE dans /root/stripe.env (host-only, jamais dans le repo)
    → FRANCK : créer une clé restreinte (rk_live_) avec permissions
      Products/Prices/PaymentLinks en écriture, la déposer dans /root/stripe.env
  - python3 -m pip install stripe

Usage :
  python3 create-payment-link.py create     # crée les 3 liens INACTIFS
  python3 create-payment-link.py activate   # VERROU : active les 3 liens
  python3 create-payment-link.py status     # affiche l'état sans rien modifier

Après création (liens inactifs) :
  1. /opt/data/citescan-links.json est écrit (status: pending_activation)
  2. offre.html + en/offer.html : renseigner STRIPE_PAYMENT_LINKS {29,39,49}
     (les URLs buy.stripe.com existent déjà, inaccessibles tant qu'inactives)
Après activation (verrou levé par Franck) :
  3. Décommenter les formulaires de commande des 2 pages offre, push + deploy
  4. Test bout-en-bout avec un achat réel remboursé (verrou Franck)
"""

import json
import os
import sys
from pathlib import Path

STRIPE_ENV = Path("/root/stripe.env")
LINKS_JSON = Path("/opt/data/citescan-links.json")
ACTIVATION_GATE = "OUI-FRANCK-A-VALIDE"
CURRENCY = "eur"
SUCCESS_URL_FR = "https://citescan.brozapi.com/merci.html"

TIERS = [
    {
        "price_cents": 2900,
        "eur": 29,
        "name": "CiteScan — Audit Perplexity + Gemini",
        "description": (
            "Audit CiteScan : 4 contrôles techniques approfondis, détection de "
            "citations sur 15 requêtes buyer-intent testées sur Perplexity ET "
            "Gemini, tableau comparatif par moteur, plan d'action priorisé, "
            "rapport PDF 10-15 pages + page HTML privée, re-scan gratuit à "
            "J+30. Livraison sous 24 h. Garantie satisfait ou remboursé 7 jours."
        ),
        "metadata": {"product": "citescan_audit", "version": "2",
                     "tier": "29", "engines": "perplexity,gemini"},
    },
    {
        "price_cents": 3900,
        "eur": 39,
        "name": "CiteScan — Audit Perplexity + Gemini + 1 IA au choix",
        "description": (
            "Audit CiteScan : tout le palier 29 € (Perplexity + Gemini) PLUS "
            "une IA supplémentaire au choix (ChatGPT ou Claude) : 15 requêtes "
            "buyer-intent par moteur, tableau comparatif, plan d'action "
            "priorisé, rapport PDF + page HTML privée, re-scan gratuit à J+30. "
            "Livraison sous 24 h. Garantie 7 jours."
        ),
        "metadata": {"product": "citescan_audit", "version": "2",
                     "tier": "39", "engines": "perplexity,gemini,+1-au-choix"},
    },
    {
        "price_cents": 4900,
        "eur": 49,
        "name": "CiteScan — Audit complet 4 IA",
        "description": (
            "Audit CiteScan complet : 15 requêtes buyer-intent testées sur les "
            "4 IA (Perplexity, Gemini, ChatGPT, Claude), tableau comparatif de "
            "visibilité par moteur, analyse des écarts entre IA, plan d'action "
            "priorisé, rapport PDF 10-15 pages + page HTML privée, re-scan "
            "gratuit à J+30. Livraison sous 24 h. Garantie 7 jours."
        ),
        "metadata": {"product": "citescan_audit", "version": "2",
                     "tier": "49", "engines": "perplexity,gemini,chatgpt,claude"},
    },
]


def load_stripe_key() -> str:
    """Charge la clé Stripe depuis /root/stripe.env (jamais depuis le repo).
    Accepte STRIPE_SECRET_KEY / STRIPE_LIVE_KEY (sk_live_) ou
    STRIPE_RESTRICTED_KEY (rk_live_)."""
    if not STRIPE_ENV.exists():
        sys.exit(f"❌ Fichier {STRIPE_ENV} introuvable. Clé Stripe LIVE requise.\n"
                 "   → Franck : dashboard Stripe → Développeurs → Clés API →\n"
                 "     créer une clé restreinte rk_live_ (Products, Prices,\n"
                 "     PaymentLinks en écriture) puis :\n"
                 "     echo 'STRIPE_RESTRICTED_KEY=rk_live_...' > /root/stripe.env")
    for line in STRIPE_ENV.read_text().splitlines():
        line = line.strip()
        for var in ("STRIPE_SECRET_KEY", "STRIPE_LIVE_KEY", "STRIPE_RESTRICTED_KEY"):
            if line.startswith(var + "="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if not (key.startswith("sk_live_") or key.startswith("rk_live_")):
                    sys.exit("❌ La clé trouvée n'est pas une clé LIVE "
                             "(sk_live_/rk_live_). Pas de clé test autorisée.")
                return key
    sys.exit(f"❌ Aucune variable Stripe utilisable dans {STRIPE_ENV}")


def load_links_file() -> dict:
    if LINKS_JSON.exists():
        return json.loads(LINKS_JSON.read_text())
    return {}


def cmd_create(stripe) -> None:
    existing = load_links_file()
    if existing.get("payment_link_ids"):
        sys.exit("❌ Des liens existent déjà dans "
                 f"{LINKS_JSON} (status={existing.get('status')}).\n"
                 "   Refus de créer des doublons. Utilisez 'status' ou 'activate'.")

    print("⚠  Création de 3 Payment Links Stripe LIVE — CiteScan 29/39/49 €")
    print("   Les liens seront créés INACTIFS (active=false) : aucun encaissement")
    print("   possible tant que le verrou Franck n'est pas levé (mode 'activate').")
    confirm = input("   Taper 'CREER-INACTIFS' pour continuer : ").strip()
    if confirm != "CREER-INACTIFS":
        sys.exit("❌ Annulé.")

    links_json = {}          # format poller /root/citescan-deliveries.py
    payment_link_ids = {}    # palier -> id, pour l'activation ultérieure
    for tier in TIERS:
        product = stripe.Product.create(
            name=tier["name"], description=tier["description"])
        price = stripe.Price.create(
            product=product.id, unit_amount=tier["price_cents"], currency=CURRENCY)
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            active=False,  # ← PENDING ACTIVATION : verrou Franck n°3
            after_completion={"type": "redirect",
                              "redirect": {"url": SUCCESS_URL_FR}},
            consent_collection={"terms_of_service": "required"},
            custom_text={
                "terms_of_service_acceptance": {
                    "message": (
                        "J'accepte les [CGV](https://citescan.brozapi.com/cgv.html) "
                        "et je renonce expressément à mon droit de rétractation pour "
                        "ce contenu numérique fourni immédiatement (art. L.221-28 13°). "
                        "Garantie commerciale satisfait ou remboursé 7 jours."
                    ),
                },
            },
            metadata=tier["metadata"],
        )
        print(f"✓ Palier {tier['eur']} € : {link.url}  ({link.id}) — INACTIF, "
              "en attente d'activation")
        links_json[link.url] = ["audit", f"Audit CiteScan {tier['eur']} €",
                                tier["eur"]]
        payment_link_ids[str(tier["eur"])] = link.id

    payload = {
        "status": "pending_activation",
        "note": "Liens créés INACTIFS. Activation = verrou Franck "
                "(python3 create-payment-link.py activate).",
        "links": links_json,
        "payment_link_ids": payment_link_ids,
    }
    LINKS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    print()
    print("=" * 70)
    print(f"  Écrit : {LINKS_JSON} (status: pending_activation)")
    print()
    print("  STRIPE_PAYMENT_LINKS pour offre.html + en/offer.html :")
    for url, (_, _, eur) in sorted(links_json.items(), key=lambda kv: kv[1][2]):
        print(f"     {eur}: \"{url}\"")
    print()
    print("  ⚠  LIENS INACTIFS — aucun paiement possible.")
    print("  Activation (verrou Franck) : python3 create-payment-link.py activate")
    print("=" * 70)


def cmd_activate(stripe) -> None:
    data = load_links_file()
    ids = data.get("payment_link_ids")
    if not ids:
        sys.exit(f"❌ Aucun lien à activer dans {LINKS_JSON}. "
                 "Lancez d'abord le mode 'create'.")
    if data.get("status") == "active":
        sys.exit("ℹ  Liens déjà actifs, rien à faire.")

    print("⚠  ACTIVATION des 3 Payment Links CiteScan — encaissement réel possible")
    print("   immédiatement après cette étape. Verrou Franck n°3.")
    confirm = input(f"   Taper '{ACTIVATION_GATE}' pour activer : ").strip()
    if confirm != ACTIVATION_GATE:
        sys.exit("❌ Annulé. Verrou Franck non levé — les liens restent INACTIFS.")

    for eur in sorted(ids, key=int):
        stripe.PaymentLink.update(ids[eur], active=True)
        print(f"✓ Palier {eur} € activé ({ids[eur]})")

    data["status"] = "active"
    data.pop("note", None)
    LINKS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print()
    print("✅ Liens ACTIFS. Reste à faire :")
    print("   1. Décommenter les formulaires de offre.html + en/offer.html")
    print("   2. Push + deploy")
    print("   3. Test achat réel remboursé (verrou Franck)")


def cmd_status(stripe) -> None:
    data = load_links_file()
    if not data:
        sys.exit(f"ℹ  {LINKS_JSON} absent — liens non créés (mode 'create').")
    print(f"status: {data.get('status')}")
    for url, (_, label, eur) in sorted(data.get("links", {}).items(),
                                       key=lambda kv: kv[1][2]):
        lid = data.get("payment_link_ids", {}).get(str(eur), "?")
        print(f"  {eur} € — {label}\n      {url} ({lid})")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "create"
    if mode not in ("create", "activate", "status"):
        sys.exit("Usage: create-payment-link.py [create|activate|status]")

    if mode == "status" and load_links_file():
        cmd_status(None)
        return

    try:
        import stripe  # type: ignore
    except ImportError:
        sys.exit("❌ Module 'stripe' manquant. Installez-le : pip install stripe")

    stripe.api_key = load_stripe_key()  # type: ignore[attr-defined]

    if mode == "create":
        cmd_create(stripe)
    elif mode == "activate":
        cmd_activate(stripe)
    else:
        cmd_status(stripe)


if __name__ == "__main__":
    main()
