"""
rag_analyze.py — Assistant d'analyse d'incident RAG (LangChain + FAISS + Ollama).
Project Resilience-Alpha.

Boucle, à chaque intervalle :
  1. récupère les KPI en direct depuis Prometheus,
  2. formule une requête, cherche les connaissances pertinentes dans FAISS,
  3. demande à Ollama un verdict JSON (type d'attaque, signification, remédiation),
     fondé UNIQUEMENT sur le contexte récupéré,
  4. affiche le résultat et les sources utilisées.

C'est l'assistant d'analyse (volet RAG du sujet). Il EXPLIQUE l'incident à
l'opérateur ; il n'exécute aucune action corrective sur le système.

Prérequis :
    python build_index.py ...   (pour créer faiss_index/)
    ollama pull llama3.2:3b
    ollama pull nomic-embed-text
    pip install -r requirements.txt

Usage :
    python rag_analyze.py --prom http://localhost:9090 --index faiss_index --interval 15
    python rag_analyze.py --once      # une seule analyse puis sortie
"""
import argparse
import json
import time

import requests
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings

# ---- KPI à relever (identiques au collecteur) ----
QUERIES = {
    "req_per_sec":        'sum(rate(http_requests_total[30s]))',
    "err_5xx_per_sec":    'sum(rate(http_requests_total{status=~"5.."}[30s]))',
    "err_4xx_per_sec":    'sum(rate(http_requests_total{status=~"4.."}[30s]))',
    "login_fail_per_sec": 'sum(rate(login_failed_total[30s]))',
    "login_ok_per_sec":   'sum(rate(login_success_total[30s]))',
    "sql_errors_per_sec": 'sum(rate(sql_errors_total[30s]))',
    "tx_ok_per_sec":      'sum(rate(transactions_total{status="OK"}[30s]))',
    "tx_err_per_sec":     'sum(rate(transactions_total{status="ERROR"}[30s]))',
    "inprogress":         'sum(http_inprogress_requests)',
    "latency_p95":        'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[30s])) by (le))',
    "api_cpu_per_sec":    'sum(rate(container_cpu_usage_seconds_total{name=~".*api.*"}[30s]))',
    "api_net_rx_per_sec": 'sum(rate(container_network_receive_bytes_total{name=~".*api.*"}[30s]))',
}


def query_prom(prom_url, promql):
    try:
        r = requests.get(f"{prom_url}/api/v1/query",
                         params={"query": promql}, timeout=4)
        result = r.json().get("data", {}).get("result", [])
        if result:
            val = result[0]["value"][1]
            return 0.0 if val in ("NaN", "+Inf", "-Inf") else round(float(val), 3)
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return 0.0


def get_kpis(prom_url):
    return {name: query_prom(prom_url, q) for name, q in QUERIES.items()}


def kpis_to_query(kpis):
    """Construit une requête de recherche textuelle à partir des KPI anormaux."""
    parts = [f"{k}={v}" for k, v in kpis.items()]
    return ("Quel type d'incident correspond à ces indicateurs de la plateforme "
            "de paiement : " + ", ".join(parts))


def ask_ollama(model, prompt, ollama_url):
    try:
        r = requests.post(f"{ollama_url}/api/generate",
                          json={"model": model, "prompt": prompt, "stream": False,
                                "format": "json", "options": {"temperature": 0.1}},
                          timeout=120)
        return r.json().get("response", "").strip()
    except requests.RequestException as e:
        return json.dumps({"type": "erreur", "signification": f"Ollama injoignable: {e}"})


PROMPT_TEMPLATE = """Tu es un analyste SOC pour une plateforme de paiement.
Utilise UNIQUEMENT le contexte ci-dessous (fiches d'attaque et profils observés)
pour analyser les indicateurs. N'invente rien hors du contexte.

=== CONTEXTE RÉCUPÉRÉ ===
{context}
=== FIN DU CONTEXTE ===

Indicateurs mesurés à l'instant présent :
{kpis}

Réponds en JSON strict, sans texte autour :
{{
  "type": "<normal|ddos|brute_force|sql_injection|service_down|port_scan>",
  "confiance": "<faible|moyenne|élevée>",
  "signification": "<une phrase expliquant ce type d'attaque>",
  "kpi_declencheurs": ["<KPI anormaux qui justifient la conclusion>"],
  "remediation": "<action corrective recommandée d'après le contexte>"
}}"""


def analyze_once(store, kpis, model, ollama_url, k=4):
    query = kpis_to_query(kpis)
    hits = store.similarity_search(query, k=k)
    context = "\n\n".join(h.page_content for h in hits)
    sources = [h.metadata.get("label") or h.metadata.get("source") for h in hits]
    kpi_text = "\n".join(f"- {k2} = {v}" for k2, v in kpis.items())
    prompt = PROMPT_TEMPLATE.format(context=context, kpis=kpi_text)
    raw = ask_ollama(model, prompt, ollama_url)
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        verdict = {"type": "indéterminé", "signification": raw[:200]}
    return verdict, sources


def print_verdict(verdict, sources, kpis):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] type = {str(verdict.get('type','?')).upper():14s} "
          f"confiance = {verdict.get('confiance','?')}")
    print(f"         {verdict.get('signification','')}")
    if verdict.get("kpi_declencheurs"):
        print(f"         KPI déclencheurs : {', '.join(verdict['kpi_declencheurs'])}")
    if verdict.get("remediation"):
        print(f"         Remédiation : {verdict['remediation']}")
    print(f"         Sources RAG : {', '.join(str(s) for s in sources)}")
    print(f"         (bruts : req/s={kpis['req_per_sec']} p95={kpis['latency_p95']}s "
          f"login_fail/s={kpis['login_fail_per_sec']} sql_err/s={kpis['sql_errors_per_sec']} "
          f"err5xx/s={kpis['err_5xx_per_sec']})\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prom", default="http://localhost:9090")
    p.add_argument("--index", default="faiss_index")
    p.add_argument("--model", default="llama3.2:3b")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--ollama", default="http://localhost:11434")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--once", action="store_true", help="une seule analyse puis sortie")
    args = p.parse_args()

    print(f"Chargement de l'index FAISS « {args.index} »...")
    embeddings = OllamaEmbeddings(model=args.embed_model, base_url=args.ollama)
    store = FAISS.load_local(args.index, embeddings,
                             allow_dangerous_deserialization=True)
    print(f"Assistant RAG prêt (modèle {args.model}). Ctrl+C pour arrêter.\n")

    try:
        while True:
            kpis = get_kpis(args.prom)
            verdict, sources = analyze_once(store, kpis, args.model, args.ollama)
            print_verdict(verdict, sources, kpis)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nAssistant arrêté.")


if __name__ == "__main__":
    main()
