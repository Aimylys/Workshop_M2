# Resilience-Alpha — plateforme de paiement fictive à reprise autonome

Démonstrateur du workshop EPSI **« PROJECT RESILIENCE-ALPHA »** : une plateforme de paiement
**entièrement fictive** qui **détecte une cyberattaque et se rétablit automatiquement**, sans
intervention humaine (*Zero-Touch Recovery*). Réseau fermé, données 100 % fictives.

> Ce README sert à **lancer le projet pas à pas**. Pour comprendre le fonctionnement en détail,
> voir **[DOCUMENTATION_COMPLETE.md](DOCUMENTATION_COMPLETE.md)** (ou le PDF fourni).

## En une minute

Le système tourne en boucle sur cinq temps :

**Mesurer → Détecter → Expliquer → Remédier → Vérifier.**

- **Mesurer** : Prometheus calcule en continu des indicateurs (KPI) à partir des métriques et des journaux.
- **Détecter** : un modèle *k plus proches voisins* compare l'état courant aux situations connues et rend un verdict (normal / type d'attaque / inconnu). **La détection décide.**
- **Expliquer** : un assistant RAG (LLM local) explique l'incident en français. **Il explique seulement.**
- **Remédier** : un moteur exécute une action prédéfinie (bloquer la source, redémarrer, confiner). **La remédiation agit.**
- **Vérifier** : la reprise n'est validée que par une sonde `/health` **et** une transaction de test réussie.

Deux interfaces web : une page pour **lancer** les attaques, une page **SOC** pour **visualiser**
l'état du système, le verdict, l'explication et la remédiation en direct.

---

## Prérequis

- **Docker Desktop** (WSL2) démarré
- **Python 3.12**
- *(optionnel, pour l'explication RAG)* **Ollama** avec les modèles `llama3.2:3b` et `nomic-embed-text`

Toutes les commandes se lancent depuis le dossier `new_projet/`, sous **PowerShell**.

---

## Lancement pas à pas

### 1. Installer l'environnement Python

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt -r detection/requirements.txt -r assistant/requirements.txt
```

### 2. Générer les secrets (mots de passe, clés — non versionnés)

```powershell
.\.venv\Scripts\python deploy/gen_secrets.py
```

### 3. Démarrer la plateforme

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
.\.venv\Scripts\python tests/smoke_test.py          # vérifie que tout répond (via le WAF)
```

### 4. Entraîner le modèle de détection *(première fois, ou si la détection est imprécise)*

La détection a besoin d'un jeu de données étiqueté. On le construit en jouant les attaques puis on
entraîne le modèle :

```powershell
.\.venv\Scripts\python -m labtest.collect_session --repeat 2    # collecte (~30 min, la VM travaille seule)
.\.venv\Scripts\python -m detection.index build                 # entraîne le kNN + profils RAG
.\.venv\Scripts\python -m detection.index evaluate              # (optionnel) précision par type d'attaque
```

> Pendant la collecte, **ne lance pas d'attaque à la main** : l'orchestrateur enchaîne tout seul
> ddos → force brute → injection SQL → scan → panne, avec du trafic normal entre chaque.

### 5. Lancer la console (les deux interfaces)

```powershell
.\.venv\Scripts\python -m console.app
```

- **Dashboard SOC** : http://127.0.0.1:8060
- **Page attaquant** : http://127.0.0.1:8060/attacker

### 6. *(optionnel)* Remédiation 100 % automatique

Le dashboard propose déjà un bouton **« Déclencher la remédiation »** quand une attaque est
détectée. Pour la reprise **entièrement autonome** (sans clic), lancer en plus, dans un autre
terminal :

```powershell
.\.venv\Scripts\python -m remediation.run
```

---

## La démo (Zero-Touch Recovery)

1. Ouvre le **dashboard SOC** (http://127.0.0.1:8060) et la **page attaquant** (`/attacker`).
2. Sur la page attaquant, clique **Lancer** sur une attaque (ex. *DDoS* ou *Injection SQL*), ou
   provoque une panne : `docker compose -f deploy/docker-compose.yml stop db`.
3. Sur le dashboard, **sans rien toucher** : le bandeau passe en **ATTAQUE**, l'assistant explique,
   et la courbe de trafic réagit.
4. Clique **⚡ Déclencher la remédiation** (ou laisse `remediation.run` agir) : le bandeau passe en
   **REMÉDIATION EN COURS**, le journal se remplit (détection → confinement → vérification), puis un
   bandeau vert confirme **« attaque neutralisée — trafic rétabli »**. Un repère vert sur la courbe
   marque l'instant de la remédiation.

---

## Les interfaces et accès

| Interface | Adresse | Identifiants |
|---|---|---|
| Dashboard SOC | http://127.0.0.1:8060 | — |
| Page attaquant | http://127.0.0.1:8060/attacker | — |
| Application de paiement | http://127.0.0.1:8088 | `alice` / `bob` / `charlie` — mot de passe dans `deploy/secrets/demo_password` |
| Grafana | http://127.0.0.1:3000 | `admin` — mot de passe dans `deploy/secrets/grafana_admin_password` |
| Prometheus | http://127.0.0.1:9090 | — |

### Attaquer depuis un autre PC

Possible sur le réseau fermé de l'équipe (hotspot). Voir **[redteam/PC-ATTAQUANT.md](redteam/PC-ATTAQUANT.md)** :
il suffit du dossier `labtest/` et de Python 3 côté attaquant ; la console, elle, reste sur l'hôte.

---

## Sécurité en place

- Données **100 % fictives** ; aucun secret en clair dans le dépôt.
- WAF en **mode blocage** (OWASP CRS) ; journaux sans mots de passe ni jetons.
- Conteneurs durcis (non-root, lecture seule, privilèges retirés) ; réseaux internes isolés ; seul le WAF est publié.
- Rôles SQL séparés (droits minimaux par service).
- **Remédiation à droits minimaux** : actions prédéfinies sur cibles connues, jamais de commande arbitraire.
- Les attaques restent **sur le réseau fermé de l'équipe**, jamais sur le campus.

---

## Documentation

| Fichier | Contenu |
|---|---|
| **[DOCUMENTATION_COMPLETE.md](DOCUMENTATION_COMPLETE.md)** | Documentation complète (~10 pages) : logique, KPI, signatures, remédiation |
| [RAPPORT.md](RAPPORT.md) | Mini-rapport (une page) pour une lecture rapide |
| [redteam/PC-ATTAQUANT.md](redteam/PC-ATTAQUANT.md) | Lancer les attaques depuis un autre PC |

---

## Structure du projet

| Dossier | Rôle |
|---|---|
| `deploy/` | Docker Compose, génération des secrets |
| `services/` | `auth`, `payment-api` (API), `waf` (règles ModSecurity) |
| `observability/` | Prometheus (KPI), Loki, Grafana |
| `data/` | Collecteur de données + trafic normal de référence |
| `detection/` | Modèle kNN, caractéristiques (KPI), entraînement |
| `assistant/` | Assistant RAG (LLM local + base de connaissance) |
| `remediation/` | Moteur, actions, vérification, journal |
| `console/` | Backend + les deux interfaces web |
| `labtest/` · `redteam/` | Harnais d'attaque + guides |
