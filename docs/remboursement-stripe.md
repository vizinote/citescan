# Procédure de remboursement CiteScan (garantie 7 jours)

> **R4 — Verrou humain.** Tout remboursement est une décision de Franck.
> Hermes ne rembourse JAMAIS tout seul : il prépare les éléments, Franck clique.

## Cadre

- L'offre CiteScan (29 € one-shot) est vendue avec une **garantie 7 jours** :
  tout client remboursé sur simple demande dans les 7 jours suivant le paiement.
- Paiement via **Stripe Payment Link** (activation = verrou Franck n°3, jamais sans validation).
- Les ventes sont journalisées dans `/opt/data/citescan-sales.log` (VPS) :
  date ISO, offre, email client, domaine audité, id de session Stripe, token du rapport.

## Quand un client demande un remboursement

1. **Identifier le paiement**
   - Email client → chercher la ligne correspondante dans `/opt/data/citescan-sales.log`
     (ou directement dans le dashboard Stripe : *Paiements*, filtrer par email).
   - Noter l'id de session/`pi_...` et la date de paiement.
2. **Vérifier la garantie**
   - ≤ 7 jours après le paiement → remboursement de droit, sans discussion.
   - \> 7 jours → décision commerciale de Franck (hors garantie).
3. **Validation Franck (verrou)**
   - Hermes envoie à Franck sur Telegram : email, montant, date, id paiement, lien
     direct vers le paiement dans le dashboard Stripe.
   - Franck répond « OK » / « non ». **Aucun remboursement sans ce OK explicite.**
4. **Exécution (par Franck, 30 secondes)**
   - Dashboard Stripe → *Paiements* → ouvrir le paiement → bouton **Rembourser**
     → montant total (29 €) → *Rembourser*.
   - Stripe rembourse la carte du client sous 5 à 10 jours ouvrés et envoie
     automatiquement un reçu de remboursement au client.
5. **Traçabilité**
   - Hermes ajoute une ligne `REFUND` dans `/opt/data/citescan-sales.log`
     (date, email, id paiement, montant) après confirmation de Franck.
   - Le rapport privé (`/rapports/<token>`) reste accessible au client : il a été
     livré ; le remboursement ne supprime pas la donnée (sauf demande RGPD, auquel cas
     suppression manuelle de la ligne SQLite `reports` + du token).

## Litiges (chargebacks)

- Un client peut aussi contester via sa banque. Stripe prélève alors des frais
  (~15 €) même en cas de victoire. D'où la garantie 7 jours « sans discussion » :
  **toujours moins chère qu'un chargeback**. Si Franck hésite, rembourser vite.
- En cas de chargeback, répondre via le dashboard Stripe (*Paiements → Litiges*)
  avec : preuve de livraison (email + lien rapport + horodatage `citescan-sales.log`).

## Ce que Hermes peut faire seul

- Chercher le paiement, vérifier le délai, préparer la demande de validation,
  logger le remboursement après coup.

## Ce que Hermes ne fait JAMAIS

- Cliquer « Rembourser » (aucune clé Stripe avec droits d'écriture n'est configurée —
  et c'est volontaire).
- Modifier les Payment Links ou activer le paiement (verrou n°3).
