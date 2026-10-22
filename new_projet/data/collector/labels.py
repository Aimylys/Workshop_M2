"""Étiquette de l'état en cours (normal / type d'attaque), pilotée par un fichier texte.

L'équipe cyber change l'étiquette juste avant de lancer une attaque, puis la remet à
« normal » quand elle est terminée :

    python data/collector/labels.py ddos
    python data/collector/labels.py normal
    python data/collector/labels.py            # affiche l'étiquette courante

Chaque changement est horodaté dans label_history.csv (traçabilité du jeu de données).
Écrire le fichier à la main fonctionne aussi : la lecture accepte UTF-8 et UTF-16
(ce que produit « echo ddos > label.txt » sous PowerShell).
"""
import csv
import os
import sys
import time
from pathlib import Path

try:
    from .kpis import LABELS
except ImportError:          # exécuté comme script
    from kpis import LABELS

HERE = Path(__file__).resolve().parent
LABEL_FILE = HERE / "label.txt"
HISTORY_FILE = HERE / "label_history.csv"


def read_label(path: Path = LABEL_FILE) -> str:
    """Étiquette courante ; « normal » si le fichier est absent ou vide."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "normal"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    return text.strip().lower() or "normal"


def write_label(label: str, path: Path = LABEL_FILE, history: Path = HISTORY_FILE) -> None:
    label = label.strip().lower()
    if label not in LABELS:
        raise ValueError(f"étiquette inconnue « {label} » ; valeurs possibles : {', '.join(LABELS)}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(label + "\n", encoding="utf-8")
    os.replace(tmp, path)       # remplacement atomique : le collecteur ne lit jamais un fichier à moitié écrit
    new = not history.exists()
    with history.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["timestamp", "iso_time", "label"])
        writer.writerow([int(time.time()), time.strftime("%Y-%m-%dT%H:%M:%S%z"), label])


def main() -> None:
    if len(sys.argv) == 1:
        print(read_label())
        return
    try:
        write_label(sys.argv[1])
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"étiquette -> {read_label()}")


if __name__ == "__main__":
    main()
