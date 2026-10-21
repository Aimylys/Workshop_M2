"""
COLLECTEUR DE KPI — Project Resilience-Alpha.

Interroge Prometheus toutes les N secondes, calcule les KPI du site + de la
machine, et écrit une ligne par échantillon dans un CSV. Chaque ligne porte
un LABEL = le type d'attaque en cours (ou 'normal').

Le label se pilote SANS arrêter le collecteur, via un petit fichier texte
(label.txt). Ton équipe cyber écrit dedans le nom de l'attaque juste avant
de la lancer, et remet 'normal' après. Exemple :
    echo "ddos"        > label.txt   # avant de lancer le flood
    echo "normal"      > label.txt   # après l'attaque

Usage:
    python collect.py --prom http://localhost:9090 --out dataset.csv --interval 5
"""
import argparse
import csv
import os
import time
import requests

# ------- Requêtes PromQL : chaque entrée devient une COLONNE du dataset -------
# rate(...[30s]) = variation par seconde sur une fenêtre glissante de 30 s.
QUERIES = {
    # Débit et erreurs de l'API
    "req_per_sec":        'sum(rate(http_requests_total[30s]))',
    "err_5xx_per_sec":    'sum(rate(http_requests_total{status=~"5.."}[30s]))',
    "err_4xx_per_sec":    'sum(rate(http_requests_total{status=~"4.."}[30s]))',
    "login_fail_per_sec": 'sum(rate(login_failed_total[30s]))',
    "login_ok_per_sec":   'sum(rate(login_success_total[30s]))',
    "sql_errors_per_sec": 'sum(rate(sql_errors_total[30s]))',
    "tx_ok_per_sec":      'sum(rate(transactions_total{status="OK"}[30s]))',
    "tx_err_per_sec":     'sum(rate(transactions_total{status="ERROR"}[30s]))',
    "inprogress":         'sum(http_inprogress_requests)',
    # Latence (95e percentile) en secondes
    "latency_p95":        'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[30s])) by (le))',
    # Ressources machine via cAdvisor (conteneur api)
    "api_cpu_per_sec":    'sum(rate(container_cpu_usage_seconds_total{name=~".*api.*"}[30s]))',
    "api_mem_bytes":      'sum(container_memory_usage_bytes{name=~".*api.*"})',
    "api_net_rx_per_sec": 'sum(rate(container_network_receive_bytes_total{name=~".*api.*"}[30s]))',
    "api_net_tx_per_sec": 'sum(rate(container_network_transmit_bytes_total{name=~".*api.*"}[30s]))',
}


def read_label(path):
    """Lit le type d'attaque courant. 'normal' si le fichier n'existe pas."""
    try:
        with open(path) as f:
            v = f.read().strip()
            return v if v else "normal"
    except FileNotFoundError:
        return "normal"


def query_one(prom_url, promql):
    """Exécute une requête PromQL instantanée et renvoie un float (0.0 si vide)."""
    try:
        r = requests.get(f"{prom_url}/api/v1/query",
                         params={"query": promql}, timeout=4)
        result = r.json().get("data", {}).get("result", [])
        if result:
            val = result[0]["value"][1]
            return 0.0 if val in ("NaN", "+Inf", "-Inf") else float(val)
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prom", default="http://localhost:9090")
    p.add_argument("--out", default="dataset.csv")
    p.add_argument("--label-file", default="label.txt")
    p.add_argument("--interval", type=int, default=5)
    args = p.parse_args()

    cols = ["timestamp"] + list(QUERIES.keys()) + ["label"]
    new_file = not os.path.exists(args.out)

    with open(args.out, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(cols)

        print(f"Collecte -> {args.out} (toutes les {args.interval}s). Ctrl+C pour arrêter.")
        print(f"Label piloté par : {args.label_file}")
        try:
            while True:
                row = [int(time.time())]
                for promql in QUERIES.values():
                    row.append(round(query_one(args.prom, promql), 4))
                label = read_label(args.label_file)
                row.append(label)
                writer.writerow(row)
                f.flush()
                print(f"  {time.strftime('%H:%M:%S')}  label={label:10s}  "
                      f"req/s={row[1]}  err5xx/s={row[2]}  p95={row[10]}s")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nCollecte arrêtée.")


if __name__ == "__main__":
    main()
