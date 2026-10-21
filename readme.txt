# IDS Attack Launcher

Interface graphique (CustomTkinter) pour piloter des attaques labellisées
dans un projet de collecte IDS.

## ⚠️ Avertissement légal

Cet outil exécute de vraies attaques (brute force, port scan, SQL injection,
DDoS). **Utilisation strictement réservée à un lab isolé ou à des cibles
explicitement autorisées.** Toute utilisation contre un système tiers sans
autorisation est illégale.

## Prérequis

- Python 3.10+
- Sur Windows :
  - PowerShell (natif)
  - `nmap` dans le `PATH` (pour Port Scan)
  - `sqlmap` dans le `PATH` (pour SQL Injection)
  - `hey.exe` dans `C:\Users\skibi\Downloads\PROJET\` ou dans le `PATH` (DDoS)

## Installation

```powershell
cd C:\Users\skibi\Downloads\PROJET
pip install -r requirements.txt