"""Assistant RAG : EXPLIQUE un incident à l'opérateur, en français, à partir de la base de
connaissance indexée. Il n'agit JAMAIS sur le système — c'est la détection qui décide, et la
remédiation qui agit. Le RAG se contente de retrouver les fiches pertinentes et de les résumer.

Modèle local llama3.2:3b (≤ 8 Md de paramètres, conforme au sujet) via Ollama.

    python -m assistant.rag --label ddos         # explication d'un état donné
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "assistant" / "faiss_index"
OLLAMA_URL = "http://127.0.0.1:11434"

PROMPT = """Tu es un assistant SOC pour une plateforme de paiement. Un détecteur automatique a
identifié l'état « {label} ». Voici les indicateurs anormaux relevés :
{triggers}

En t'appuyant UNIQUEMENT sur le contexte ci-dessous, explique à l'opérateur, en 2 à 4 phrases et
en français : ce que signifie cet état, son risque pour la plateforme de paiement, et la
remédiation recommandée. N'invente rien qui ne soit pas dans le contexte. Ne proposes pas
d'exécuter toi-même une action : tu expliques seulement.

=== CONTEXTE ===
{context}
=== FIN DU CONTEXTE ===

Explication :"""


class Assistant:
    """Charge l'index FAISS une fois ; chaque explication est une recherche + un appel LLM."""

    def __init__(self, index_dir=INDEX_DIR, ollama_url=OLLAMA_URL,
                 model="llama3.2:3b", embed_model="nomic-embed-text"):
        from langchain_community.vectorstores import FAISS
        from langchain_ollama import OllamaEmbeddings, OllamaLLM

        if not Path(index_dir).exists():
            raise FileNotFoundError(
                f"index RAG absent ({index_dir}). Lancer d'abord : python -m assistant.build_index")
        embeddings = OllamaEmbeddings(model=embed_model, base_url=ollama_url)
        self.store = FAISS.load_local(str(index_dir), embeddings, allow_dangerous_deserialization=True)
        self.llm = OllamaLLM(model=model, base_url=ollama_url, temperature=0.1)

    def explain(self, label: str, triggers: list | None = None, k: int = 4) -> dict:
        """Renvoie {"text": explication, "sources": [...]}. Jamais d'exception vers l'appelant :
        si Ollama est injoignable, renvoie un message clair plutôt que de planter le dashboard."""
        trigger_text = "aucun indicateur déclencheur précis."
        if triggers:
            trigger_text = "\n".join(f"- {k2} = {v} ({z:+.0f} écarts-types vs normal)"
                                     for k2, v, z in triggers)
        query = f"état {label} signification risque remédiation plateforme de paiement"
        try:
            hits = self.store.similarity_search(query, k=k)
        except Exception as exc:  # noqa: BLE001
            return {"text": f"(recherche documentaire indisponible : {exc})", "sources": []}
        context = "\n\n".join(h.page_content for h in hits)
        sources = sorted({h.metadata.get("source", "?") for h in hits})
        prompt = PROMPT.format(label=label, triggers=trigger_text, context=context)
        try:
            text = self.llm.invoke(prompt).strip()
        except Exception as exc:  # noqa: BLE001
            text = f"(modèle d'explication indisponible : {exc}. Contexte documentaire : {sources})"
        return {"text": text, "sources": sources}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--label", required=True)
    p.add_argument("--index", default=str(INDEX_DIR))
    p.add_argument("--ollama", default=OLLAMA_URL)
    p.add_argument("--model", default="llama3.2:3b")
    args = p.parse_args()
    assistant = Assistant(args.index, args.ollama, args.model)
    result = assistant.explain(args.label)
    print(result["text"])
    print(f"\n[sources : {', '.join(result['sources'])}]")


if __name__ == "__main__":
    main()
