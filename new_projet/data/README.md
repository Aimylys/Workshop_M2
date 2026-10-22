# Collecte du jeu de données (phase 3)

Le modèle de détection (phase 4) apprend à reconnaître chaque état à partir des KPI de la
plateforme. Ce dossier produit le jeu de données étiqueté qui sert à l'entraîner.

```
trafic normal ──► plateforme ──► Prometheus (kpi:*) ──► collect.py ──► dataset.csv
                     ▲                                       ▲
     attaques lancées À LA MAIN          label.txt ──────────┘  (labels.py <état>)
     depuis le PC attaquant
```

## Outils

| Fichier | Rôle |
|---|---|
| `traffic/normal_traffic.py` | Clients fictifs légitimes, à laisser tourner **pendant toute la collecte** |
| `collector/collect.py` | Une ligne toutes les 5 s : horodatage, tous les KPI, étiquette, épisode |
| `collector/labels.py` | Change l'étiquette courante (avec historique horodaté) |
| `collector/kpis.py` | Lecture des KPI (liste lue dans `observability/prometheus/rules/kpi.yml`) |

Étiquettes possibles : `normal`, `ddos`, `brute_force`, `sql_injection`, `service_down`, `port_scan`.

## Protocole de collecte

Trois terminaux sur le PC hôte :

```powershell
# 1. trafic normal (en continu)
python data/traffic/normal_traffic.py
# 2. collecteur (en continu)
python data/collector/collect.py
# 3. pilotage de l'étiquette, au rythme de l'équipe cyber
python data/collector/labels.py normal
```

Puis, pour chaque scénario du runbook Red Team (`redteam/RUNBOOK.md`, phase 4) :

1. au moins **10 minutes de `normal`** au début (référence) ;
2. `python data/collector/labels.py <état>` **juste avant** que l'équipe cyber lance l'outil
   depuis le PC attaquant ;
3. attaque pendant **2 à 3 minutes** ;
4. `python data/collector/labels.py normal` **dès l'arrêt** de l'outil ;
5. **2 minutes de retour au calme** avant le scénario suivant.

Répéter chaque scénario **au moins 3 fois** (3 épisodes) : la phase 4 entraîne le modèle sur
certains épisodes et l'évalue sur d'autres, jamais vus. Varier l'intensité d'un épisode à
l'autre rend le modèle plus robuste.

Ordre de grandeur : 3 × 5 scénarios × 5 min + référence ≈ 1 h 30 de collecte.

## Qualité des données (garanties du collecteur)

| Situation | Comportement |
|---|---|
| Prometheus injoignable | aucune ligne écrite (jamais de zéros inventés) |
| Prometheus vient de démarrer (fenêtre de 30 s incomplète) | aucune ligne écrite |
| KPI pas encore recalculés depuis la ligne précédente | ligne ignorée (pas de doublon) |
| KPI sans valeur (ex. latence sans aucune requête) | cellule vide, jamais 0 |
| Étiquette inconnue dans `label.txt` | ligne ignorée, avertissement |
| `dataset.csv` existant avec d'autres colonnes | refus explicite (choisir un autre `--out`) |

Les lignes de transition (les quelques secondes où une attaque démarre ou s'arrête) sont
normales : le modèle de la phase 4 les traite à part.

## Rattrapage depuis l'historique

Si le collecteur a été arrêté, Prometheus garde 48 h d'historique. Une période dont on connaît
l'état peut être reconstruite :

```powershell
python data/collector/collect.py --out data/collector/dataset.csv export --label normal --minutes 30
```

## Fichiers produits (non versionnés)

`collector/dataset*.csv`, `collector/label.txt`, `collector/label_history.csv`.
