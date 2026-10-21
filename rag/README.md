# Project Resilience-Alpha — Site victime + collecte de KPI

Ce dépôt contient la **plateforme de paiement fictive** et toute la chaîne de
**collecte des KPI** servant à constituer le dataset pour la détection ML.

> Les scripts offensifs (DDoS, brute force, injection…) ne sont **pas** inclus :
> ils sont produits par l'équipe cybersécurité, sur le PC Attaquant. Ce dépôt
> fournit la cible et la mesure.

## Composants

| Service     | Rôle                                   | Port |
|-------------|----------------------------------------|------|
| api         | API de paiement (FastAPI) + /metrics   | 8000 |
| db          | PostgreSQL (interne, non exposé)        | —    |
| prometheus  | Collecte des métriques                  | 9090 |
| cadvisor    | CPU/RAM/réseau par conteneur            | —    |
| grafana     | Visualisation (admin/admin)             | 3000 |

## 1. Démarrer la plateforme

```bash
docker compose up -d --build
curl http://localhost:8000/health        # doit répondre {"status":"up"}
```

Vérifier les métriques : http://localhost:8000/metrics
Vérifier Prometheus : http://localhost:9090  (Status > Targets, tout en "UP")

## 2. Lancer le trafic normal (à garder actif pendant toute la collecte)

```bash
pip install -r traffic/requirements.txt 2>/dev/null || pip install requests
python traffic/normal_traffic.py --url http://localhost:8000 --rps 15
```

## 3. Lancer la collecte des KPI

Dans un autre terminal :

```bash
pip install -r collector/requirements.txt
cd collector
echo "normal" > label.txt
python collect.py --prom http://localhost:9090 --out dataset.csv --interval 5
```

Le fichier `dataset.csv` se remplit, une ligne toutes les 5 s, avec une colonne
`label`.

## 4. Étiqueter les attaques (fait par l'équipe cyber)

Le collecteur lit en continu le fichier `label.txt`. Pour marquer une attaque,
il suffit de changer ce fichier **avant** et **après** :

```bash
# --- séquence pour UNE attaque ---
echo "normal" > collector/label.txt   # 5 min de normal
#   ... attendre ~5 min ...
echo "ddos"   > collector/label.txt   # PUIS lancer le flood depuis le PC Attaquant
#   ... attendre ~5 min ...
echo "normal" > collector/label.txt   # arrêter l'attaque, retour au normal
```

Répéter pour chaque type : `ddos`, `brute_force`, `sql_injection`, `port_scan`,
`service_down`. À la fin, `dataset.csv` contient tous les types, prêt pour le ML.

## Colonnes du dataset

timestamp, req_per_sec, err_5xx_per_sec, err_4xx_per_sec, login_fail_per_sec,
login_ok_per_sec, sql_errors_per_sec, tx_ok_per_sec, tx_err_per_sec, inprogress,
latency_p95, api_cpu_per_sec, api_mem_bytes, api_net_rx_per_sec,
api_net_tx_per_sec, **label**

## Rappel périmètre

Toutes les actions offensives restent sur le réseau du consortium
(192.168.137.0/24), jamais sur le campus ni Internet. Données 100 % fictives.
