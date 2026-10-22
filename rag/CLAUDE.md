# Contexte projet — Resilience-Alpha (Workshop M2)

Ce fichier donne le contexte à Claude Code pour travailler sur ce projet.

## Objectif du projet

Démontrer une plateforme de paiement capable de **détecter une cyberattaque et
se rétablir automatiquement** (Zero-Touch Recovery), sans intervention humaine.
Chaîne complète : attaque → détection → remédiation automatique → vérification.

5 piliers : Développement, Infrastructure, IA/Data, Cybersécurité, Gouvernance.

## Architecture générale

```
PC attaquant ──(attaques réseau)──► API paiement ──► Prometheus ──► Détection (règles/ML) ──► Remédiation
                                         │                              │
                                    /metrics                        RAG (Ollama+FAISS) ──► explique à l'opérateur
```

- Les attaques (DDoS, brute force, injection SQL, panne) partent d'un 2e PC.
- Prometheus collecte les KPI de l'API toutes les 5 s.
- La détection identifie le type d'attaque à partir des KPI.
- Le RAG (LLM local) explique l'incident et la remédiation à l'opérateur.
- La remédiation (`infra/remediation/`) agit automatiquement (bloquer IP, redémarrer…).

## Composants de ce dossier (`rag/`)

| Fichier | Rôle |
|---|---|
| `api/main.py` | **API de paiement PROTOTYPE** (voir note ci-dessous) |
| `collector/collect.py` | Interroge Prometheus, écrit un CSV de KPI étiquetés |
| `ai/build_index.py` | Construit l'index FAISS (fiches + profils du CSV) |
| `ai/rag_analyze.py` | Détection par règles + explication RAG |
| `api/dashboard_server.py` + `api/dashboard.html` | Dashboard web temps réel |
| `ai/attack_knowledge.md` | Base de connaissance des attaques |

## ⚠️ NOTE IMPORTANTE : l'API de ce dossier est un PROTOTYPE

`rag/api/main.py` est une **fausse API de paiement**, créée uniquement pour :
- produire des KPI réalistes,
- tester la détection et le RAG en local.

**Ce n'est PAS le vrai système de paiement de l'équipe.** Le vrai système
(pilier Dev) est dans `services/api/main.py` et devra être branché à la place.
Tout le reste (collecteur, détection, RAG, dashboard) est conçu pour être
réutilisé tel quel, à condition d'adapter la source des KPI.

## Comment adapter le RAG/détection à la VRAIE API de paiement

La détection et le RAG ne connaissent l'API qu'à travers les **métriques
Prometheus**. Étapes :

1. **Instrumenter la vraie API.** Endpoint `/metrics` au format Prometheus, avec
   au minimum :
   - un compteur de requêtes par statut HTTP,
   - un compteur d'échecs / succès de connexion,
   - un compteur d'erreurs applicatives (ex. erreurs base de données),
   - un compteur de transactions réussies / échouées,
   - un histogramme de latence,
   - une jauge de requêtes en cours.
   Les NOMS de métriques peuvent différer.

2. **Mapper les noms de métriques.** Les requêtes PromQL sont dans le
   dictionnaire `QUERIES`, dupliqué dans `collector/collect.py`,
   `ai/rag_analyze.py` et `api/dashboard_server.py`. Le remplacer par les noms
   réellement exposés, idéalement dans un fichier de config partagé unique.

3. **Configurer Prometheus** (`prometheus/prometheus.yml`) pour scraper la vraie
   API (bon host:port de son `/metrics`).

4. **Re-calibrer les seuils de détection** (`detect_rule`, ex. `req_per_sec > 80`
   pour un DDoS) :
   - mesurer le trafic normal réel pendant 30-60 min,
   - régler les seuils au-dessus de ce normal,
   - idéalement remplacer les règles par un modèle ML entraîné sur un CSV
     collecté sur le vrai système (sujet, section 3.3 : ML obligatoire).

5. **Reconstruire l'index RAG** avec les données réelles :
   `python ai/build_index.py --csv <vrai_dataset.csv> --knowledge ai/attack_knowledge.md`

6. **Garder le RAG en rôle d'assistant uniquement.** Le RAG explique, il ne
   déclenche pas la remédiation (exigence du sujet). La détection (règles/ML)
   reste la source de décision pour la remédiation.

## État du mapping avec `services/api/main.py`

La vraie API expose déjà la plupart des noms attendus (via
`prometheus_fastapi_instrumentator` + compteurs maison), avec ces écarts :

- `transactions_total{status}` : labels `success` / `failed`, alors que
  `QUERIES` filtre sur `OK` / `ERROR` → `tx_ok_per_sec` / `tx_err_per_sec` à 0.
- `login_success_total` n'existe pas → `login_ok_per_sec` toujours à 0.
- `http_requests_total` (Instrumentator) : `status` groupé en `2xx`/`4xx`/`5xx`
  (les regex `5..` / `4..` fonctionnent), label `handler` au lieu d'`endpoint`.

## Règles de travail

- Ne jamais committer de secrets en clair (exigence du sujet).
- Fichiers lourds / locaux hors Git (`.gitignore` : `faiss_index/`,
  `dataset*.csv`, `hey.exe`, `__pycache__/`).
- Toutes les attaques restent sur le réseau d'équipe fermé, jamais sur le campus.
- Tout utiliser `127.0.0.1` et non `localhost` (souci IPv6/Docker sous Windows).
