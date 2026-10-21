"""
build_index.py — Construction de l'index vectoriel FAISS (RAG).
Project Resilience-Alpha.

Indexe deux sources de connaissance :
  1. attack_knowledge.md  : les fiches descriptives de chaque attaque.
  2. dataset.csv          : un RÉSUMÉ STATISTIQUE par label (moyennes des KPI),
                            transformé en texte. On n'indexe JAMAIS les lignes
                            brutes de chiffres : FAISS compare du sens, pas des
                            nombres. Les profils moyens, eux, sont du texte utile.

Les embeddings sont calculés en local par Ollama (nomic-embed-text), donc tout
reste hors ligne. L'index est sauvegardé sur disque pour être rechargé par le
script d'analyse sans tout recalculer.

Prérequis :
    ollama pull nomic-embed-text
    pip install -r requirements.txt

Usage :
    python build_index.py --csv ../collector/dataset.csv --knowledge attack_knowledge.md --out faiss_index
"""
import argparse
import os

import pandas as pd
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


def load_knowledge_docs(path):
    """Découpe le markdown des fiches d'attaque en morceaux indexables."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700, chunk_overlap=100,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )
    chunks = splitter.split_text(text)
    return [Document(page_content=c, metadata={"source": "attack_knowledge"})
            for c in chunks]


def summarize_csv(path):
    """Transforme le CSV en un profil texte par label (moyenne + min/max des KPI)."""
    if not os.path.exists(path):
        print(f"  [info] {path} introuvable : résumé CSV ignoré.")
        return []

    df = pd.read_csv(path)
    if "label" not in df.columns:
        print("  [info] pas de colonne 'label' : résumé CSV ignoré.")
        return []

    # colonnes numériques à résumer (tout sauf timestamp et label)
    num_cols = [c for c in df.columns
                if c not in ("timestamp", "label")
                and pd.api.types.is_numeric_dtype(df[c])]

    docs = []
    for label, group in df.groupby("label"):
        lines = [f"Profil statistique observé pour l'état « {label} » "
                 f"({len(group)} mesures) :"]
        for col in num_cols:
            lines.append(
                f"- {col} : moyenne {group[col].mean():.2f}, "
                f"min {group[col].min():.2f}, max {group[col].max():.2f}")
        content = "\n".join(lines)
        docs.append(Document(page_content=content,
                             metadata={"source": "dataset_profile", "label": label}))
        print(f"  [csv] profil indexé pour '{label}' ({len(group)} lignes)")
    return docs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="../collector/dataset.csv")
    p.add_argument("--knowledge", default="attack_knowledge.md")
    p.add_argument("--out", default="faiss_index")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--ollama", default="http://localhost:11434")
    args = p.parse_args()

    print("Construction de l'index RAG...")
    docs = load_knowledge_docs(args.knowledge)
    print(f"  [md]  {len(docs)} morceaux issus des fiches d'attaque")
    docs += summarize_csv(args.csv)

    print(f"Calcul des embeddings via Ollama ({args.embed_model})...")
    embeddings = OllamaEmbeddings(model=args.embed_model, base_url=args.ollama)
    store = FAISS.from_documents(docs, embeddings)
    store.save_local(args.out)
    print(f"Index FAISS sauvegardé dans « {args.out} » ({len(docs)} documents).")


if __name__ == "__main__":
    main()
