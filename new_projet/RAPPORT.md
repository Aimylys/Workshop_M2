# Resilience-Alpha — Mini-rapport

*Workshop EPSI « PROJECT RESILIENCE-ALPHA » — plateforme de paiement fictive à reprise autonome.*

## 1. Objectif

Démontrer une plateforme de paiement **entièrement fictive** capable de **détecter une
cyberattaque et de se rétablir toute seule**, sans intervention humaine (*Zero-Touch Recovery*).
Tout se passe sur un **réseau fermé**, avec des **données 100 % fictives**.

## 2. Architecture (en bref)

Un seul point d'entrée (le WAF) protège des microservices isolés ; tout est observé en continu.

```
PC attaquant / navigateur ──► WAF (ModSecurity + OWASP CRS)
                                 │
                        frontend (React) ──► auth (JWT) ──► payment-api ──► base PostgreSQL
                                 │
                 Observabilité : Prometheus (métriques) · Loki (journaux/SIEM) · Grafana
```

| Brique | Rôle |
|---|---|
| **WAF** | Seule porte d'entrée ; bloque les attaques web et les IP malveillantes |
| **auth / payment-api** | Connexion (JWT) et virements fictifs, atomiques |
| **base PostgreSQL** | Un rôle par service, droits minimaux |
| **Prometheus / Loki / Grafana** | Mesure le trafic, centralise les journaux, visualise |

## 3. La chaîne de résilience

Trois rôles **séparés** (exigence du sujet) :

1. **Collecte** — Prometheus et Loki enregistrent le trafic et les journaux en permanence.
2. **Détection (décide)** — un modèle de similarité **kNN** compare l'état courant à des profils
   connus et dit : *trafic normal*, ou *attaque* (DDoS, force brute, injection SQL, scan, panne).
3. **Explication (RAG / LLM, explique)** — un assistant local (Ollama) explique en langage clair
   *ce qui se passe* et *quoi faire*. **Il explique, il ne décide pas.**
4. **Remédiation (agit)** — dès qu'une attaque est confirmée, une action prédéfinie est exécutée,
   **vérifiée**, puis tracée.

## 4. Remédiation automatique (le cœur de la démo)

Pour chaque incident : **verdict → action → vérification → journal**.

| Type d'attaque | Action automatique |
|---|---|
| Panne de service | Redémarre le conteneur, **vérifie** la reprise (santé + transaction de test réussie) |
| DDoS | Bloque l'IP source / stoppe l'attaque, redémarre l'API si besoin, vérifie |
| Force brute / scan | Bloque la source, surveille |
| Injection SQL | **Confinement seul** : bloque la source, alerte — jamais « résolu » sans analyse humaine |

La remédiation a des **droits minimaux** : uniquement des actions prédéfinies sur des cibles
connues (IP validée, liste blanche de services), **jamais de commande arbitraire**. Elle ne peut
donc pas devenir elle-même une faille.

## 5. Sécurité en place

- Données **fictives** ; aucun secret en clair dans le code (secrets séparés, chiffrés).
- WAF en **mode blocage** (OWASP CRS) ; journaux sans mots de passe ni jetons.
- Conteneurs durcis (non-root, lecture seule, privilèges retirés) ; réseaux internes isolés.
- Rôles SQL séparés : chaque service ne peut faire que le strict nécessaire.
- Toutes les attaques restent sur le **réseau fermé de l'équipe**, jamais sur le campus.

## 6. Démonstration *Zero-Touch*

1. On provoque un incident : arrêt d'un service, ou attaque lancée depuis le PC attaquant.
2. **Sans toucher à rien** : le tableau de bord SOC passe en « ATTAQUE », l'assistant explique,
   puis le **journal de remédiation** se remplit (détection → confinement/redémarrage →
   vérification → résolu) et le service repart.
3. Résultat validé : une panne de base de données est détectée et **réparée automatiquement en
   ~14 s**, confirmée par une transaction de test réussie.

## 7. Limites connues

- Démo sur une machine à 2 cœurs : les attaques sont volontairement **modérées** (produire la
  signature, pas écrouler l'hôte).
- La détection des attaques **réseau** dépend du modèle entraîné : un ré-entraînement sur les
  attaques douces fiabilise les verdicts. La reprise sur **panne** fonctionne indépendamment.

---

*Deux interfaces : une page pour **lancer** les attaques, une page **SOC** pour visualiser le
trafic, le verdict, l'explication et la remédiation en direct.*
