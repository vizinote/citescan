# Stripe — CiteScan (29 € one-shot)

## ⚠ Verrou Franck (n°3)

**Le paiement Stripe ne doit PAS être activé tant que Franck n'a pas explicitement validé.**
Tant que le verrou est actif :

- La page `/offre` affiche un bouton **désactivé** avec une notice explicative.
- Le script `create-payment-link.py` est présent mais **jamais exécuté** (demande de confirmation interactive `OUI-FRANCK-A-VALIDE`).
- Aucun Payment Link n'est lié au site.

## État actuel (carte 2 terminée)

| Élément | Statut |
|---|---|
| Page `/offre` FR + EN | ✅ créée, CTA désactivé |
| Page `/merci` FR + EN | ✅ créée (noindex) |
| CGV FR + EN | ✅ créées (7 jours garantie, rétractation L.221-28 13°) |
| Mentions légales FR + EN | ✅ créées (RGPD, médiation CM2C) |
| Script création Payment Link | ✅ prêt, **non exécuté** |
| Payment Link LIVE | ❌ **non créé** (verrou Franck) |
| Lien sur la page offre | ❌ **non lié** (verrou Franck) |

## Procédure d'activation (quand Franck valide)

1. **Créer le Payment Link** (sur le VPS, avec la clé LIVE dans `/root/stripe.env`) :
   ```bash
   cd /chemin/vers/citescan/stripe
   python3 create-payment-link.py
   # Taper 'OUI-FRANCK-A-VALIDE' à la confirmation
   # Copier l'URL affichée (https://buy.stripe.com/...)
   ```

2. **Lier le Payment Link aux pages** :
   - `offre.html` et `en/offer.html` : remplacer le `<button disabled>` par le formulaire
     domaine → Stripe fourni en commentaire dans chaque page (constante `STRIPE_PAYMENT_LINK`
     à renseigner). Le formulaire redirige vers
     `<URL>?client_reference_id=<domaine>|<lang>` : **c'est ce qui permet au poller de
     livraison de savoir quel site auditer et dans quelle langue rédiger le rapport.**
   - Supprimer le bloc `.cta-disabled-notice`

3. **Enregistrer le lien pour le poller de livraison** (carte 4) : créer sur le VPS
   `/opt/data/citescan-links.json` :
   ```json
   {"links": {"https://buy.stripe.com/<id>": ["audit", "Audit CiteScan 29 €"]}}
   ```
   Sans ce fichier, `/root/citescan-deliveries.py` ignore toutes les sessions (rien n'est livré).

4. **Commit + push + deploy** sur `citescan.brozapi.com`.

5. **Test bout-en-bout** (carte 5) : achat réel de 29 € → vérifier la réception du rapport → rembourser via le dashboard Stripe (tout remboursement reste un verrou Franck).

## Clés et secrets

- **Jamais** de clé Stripe dans le repo (`.gitignore` le garantit, mais vigilance).
- Clé LIVE : `/root/stripe.env` sur le VPS (host-only, non commitée).
- Clé publique (publishable) : pas nécessaire — on utilise un Payment Link hébergé par Stripe, pas Stripe.js.

## Architecture choisie

**Payment Link Stripe hébergé** (pas d'intégration Stripe.js) :
- Aucun code côté client à sécuriser
- Pas de clé publique exposée
- Stripe gère la page de paiement (PCI-DSS out-of-scope)
- Redirection après paiement vers `/merci.html` (noindex)
- Le domaine à auditer + la langue du parcours voyagent dans `client_reference_id`
  (format `<domaine>|<lang>`, ex. `example.com|fr`), posé par le formulaire de la page offre
- Pas de webhook : livraison par polling (`/root/citescan-deliveries.py`, cron */5,
  calqué sur `/root/accessicheck-deliveries.py`) — voir carte 4

## Tarification Stripe

- Commission Stripe : 1,4 % + 0,25 € (cartes UE) → **~0,66 €** par vente de 29 €
- Commission Stripe : 2,9 % + 0,25 € (cartes non-UE) → **~1,09 €** par vente de 29 €
- Pas de frais mensuels (plan standard)

## Test

Pour tester sans argent réel : utiliser le mode test Stripe (clé `sk_test_...` dans un environnement séparé) avec la carte `4242 4242 4242 4242`. **Jamais en prod.**
