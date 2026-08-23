# CiteScan — Spec MVP

> **Votre site est-il cité par ChatGPT et Perplexity ? Audit complet + plan d'action en 24 h, 29 €, sans abonnement.**

**Statut : spec Phase 2 (playbook lancement-micro-saas), suite Phase 1 validée (GO Franck 23/08/2026).**
**Domaine : citescan.brozapi.com (sous-domaine gratuit, aucun achat de domaine avant la 1re vente).**

---

## 1. Positionnement

| | |
|---|---|
| Cible | **Mondiale** : TPE/PME avec site existant, dépendantes du trafic SEO, inquiètes de la baisse de trafic Google liée aux réponses IA. Wedge de lancement = **FR** (SEO FR attaquable, angle « fait pour les TPE/PME françaises »), version EN dès le lancement pour l'international |
| Promesse | Savoir en 24 h si (et comment) ChatGPT et Perplexity citent votre site, et quoi faire pour être cité davantage |
| Prix | **29 € one-shot, sans abonnement** (affichage € ; Stripe gère la devise) |
| Différenciation | Les outils existants (Profound 99 $/mois, Otterly 29 $/mois, Semrush 99 $/mois) sont des abonnements enterprise/EN. Les gratuits (Frase, HubSpot AEO) sont des lead magnets superficiels. Le seul one-shot direct (Surmado, 50 $) est US. **Aucun audit one-shot self-service en français, et aucun acteur one-shot bilingue FR/EN à ce prix.** |
| Angle | Ce qui est vendu = le **plan d'action personnalisé dans la langue du client**, pas la détection |

---

## 2. Parcours utilisateur (3 écrans max)

### Écran 1 — Scan gratuit (`/`)
- Champ unique : URL du site.
- Résultat immédiat : **score de visibilité IA /100** (décomposition affichée) + 2-3 exemples réels (ex. « votre robots.txt bloque GPTBot », « Perplexity cite 2 concurrents sur « <requête> », pas vous »).
- CTA : « Recevoir l'audit complet + plan d'action — 29 € ».
- Anti-abus : 1 scan/IP/heure, domaine normalisé, cache 24 h.

