#!/usr/bin/env python3
"""
CiteScan — Création des 3 Stripe Payment Links multi-moteurs (29/39/49 €).

⚠ VERROU FRANCK (n°3) — À N'EXÉCUTER QU'APRÈS VALIDATION EXPLICITE DE FRANCK.
Ce script crée des Payment Links LIVE qui peuvent encaisser de l'argent réel.

Grille validée par Franck (2026-08-24, t_9864864c) :
  - 29 € : Perplexity + Gemini
  - 39 € : 29 € + ChatGPT OU Claude au choix (choix côté client)
  - 49 € : les 4 IA (« audit complet »)
Re-scan J+30 gratuit conservé sur tous les paliers (mêmes moteurs).

Prérequis :
  - Clé Stripe LIVE dans /root/stripe.env (host-only, jamais dans le repo)
  - python3 -m pip install stripe  (ou stripe-cli en fallback)

Usage :
  python3 create-payment-link.py

Le script affiche les 3 URLs à :
  1. copier dans offre.html et en/offer.html (STRIPE_PAYMENT_LINKS {29,39,49}
     dans le formulaire commenté — VERROU : décommenter seulement après GO) ;
  2. enregistrer dans /opt/data/citescan-links.json pour le poller de livraison
     (le 3e élément = palier EUR, utilisé pour borner les moteurs audités).

Après création :
  1. Écrire /opt/data/citescan-links.json (snippet affiché par le script)
  2. Décommenter les formulaires de commande des 2 pages offre
  3. Push + deploy
  4. Test bout-en-bout avec un achat réel remboursé (verrou Franck)
"""

import os
import sys
from pathlib import Path

STRIPE_ENV = Path("/root/stripe.env")
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
        sys.exit(f"❌ Fichier {STRIPE_ENV} introuvable. Clé Stripe LIVE requise.")
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


def main() -> None:
    try:
        import stripe  # type: ignore
    except ImportError:
        sys.exit("❌ Module 'stripe' manquant. Installez-le : pip install stripe")

    stripe.api_key = load_stripe_key()

    print("⚠  Création de 3 Payment Links Stripe LIVE — CiteScan 29/39/49 €")
    confirm = input("   Taper 'OUI-FRANCK-A-VALIDE' pour continuer : ").strip()
    if confirm != "OUI-FRANCK-A-VALIDE":
        sys.exit("❌ Annulé. Verrou Franck non levé.")

    links_json_snippet = {}
    for tier in TIERS:
        product = stripe.Product.create(
            name=tier["name"], description=tier["description"])
        price = stripe.Price.create(
            product=product.id, unit_amount=tier["price_cents"], currency=CURRENCY)
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
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
        print(f"✓ Palier {tier['eur']} € : {link.url}  ({link.id})")
        links_json_snippet[link.url] = ["audit", f"Audit CiteScan {tier['eur']} €",
                                        tier["eur"]]

    print()
    print("=" * 70)
    print("  1. /opt/data/citescan-links.json :")
    print()
    import json
    print(json.dumps({"links": links_json_snippet}, ensure_ascii=False, indent=2))
    print()
    print("  2. offre.html + en/offer.html : renseigner STRIPE_PAYMENT_LINKS")
    for tier in TIERS:
        for url in links_json_snippet:
            if links_json_snippet[url][2] == tier["eur"]:
                print(f"     {tier['eur']}: \"{url}\"")
    print("     puis décommenter les formulaires (VERROU déjà levé à cette étape).")
    print("  3. Push + deploy ; 4. Test achat réel remboursé (verrou Franck).")
    print("=" * 70)


if __name__ == "__main__":
    main()
