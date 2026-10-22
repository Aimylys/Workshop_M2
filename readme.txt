# IDS Attack Launcher

Interface graphique (CustomTkinter) pour piloter des attaques labellisées dans un projet de collecte IDS.

## Prérequis

- **Python 3.10+** : [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **Outils d'attaque** (à avoir dans le `PATH` ou dans le dossier du projet) :
  - **Nmap** (Port Scan) : [https://nmap.org/download.html](https://nmap.org/download.html)
  - **SQLMap** (SQL Injection) : [https://github.com/sqlmapproject/sqlmap](https://github.com/sqlmapproject/sqlmap)
  - **hey.exe** (DDoS) : [https://github.com/rakyll/hey](https://github.com/rakyll/hey) — *déjà présent dans le dossier du projet*

## Installation

Ouvre un terminal PowerShell dans le dossier du projet et installe les dépendances Python :

```powershell
pip install -r requirements.txt