### Écran 2 — Page de vente (`/offre`)
- Ce que contient l'audit payant (voir §4), livré sous 24 h, garantie satisfait/remboursé 7 j.
- Bouton **Stripe Payment Link** (29 €, produit créé une fois, pas d'API côté site) avec `?client_reference_id=<domaine>` ou champ email.
- Après paiement : page merci « rapport en préparation, livraison sous 24 h ».

### Écran 3 — Livraison (email)
- Email à l'acheteur : PDF du rapport en pièce jointe + lien vers la **page HTML privée** du rapport (URL à token non devinable, hébergée sur citescan.brozapi.com/rapports/<token>).

---

## 3. Audit gratuit (technique, coût zéro)

Analyse automatisée du site, 100 % locale :

| Contrôle | Détail |
|---|---|
| robots.txt bots IA | GPTBot, ClaudeBot, PerplexityBot, Google-Extended, CCBot… : bloqués / autorisés / absents |
| Extractabilité | Contenu principal accessible sans JS (fetch simple vs rendu), poids du texte, titres Hn |
| Données structurées | Présence JSON-LD (Organization, Article, FAQ, Product…), validité basique |
| E-E-A-T de base | Page à propos, mentions légales, auteur identifié, dates de publication, HTTPS, sitemap |

Chaque contrôle → points vers le score /100 + verdict affiché à l'écran 1. Aucun appel externe payant.

---

## 4. Audit payant (29 €) — ce qui est livré

1. **Les 4 contrôles techniques approfondis** (§3, version détaillée avec extraits et corrections prêtes à copier).
2. **Détection réelle de citations** : 15 requêtes buyer-intent (dans la langue du site audité) générées à partir du secteur/offre du site, envoyées à **Perplexity Sonar API** (`sonar`, context low, citations activées). Pour chaque requête : le domaine du client est-il cité ? quels concurrents sont cités ?
   - Coût : ~0,15 $/audit (crédits pay-as-you-go, GO Franck 23/08).
   - **Intégration triviale : variable d'environnement `PERPLEXITY_API_KEY`** injectée dans le conteneur. Rien d'autre à configurer. Sans la clé, le pipeline tombe en mode dégradé (audit technique seul) — jamais d'échec silencieux.
3. **Plan d'action priorisé** : 5-10 actions concrètes classées impact/effort (débloquer les bots IA, ajouter du JSON-LD FAQ, créer du contenu citant des sources, etc.), rédigé **dans la langue du parcours (FR ou EN)**, spécifique au site.
4. **Rapport** : PDF (10-15 pages, charte CiteScan) + page HTML privée. Générés par les agents, 100 % automatisés.

Livraison : **poller Stripe** sur le modèle de `/root/accessicheck-deliveries.py` (paiement → lancement pipeline audit → email PDF+lien). Log des ventes : `/opt/data/citescan-sales.log` (date, email, domaine, statut).

---

## 5. Architecture technique

- **Site + API** : un conteneur Docker sur le VPS Ionos (même pattern que les autres produits Brozapi), derrière Caddy : `citescan.brozapi.com`. Aucun coût récurrent nouveau (hors crédits Perplexity déjà validés, ~5 $).
- **Stack proposée** : Python + FastAPI (scan + endpoints), site statique/SSR léger, Jinja2 pour le rapport HTML, WeasyPrint pour le PDF (même pile que BadgeIA/AccessiCheck → réutilisation des skills).
- **Base de données** : SQLite dans le conteneur (scans, rapports, tokens). Rien d'autre.
- **Secrets** : `PERPLEXITY_API_KEY` et clé Stripe en variables d'environnement (fichier `.env` hors repo, passé au conteneur). **Clé Perplexity déjà reçue et testée (Kimi) — aucune action humaine requise côté API.**
- **Bilingue dès le lancement** : version **EN par défaut** (internationale) + version **FR** (wedge SEO de lancement, angle « fait pour les TPE/PME françaises » : France Num, SEO français, rapport en français). hreflang FR/EN, détection de la langue du navigateur, bascule manuelle visible dans le header.
- **Textes** : 100 % externalisés (`textes/en.json`, `textes/fr.json`) — aucune chaîne en dur, l'EN suit sans refonte.
- **Rapport client** : livré dans la langue du parcours d'achat (FR ou EN) ; templates de rapport bilingues.

---

## 6. Identité visuelle

Distincte de BadgeIA (navy) et AccessiCheck (bleu profond #1d4ed8 + ambre) :

| | |
|---|---|
| Couleur principale | **Indigo/violet profond #6d28d9** (violet 700) |
| Accent | **Vert émeraude #10b981** (signal « cité ✓ ») |
| Fond | Blanc cassé #fafaf9, texte ardoise #1e293b |
| Logo | Monoligne : loupe stylisée + guillemet « " » dans sa lentille (citation), SVG simple, déclinable en favicon |
| Ton | Direct, rassurant, zéro jargon (expliquer « cité par une IA » en une phrase). FR et EN dès le lancement |

Contrastes vérifiés WCAG AA (violet #6d28d9 sur blanc : ratio ~6,8).

---

## 7. Découpage en cartes dev (≤ 5)

1. **Carte 1 — Site vitrine bilingue + scan gratuit** : landing écran 1 (EN défaut + FR, hreflang, détection navigateur, bascule manuelle), API d'analyse technique (§3), score /100, charte violet/émeraude, textes externalisés (en.json/fr.json), déploiement citescan.brozapi.com.
2. **Carte 2 — Vente Stripe** : page /offre, Payment Link 29 €, page merci, mention légale/CGV, garantie.
3. **Carte 3 — Pipeline d'audit payant** : génération des 15 requêtes, client Perplexity Sonar (`PERPLEXITY_API_KEY`), détection de citations, mode dégradé sans clé.
4. **Carte 4 — Rapport + livraison** : template HTML privé, PDF WeasyPrint, plan d'action automatisé, poller Stripe → email (calqué sur accessicheck-deliveries.py), log `/opt/data/citescan-sales.log`.
5. **Carte 5 — Durcissement + lancement** : anti-abus, monitoring/healthcheck (même cron que les autres produits), page statut, SEO de base (og, sitemap), test bout-en-bout avec un achat réel remboursé.

Après le build : exploitation 100 % agents (livraisons, healthcheck, log ventes). Seule action humaine restante : validation des publications (verrou #2).

---

## 8. Critères de passage Phase 2 → Phase 3

- [x] Promesse et parcours 3 écrans définis
- [x] MVP = audit technique gratuit + 15 requêtes Perplexity Sonar (~0,15 $/audit) + rapport PDF
- [x] Livraison calquée sur accessicheck-deliveries.py + log /opt/data/citescan-sales.log
- [x] Conteneur Docker VPS, zéro coût récurrent nouveau
- [x] Intégration clé Perplexity triviale (`PERPLEXITY_API_KEY`), mode dégradé documenté
- [x] Identité visuelle distincte (indigo #6d28d9 + émeraude #10b981)
- [x] Bilingue dès le lancement : EN par défaut + FR (wedge SEO), hreflang, bascule manuelle, textes 100 % externalisés, rapport dans la langue du parcours
- [x] Réalisable en 5 cartes dev, opérable ensuite à 100 % par les agents

**Verrou humain en Phase 3 (build)** : activation Stripe (verrou #3 — validation Franck avant mise en production du paiement). La clé Perplexity est déjà reçue et testée.
