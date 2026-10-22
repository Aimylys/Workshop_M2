# Détection (phase 4) & assistant RAG (phase 5)

```
dataset.csv ──► detection.index build ──► detector.joblib   (le « modèle » : kNN sur KPI)
    │                   └─► profiles.json + knowledge/profiles.md
    │
Prometheus (kpi:*) ──► detection.detect ──► VERDICT ──► (phase 7 : remédiation)
                                               │
                                               └─► assistant.rag ──► explication en français
```

## Principe

- **La détection DÉCIDE.** Classement par **k plus proches voisins** (k=15) sur les KPI
  standardisés : l'état courant reçoit l'étiquette majoritaire parmi ses 15 voisins les plus
  proches dans le jeu de données étiqueté. C'est de l'apprentissage par l'exemple (pas de réseau
  entraîné « from scratch ») : l'index **est** le modèle. Un état très éloigné de tout ce qui a
  été observé est marqué `inconnu` plutôt que classé de force.
- **L'assistant RAG EXPLIQUE, il n'agit jamais.** Il retrouve les fiches pertinentes
  (`assistant/knowledge/`) et les résume avec un LLM local (`llama3.2:3b` via Ollama). Il ne
  déclenche aucune action : exigence du sujet (3.3).

## Chaîne complète

```powershell
# 1. collecter un jeu de données étiqueté (voir data/README.md ou redteam/RUNBOOK.md)
python -m labtest.collect_session --repeat 3

# 2. construire le modèle de détection + les profils + la connaissance RAG
python -m detection.index build

# 3. évaluer honnêtement (entraînement/test séparés PAR ÉPISODE, sans fuite)
python -m detection.index evaluate

# 4. construire l'index RAG (embeddings locaux Ollama)
python -m assistant.build_index

# 5. détecter en direct / expliquer
python -m detection.detect --interval 5
python -m assistant.rag --label ddos
```

## Signatures apprises (jeu de données réel)

| État | KPI distinctif |
|---|---|
| `ddos` | `edge_conn_per_sec` ↑↑ (~65/s) et `req_per_sec` ↓ (clients évincés) |
| `brute_force` | `login_fail_per_sec` ↑ (~4/s) et `latency_p95_login_seconds` ↑ |
| `sql_injection` | `waf_blocked_per_sec` ↑ (~18/s, requêtes arrêtées au WAF) |
| `port_scan` | `waf_404_per_sec` ↑ (~45/s, chemins inexistants) |
| `service_down` | `tx_ok_per_sec` → 0, `db_errors_per_sec` ↑ |

## Dépendances

`detection/requirements.txt` (numpy, pandas, scikit-learn) et `assistant/requirements.txt`
(faiss-cpu, langchain, langchain-ollama) cohabitent dans un même venv **avec numpy 2.x**
(un avertissement de résolution pip subsiste mais les deux piles s'importent correctement).

## Limites connues

- Le signal `api_up` reflète la joignabilité de l'endpoint `/metrics` (port 9000), pas la santé
  applicative : pendant `service_down`, il reste à 1 (l'API répond mais renvoie 503). La panne se
  reconnaît via `tx_ok_per_sec`, `db_errors_per_sec` et la latence, pas via `api_up`.
- Le modèle ne connaît que les états collectés. Un nouveau type d'attaque sera classé `inconnu`
  ou rapproché de l'état le plus ressemblant : à enrichir par de nouvelles collectes.
