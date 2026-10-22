# Runbook Red Team — Resilience-Alpha

Scénarios d'attaque du démonstrateur. **Cadre strict** : toutes les actions visent la plateforme
du consortium (le WAF, seul point d'entrée) sur le réseau fermé du groupe. Jamais le campus, un
autre groupe, ni un service tiers (section 9 du sujet).

Deux façons de produire les signatures :

- **A. Outils standards depuis le PC Attaquant** (attendu par le sujet, section 3.4) : un second
  poste lance les outils ci-dessous contre `192.168.137.1:8088`. Aucun script offensif n'est
  versionné dans le dépôt — seulement ces commandes documentées.
- **B. Harnais local `labtest/`** (repli, ou collecte en solo) : équivalents minimaux et
  **limités à 127.0.0.1** (garde-fou `labtest/guard.py`). Voir `python -m labtest.collect_session`.

Cible depuis le PC Attaquant : `http://192.168.137.1:8088` (publier le WAF avec
`$env:EDGE_BIND="192.168.137.1"` sur l'hôte). Prérequis côté hôte : laisser tourner le trafic
normal (`python data/traffic/normal_traffic.py`) et le collecteur (`python data/collector/collect.py`).

Avant chaque scénario, poser l'étiquette sur l'hôte : `python data/collector/labels.py <état>`,
et la remettre à `normal` à la fin. Garder chaque attaque 2-3 min, répéter 3 fois (3 épisodes).

---

## 1. DDoS — saturation (`ddos`)

- **PC Attaquant** (`hey`, générateur de charge HTTP) :
  ```bash
  hey -z 2m -c 200 http://192.168.137.1:8088/api/pay/health
  ```
- **Local** : `python -m labtest.run_scenario ddos --duration 120`
- **Effet KPI attendu** : `edge_req_per_sec` ↑↑, `edge_conn_per_sec` ↑↑, `inprogress` ↑,
  `latency_p95_payment_seconds` ↑, `tx_ok_per_sec` ↓ (clients légitimes évincés).
- **Réponse attendue** : blocage IP / limitation de débit, puis redémarrage de l'API si besoin.

## 2. Force brute — authentification (`brute_force`)

- **PC Attaquant** (`hydra`) :
  ```bash
  hydra -l admin -P mots_de_passe.txt 192.168.137.1 -s 8088 \
        http-post-form "/api/auth/login:username=^USER^&password=^PASS^:C=/:401"
  ```
  (viser un compte **fictif** ; ne jamais utiliser de liste de mots de passe réelle d'un tiers.)
- **Local** : `python -m labtest.run_scenario brute_force --duration 120`
- **Effet KPI attendu** : `login_fail_per_sec` ↑↑, `latency_p95_login_seconds` ↑ (hachage Argon2).
- **Réponse attendue** : blocage IP + verrouillage du compte visé (déjà déclenché après 10 échecs).

## 3. Injection SQL (`sql_injection`)

- **PC Attaquant** (`sqlmap`) :
  ```bash
  sqlmap -u "http://192.168.137.1:8088/api/pay/accounts?id=1" --batch --level=2
  ```
- **Local** : `python -m labtest.run_scenario sql_injection --duration 120`
- **Effet KPI attendu** : `waf_blocked_per_sec` ↑↑ (requêtes arrêtées au WAF, 403), `err_4xx` ↑.
  Les requêtes paramétrées de l'API neutralisent l'injection : `db_errors_per_sec` reste bas.
- **Réponse attendue** : **confinement** (blocage IP + alerte), PAS un simple redémarrage —
  c'est une tentative de compromission, pas une panne de disponibilité.

## 4. Reconnaissance / balayage (`port_scan`)

- **PC Attaquant** (`nmap` + énumération de chemins) :
  ```bash
  nmap -sS -p 1-10000 192.168.137.1
  ffuf -u http://192.168.137.1:8088/api/pay/FUZZ -w chemins.txt   # énumération
  ```
- **Local** : `python -m labtest.run_scenario port_scan --duration 120`
- **Effet KPI attendu** : `edge_conn_per_sec` ↑, `waf_404_per_sec` ↑ (chemins inexistants).
- **Réponse attendue** : blocage IP + surveillance ; pas de redémarrage.

## 5. Panne de service (`service_down`) — injection de panne

Chaos engineering sur **notre propre** conteneur (pas une attaque réseau) :
```bash
docker compose -f deploy/docker-compose.yml stop db     # provoque la panne
docker compose -f deploy/docker-compose.yml start db    # (sinon la remédiation le fait, phase 7)
```
- **Effet KPI attendu** : `tx_ok_per_sec` → 0, `db_errors_per_sec` ↑, `err_5xx` ↑,
  `latency_p95_payment_seconds` ↑.
- **Réponse attendue** : redémarrage du conteneur, puis vérification `/health` + transaction test.

---

## Collecte automatisée (repli solo)

Une seule commande enchaîne tous les scénarios (local), pilote l'étiquette, lance trafic et
collecteur, et produit `data/collector/dataset.csv` :

```powershell
python -m labtest.collect_session --repeat 3
```

Le jeu de données sert ensuite à l'indexation de la détection (`python -m detection.index build`)
puis à l'assistant RAG (`python -m assistant.build_index`).
