"""Construit l'index vectoriel FAISS de la base de connaissance (RAG, local via Ollama).

Indexe assistant/knowledge/*.md : les fiches d'incident (attacks.md) et les profils de KPI
générés à partir du jeu de données réel (profiles.md, produit par detection.index). Les
embeddings sont calculés en local par Ollama (nomic-embed-text) : rien ne sort de la machine.

    python -m assistant.build_index
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "assistant" / "knowledge"
INDEX_DIR = ROOT / "assistant" / "faiss_index"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"


def build(knowledge_dir: Path, index_dir: Path, ollama_url: str, embed_model: str) -> None:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_ollama import OllamaEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    files = sorted(knowledge_dir.glob("*.md"))
    if not files:
        sys.exit(f"aucun fichier de connaissance dans {knowledge_dir}")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700, chunk_overlap=120, separators=["\n## ", "\n### ", "\n\n", "\n", " "])
    docs: list[Document] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for chunk in splitter.split_text(text):
            docs.append(Document(page_content=chunk, metadata={"source": path.name}))
    print(f"{len(docs)} fragments issus de {', '.join(p.name for p in files)}")

    embeddings = OllamaEmbeddings(model=embed_model, base_url=ollama_url)
    try:
        store = FAISS.from_documents(docs, embeddings)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"échec du calcul des embeddings via Ollama ({ollama_url}) : {exc}\n"
                 f"Vérifier qu'Ollama tourne et que le modèle « {embed_model} » est présent "
                 f"(ollama pull {embed_model}).")
    store.save_local(str(index_dir))
    print(f"index FAISS enregistré -> {index_dir}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--knowledge", default=str(KNOWLEDGE_DIR))
    p.add_argument("--index", default=str(INDEX_DIR))
    p.add_argument("--ollama", default=OLLAMA_URL)
    p.add_argument("--embed-model", default=EMBED_MODEL)
    args = p.parse_args()
    build(Path(args.knowledge), Path(args.index), args.ollama, args.embed_model)


if __name__ == "__main__":
    main()
