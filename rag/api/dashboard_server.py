"""
dashboard_server.py — Interface web temps réel de détection d'attaques.
Project Resilience-Alpha. VERSION AVEC RAG.

- Les RÈGLES décident le type d'attaque (instantané, fiable).
- Le RAG (FAISS + Ollama) génère l'EXPLICATION en langage naturel + les sources.
- L'explication RAG est mise en CACHE par type : le LLM n'est appelé que lorsque
  l'état change, pour que le dashboard reste fluide (le LLM met plusieurs secondes).

Prérequis :
    pip install fastapi uvicorn requests langchain langchain-community langchain-ollama faiss-cpu
    ollama pull llama3.2:3b
    ollama pull nomic-embed-text
    python build_index.py ...   (pour créer faiss_index/)

Lancement (depuis le dossier ai) :
    python dashboard_server.py --prom http://127.0.0.1:9090 --index faiss_index --port 8050
Puis ouvrir http://127.0.0.1:8050
"""
import argparse
import os
import threading

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings

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
}

# Config (remplie dans __main__)
CFG = {"prom": "http://127.0.0.1:9090", "index": "faiss_index",
       "model": "llama3.2:3b", "embed": "nomic-embed-text",
       "ollama": "http://127.0.0.1:11434"}

app = FastAPI()
STORE = None                       # index FAISS chargé au démarrage
EXPL_CACHE = {}                    # {type: {"text":..., "sources":[...]}}
EXPL_LOCK = threading.Lock()


def query_prom(promql):
    try:
        r = requests.get(f"{CFG['prom']}/api/v1/query", params={"query": promql}, timeout=4)
        result = r.json().get("data", {}).get("result", [])
        if result:
            val = result[0]["value"][1]
            return 0.0 if val in ("NaN", "+Inf", "-Inf") else round(float(val), 3)
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return 0.0


def detect_rule(k):
    req, fail, sqlerr = k["req_per_sec"], k["login_fail_per_sec"], k["sql_errors_per_sec"]
    e5, inprog = k["err_5xx_per_sec"], k["inprogress"]
    txok, oklog = k["tx_ok_per_sec"], k["login_ok_per_sec"]
    if req < 1 and txok < 0.2 and oklog < 0.2:
        return "inactif", "Aucun trafic mesuré (API inactive ou Prometheus ne reçoit rien)"
    if req > 80 or inprog > 100:
        return "ddos", f"Volume de requêtes anormal (req/s={req}, inprogress={inprog})"
    if fail > 3:
        return "brute_force", f"Nombreux échecs de connexion (login_fail/s={fail})"
    if sqlerr > 4:
        return "sql_injection", f"Erreurs SQL anormales (sql_errors/s={sqlerr})"
    if req > 1 and txok < 0.3 and oklog < 0.3 and e5 > 1:
        return "service_down", f"Opérations réussies à ~0 avec erreurs serveur (err5xx/s={e5})"
    return "normal", "Indicateurs dans les plages habituelles"


def ask_ollama(prompt):
    try:
        r = requests.post(f"{CFG['ollama']}/api/generate",
                          json={"model": CFG["model"], "prompt": prompt, "stream": False,
                                "options": {"temperature": 0.2}}, timeout=120)
        return r.json().get("response", "").strip()
    except requests.RequestException as e:
        return f"(analyse RAG indisponible : {e})"


def rag_explain(attack_type):
    """Récupère dans FAISS les fiches pertinentes et fait expliquer par Ollama.
    Résultat mis en cache par type."""
    if STORE is None:
        return {"text": "(index RAG non chargé)", "sources": []}
    hits = STORE.similarity_search(
        f"attaque {attack_type} signification remédiation", k=3)
    context = "\n\n".join(h.page_content for h in hits)
    sources = [h.metadata.get("label") or h.metadata.get("source") for h in hits]
    prompt = (f"Tu es un analyste SOC. Le détecteur a identifié l'état « {attack_type} » "
              f"sur une plateforme de paiement.\n\nContexte documentaire :\n{context}\n\n"
              f"Explique en 2 phrases max, en français, ce que signifie cet état et la "
              f"remédiation recommandée. Ne remets pas en cause le type identifié.")
    return {"text": ask_ollama(prompt), "sources": sources}


def get_explanation(attack_type):
    """Explication RAG, calculée une seule fois par type puis mise en cache."""
    if attack_type in ("normal", "inactif"):
        return None
    with EXPL_LOCK:
        if attack_type in EXPL_CACHE:
            return EXPL_CACHE[attack_type]
    expl = rag_explain(attack_type)          # appel LLM (hors du lock)
    with EXPL_LOCK:
        EXPL_CACHE[attack_type] = expl
    return expl


@app.get("/api/status")
def status():
    kpis = {name: query_prom(q) for name, q in QUERIES.items()}
    attack_type, reason = detect_rule(kpis)
    expl = get_explanation(attack_type)
    return JSONResponse({
        "type": attack_type, "reason": reason, "kpis": kpis,
        "rag": expl,  # {"text":..., "sources":[...]} ou null
    })


@app.get("/")
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "dashboard.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument("--prom", default="http://127.0.0.1:9090")
    p.add_argument("--index", default="faiss_index")
    p.add_argument("--model", default="llama3.2:3b")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8050)
    args = p.parse_args()
    CFG.update(prom=args.prom, index=args.index, model=args.model,
               embed=args.embed_model, ollama=args.ollama)

    print(f"Chargement de l'index FAISS « {args.index} »...")
    emb = OllamaEmbeddings(model=args.embed_model, base_url=args.ollama)
    STORE = FAISS.load_local(args.index, emb, allow_dangerous_deserialization=True)
    print(f"Dashboard RAG sur http://{args.host}:{args.port}  (Prometheus: {args.prom})")
    uvicorn.run(app, host=args.host, port=args.port)
