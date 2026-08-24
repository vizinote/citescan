#!/usr/bin/env python3
"""
CiteScan — Création du Stripe Payment Link (29 € one-shot).

⚠ VERROU FRANCK (n°3) — À N'EXÉCUTER QU'APRÈS VALIDATION EXPLICITE DE FRANCK.
Ce script crée un Payment Link LIVE qui peut encaisser de l'argent réel.

Prérequis :
  - Clé Stripe LIVE dans /root/stripe.env (host-only, jamais dans le repo)
  - python3 -m pip install stripe  (ou stripe-cli en fallback)

Usage :
  python3 create-payment-link.py

Le script affiche le Payment Link URL à copier dans offre.html et en/offer.html
(remplacer REPLACE_WITH_STRIPE_PAYMENT_LINK).

Après création :
  1. Activer le webhook Stripe (carte 4 - pipeline d'audit)
  2. Remplacer le bouton désactivé par <a href="<URL>"> dans les 2 pages offre
  3. Push + deploy
  4. Test bout-en-bout avec un achat réel remboursé (carte 5)
"""

import os
import sys
from pathlib import Path

STRIPE_ENV = Path("/root/stripe.env")
PRODUCT_NAME = "CiteScan — Audit complet"
PRODUCT_DESCRIPTION = (
    "Audit complet CiteScan : 4 contrôles techniques approfondis, "
    "détection de citations sur 15 requêtes Perplexity, plan d'action priorisé, "
    "rapport PDF 10-15 pages + page HTML privée. Livraison sous 24 h. "
    "Garantie satisfait ou remboursé 7 jours."
)
PRICE_EUR_CENTS = 2900  # 29,00 €
CURRENCY = "eur"
SUCCESS_URL_FR = "https://citescan.brozapi.com/merci.html"
SUCCESS_URL_EN = "https://citescan.brozapi.com/en/thanks.html"


def load_stripe_key() -> str:
    """Charge la clé Stripe depuis /root/stripe.env (jamais depuis le repo)."""
    if not STRIPE_ENV.exists():
        sys.exit(f"❌ Fichier {STRIPE_ENV} introuvable. Clé Stripe LIVE requise.")
    for line in STRIPE_ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("STRIPE_SECRET_KEY=") or line.startswith("STRIPE_LIVE_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not key.startswith("sk_live_"):
                sys.exit("❌ La clé trouvée n'est pas une clé LIVE (sk_live_...). "
                         "Pas de clé test autorisée pour la prod.")
            return key
    sys.exit(f"❌ Aucune variable STRIPE_SECRET_KEY / STRIPE_LIVE_KEY dans {STRIPE_ENV}")


def main() -> None:
    try:
        import stripe  # type: ignore
    except ImportError:
        sys.exit("❌ Module 'stripe' manquant. Installez-le : pip install stripe")

    stripe.api_key = load_stripe_key()

    print("⚠  Création d'un Payment Link Stripe LIVE — CiteScan 29 €")
    confirm = input("   Taper 'OUI-FRANCK-A-VALIDE' pour continuer : ").strip()
    if confirm != "OUI-FRANCK-A-VALIDE":
        sys.exit("❌ Annulé. Verrou Franck non levé.")

    # 1. Produit
    product = stripe.Product.create(
        name=PRODUCT_NAME,
        description=PRODUCT_DESCRIPTION,
    )
    print(f"✓ Produit créé : {product.id}")

    # 2. Prix
    price = stripe.Price.create(
        product=product.id,
        unit_amount=PRICE_EUR_CENTS,
        currency=CURRENCY,
    )
    print(f"✓ Prix créé : {price.id} ({PRICE_EUR_CENTS/100:.2f} {CURRENCY.upper()})")

    # 3. Payment Link (avec redirection vers /merci, la langue est gérée côté
    # site : Stripe redirige vers /merci.html par défaut ; la page merci
    # détecte la langue du navigateur et propose un lien vers /en/thanks.html)
    link = stripe.PaymentLink.create(
        line_items=[{"price": price.id, "quantity": 1}],
        after_completion={
            "type": "redirect",
            "redirect": {"url": SUCCESS_URL_FR},
        },
        # Demande explicite du consentement rétractation numérique
        consent_collection={
            "terms_of_service": "required",
        },
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
        metadata={
            "product": "citescan_audit",
            "version": "1",
        },
    )
    print(f"✓ Payment Link créé : {link.id}")
    print()
    print("=" * 70)
    print(f"  URL DU PAYMENT LINK : {link.url}")
    print("=" * 70)
    print()
    print("Prochaines étapes :")
    print("  1. Enregistrer le lien pour le poller de livraison (carte 4) :")
    print("     /opt/data/citescan-links.json →")
    print(f'     {{"links": {{"{link.url}": ["audit", "Audit CiteScan 29 €"]}}}}')
    print("  2. Copier cette URL dans offre.html et en/offer.html")
    print("     (décommenter le formulaire, constante STRIPE_PAYMENT_LINK)")
    print("  3. Push + deploy")
    print("  4. Carte 5 : test bout-en-bout avec achat réel remboursé (verrou Franck)")


if __name__ == "__main__":
    main()
