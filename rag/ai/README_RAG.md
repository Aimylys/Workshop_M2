# Assistant RAG d'analyse d'incident — LangChain + FAISS + Ollama

Assistant local qui analyse les KPI en direct et explique l'incident à
l'opérateur, en s'appuyant sur une base de connaissances vectorisée (FAISS).

> Rôle : EXPLIQUER (volet RAG du sujet, section 3.3). N'exécute aucune action
> corrective — la remédiation est un composant séparé.

## Fichiers

| Fichier | Rôle |
|---|---|
| `attack_knowledge.md` | Fiches descriptives des attaques (source de connaissance) |
| `build_index.py` | Construit l'index FAISS (fiches + profils tirés du CSV) |
| `rag_analyze.py` | Analyse les KPI en direct via le RAG |
| `requirements.txt` | Dépendances Python |

## Installation

1. Ollama + modèles (tout reste local, hors ligne) :
```bash
ollama pull llama3.2:3b        # modèle de chat (<= 8B, conforme au sujet)
ollama pull nomic-embed-text   # modèle d'embeddings pour FAISS
```

2. Dépendances Python :
```bash
pip install -r requirements.txt
```

## 1. Construire l'index (une fois, ou après chaque nouvelle collecte)

```bash
python build_index.py --csv ../collector/dataset.csv --knowledge attack_knowledge.md --out faiss_index
```

Ce que fait le script :
- découpe `attack_knowledge.md` en morceaux,
- calcule un **profil statistique par label** depuis `dataset.csv` (moyennes,
  min, max des KPI) et l'indexe comme texte,
- NE met jamais les lignes brutes de chiffres dans FAISS (la recherche
  vectorielle compare du sens, pas des nombres),
- sauvegarde l'index dans `faiss_index/`.

## 2. Analyser en direct

```bash
python rag_analyze.py --prom http://localhost:9090 --index faiss_index --interval 15
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypas .\traffic\run_collection.ps1
Ou une seule analyse :
```bash
python rag_analyze.py --once
```

Sortie type pendant une attaque :
```
[16:22:10] type = DDOS           confiance = élevée
         Attaque par saturation : l'API est inondée de requêtes...
         KPI déclencheurs : req_per_sec, latency_p95
         Remédiation : limiter le débit, bloquer l'IP source
         Sources RAG : ddos, attack_knowledge
         (bruts : req/s=512 p95=14.8s ...)
```

## Pourquoi ce découpage

- Le **CSV** nourrit l'index via des profils résumés : exploitable et honnête.
- Le **RAG** cite ses sources (colonne « Sources RAG »), ce qui rend le verdict
  explicable devant le jury.
- Pour la détection temps réel qui déclenche la reprise, un modèle ML reste le
  bon outil ; ce RAG est l'assistant d'analyse qui l'accompagne.

## Limites connues (à mentionner au jury)

- Un LLM met quelques secondes par analyse : bon pour l'explication, pas pour la
  détection à la milliseconde.
- La qualité des profils dépend de la richesse du `dataset.csv` : plus il couvre
  d'attaques bien étiquetées, meilleure est l'analyse.
