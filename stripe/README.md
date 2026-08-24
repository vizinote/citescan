# Stripe — CiteScan (29 € one-shot)

## ⚠ Verrou Franck (n°3)

**Le paiement Stripe ne doit PAS être activé tant que Franck n'a pas explicitement validé.**
Tant que le verrou est actif :

- La page `/offre` affiche un bouton **désactivé** avec une notice explicative.
- Les Payment Links existent (créés INACTIFS le 2026-08-24) mais **ne sont pas activés** : aucun encaissement possible, page Stripe « lien désactivé » pour tout visiteur. L'activation exige la saisie interactive de `OUI-FRANCK-A-VALIDE`.
- Le formulaire de commande des pages offre reste **commenté** (bouton désactivé visible).

## État actuel (liens créés le 2026-08-24, INACTIFS)

| Élément | Statut |
|---|---|
| Page `/offre` FR + EN | ✅ créée, CTA désactivé |
| Page `/merci` FR + EN | ✅ créée (noindex) |
| CGV FR + EN | ✅ créées (7 jours garantie, rétractation L.221-28 13°) |
| Mentions légales FR + EN | ✅ créées (RGPD, médiation CM2C) |
| Script création Payment Links | ✅ exécuté le 2026-08-24 |
| Payment Links LIVE 29/39/49 € | ✅ **créés INACTIFS** (`active=false`, status `pending_activation` dans `/opt/data/citescan-links.json`) |
| Liens sur les pages offre | ✅ URLs renseignées dans `STRIPE_PAYMENT_LINKS` (formulaire toujours commenté — verrou Franck) |
| Activation | ❌ **verrou Franck n°3** : `python3 create-payment-link.py activate` + saisie `OUI-FRANCK-A-VALIDE` |

Les 3 liens (inactifs, page Stripe « lien désactivé » pour tout visiteur) :
- 29 € : https://buy.stripe.com/aFa7sF3gB90F7tN33fcZa09
- 39 € : https://buy.stripe.com/9B69AN6sN3Gl4hBbzLcZa0a
- 49 € : https://buy.stripe.com/bJe00d8AV2Ch8xRcDPcZa0b

## Procédure en 2 phases (t_6808ea76)

**Phase 1 — Création INACTIVE** (autorisée par le GO pricing, t_9864864c) — FAITE 2026-08-24 :
```bash
cd /chemin/vers/citescan/stripe
python3 create-payment-link.py create
# Taper 'CREER-INACTIFS'. NB : l'API Stripe REFUSE le paramètre `active`
# à la création d'un Payment Link (parameter_unknown) — le script crée le
# lien puis le désactive immédiatement via PaymentLink.update(active=False).
# Écrit /opt/data/citescan-links.json (status: pending_activation).
# Piège hôte : le module python `stripe` n'est PAS installable sur l'hôte
# (pas de pip/ensurepip). Équivalent stdlib utilisé pour la création réelle :
# /root/stripe-create-stdlib.py (mêmes TIERS/clé/format JSON, importés du
# script canonique) + /root/stripe-cleanup-orphans.py.
```

**Phase 2 — ACTIVATION (verrou Franck n°3, manuel)** :
```bash
python3 create-payment-link.py activate
# Taper 'OUI-FRANCK-A-VALIDE' → les 3 liens passent active=true,
# encaissement réel possible à partir de cet instant.
```
Puis : décommenter les formulaires des 2 pages offre, push + deploy,
test bout-en-bout avec achat réel remboursé (verrou Franck).

**Après activation — rappel des étapes finales :**

1. **Lier les Payment Links aux pages** :
   - `offre.html` et `en/offer.html` : renseigner la constante `STRIPE_PAYMENT_LINKS`
     ({29,39,49} → URLs affichées par le script) dans le formulaire fourni en commentaire,
     décommenter le formulaire, supprimer le bloc `.cta-disabled-notice`. Le formulaire
     redirige vers `<URL>?client_reference_id=<domaine>|<lang>` : **c'est ce qui permet
     au poller de livraison de savoir quel site auditer et dans quelle langue rédiger
     le rapport.**
2. **Poller de livraison** : `/opt/data/citescan-links.json` est déjà écrit par le
   script (format `{"links": {"<url>": ["audit", "<label>", <eur>]}, ...}`).
   Sans ce fichier, `/root/citescan-deliveries.py` ignore toutes les sessions.
3. **Commit + push + deploy** sur `citescan.brozapi.com`.
4. **Test bout-en-bout** : achat réel → vérifier la réception du rapport → rembourser
   via le dashboard Stripe (tout remboursement reste un verrou Franck).

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
