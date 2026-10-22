# Resilience-Alpha — plateforme de paiement fictive à reprise autonome

Démonstrateur du workshop EPSI « PROJECT RESILIENCE-ALPHA » : une plateforme de paiement
**entièrement fictive** qui détecte une attaque et se rétablit sans intervention humaine.

> État : **phases 1 à 7** — plateforme, observabilité, collecte, détection par similarité (kNN),
> assistant RAG, console de supervision + lancement d'attaques, et **remédiation automatique
> (Zero-Touch Recovery)**. Voir [data/README.md](data/README.md),
> [detection/README.md](detection/README.md) et [remediation/README.md](remediation/README.md).

## Architecture

```
                   ┌──────── edge ────────┐   ┌─ web ─┐   ┌──── app ────┐   ┌─ data ─┐
PC attaquant ─┐    │                      │   │       │   │  auth       │   │        │
navigateur ───┴──► │ WAF (ModSecurity+CRS)├──►│frontal├──►│  payment-api├──►│   db   │
                   │ EDGE_BIND:EDGE_PORT  │   │ nginx │   │  (JWT)      │   │        │
                   └──────────┬───────────┘   └───────┘   └──────┬──────┘   └────────┘
                              │ journaux JSON                    │ /metrics (port 9000)
               ┌──────────────┴─────────── monitoring ───────────┴────────────────┐
               │ Alloy ──► Loki (SIEM)        Prometheus ◄── exporter nginx, cAdvisor│
               │                 └──────► Grafana ◄──────┘                          │
               └──────────────── publiés sur 127.0.0.1 uniquement : 9090, 3000 ─────┘
```

| Service | Rôle | Exposition |
|---|---|---|
| `waf` | Nginx + ModSecurity + OWASP CRS 4 (mode **blocage**), liste de blocage d'IP | **seul point d'entrée** : `127.0.0.1:8088` |
| `frontend` | Application web React/Tailwind + proxy vers les API | interne |
| `auth` | Connexion, JWT, verrouillage après 10 échecs | interne (+ métriques :9000) |
| `payment-api` | Comptes, virements atomiques et idempotents | interne (+ métriques :9000) |
| `db` | PostgreSQL ; un rôle SQL par service, droits minimaux | interne, jamais publié |
| `prometheus` | Métriques + **KPI définis une seule fois** (`kpi:*`) | `127.0.0.1:9090` |
| `loki` + `alloy` | Centralisation des journaux (SIEM) | interne |
| `grafana` | Visualisation (tableau de bord provisionné) | `127.0.0.1:3000` |
| `nginx-exporter`, `cadvisor` | Métriques du WAF et de la VM Docker | interne |

## Démarrage

Prérequis : Docker Desktop (WSL2), Python 3.12.

```powershell
python deploy/gen_secrets.py                                # crée deploy/secrets/* (non versionnés)
docker compose -f deploy/docker-compose.yml up -d --build
python tests/smoke_test.py                                  # vérification de bout en bout (via le WAF)
python data/traffic/normal_traffic.py                       # trafic normal de référence (Ctrl+C)
```

| Interface | Adresse | Identifiants |
|---|---|---|
| Application | http://127.0.0.1:8088 | `alice` / `bob` / `charlie`, mot de passe dans `deploy/secrets/demo_password` |
| Grafana | http://127.0.0.1:3000 | `admin`, mot de passe dans `deploy/secrets/grafana_admin_password` |
| Prometheus | http://127.0.0.1:9090 | — |
| Doc des API | http://127.0.0.1:8088/api/auth/docs, http://127.0.0.1:8088/api/pay/docs | — |

### Démonstration avec le PC attaquant

Le WAF est publié sur `127.0.0.1` par défaut. Pour le rendre joignable depuis le point d'accès
`RESILIENCE-G<n>` (hotspot Windows actif, hôte en `192.168.137.1`) :

```powershell
$env:EDGE_BIND = "192.168.137.1"
docker compose -f deploy/docker-compose.yml up -d waf
```

Seul le WAF est alors exposé au réseau du groupe ; Grafana, Prometheus et la base restent
inaccessibles depuis le PC attaquant.

**À vérifier une fois, depuis le PC attaquant** (le blocage d'IP de la remédiation en dépend) :
```bash
curl -s -o /dev/null http://192.168.137.1:8088/api/pay/health
```
puis sur l'hôte : `docker compose -f deploy/docker-compose.yml logs --tail 5 waf`. Le champ
`"ip"` doit être l'adresse du PC attaquant (`192.168.137.x`). S'il affiche une adresse
`172.x.x.x`, Docker Desktop masque l'IP source et le blocage par IP devra être adapté.

## KPI (Prometheus, règles `observability/prometheus/rules/kpi.yml`)

Tous les consommateurs (collecteur, détection, dashboard, Grafana) lisent ces séries ; aucun ne
réécrit de PromQL. Changer un nom de métrique de l'API ne touche que ce fichier.

| KPI | Signification |
|---|---|
| `kpi:req_per_sec`, `kpi:err_4xx_per_sec`, `kpi:err_5xx_per_sec` | Trafic et erreurs des API |
| `kpi:latency_p95_payment_seconds`, `kpi:latency_p95_login_seconds`, `kpi:inprogress` | Latence (paiement / connexion) et saturation |
| `kpi:login_ok_per_sec`, `kpi:login_fail_per_sec` | Authentification |
| `kpi:tx_ok_per_sec`, `kpi:tx_failed_per_sec`, `kpi:db_errors_per_sec` | Métier |
| `kpi:api_up` | 1 si auth et paiement répondent, 0 sinon |
| `kpi:edge_req_per_sec`, `kpi:edge_connections`, `kpi:edge_conn_per_sec` | Bordure : requêtes, connexions ouvertes, nouvelles connexions TCP |
| `kpi:waf_blocked_per_sec`, `kpi:waf_404_per_sec` | Requêtes bloquées par le WAF, chemins inexistants (reconnaissance) |
| `kpi:api_cpu_cores`, `kpi:api_mem_bytes`, `kpi:host_cpu_cores`, `kpi:host_mem_bytes` | Ressources |

## Journaux (Loki)

Chaque service écrit une ligne JSON par événement. Labels : `service`, `level`, `event`
(`http_request`, `login`, `transaction`, `transaction_rejected`, `db_error`, `waf_access`,
`waf_audit`). L'IP et l'utilisateur restent dans la ligne. Exemple de recherche SIEM dans Grafana :

```logql
sum by (ip) (count_over_time({service="auth", event="login"} | json | result!="success" [15m]))
```

## Tests

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest tests/unit     # sans base de données
python tests/smoke_test.py                       # sur la plateforme lancée
```

## Sécurité en place

- Données 100 % fictives ; aucun secret dans le code ni dans le dépôt (`deploy/secrets/` ignoré).
- WAF en mode blocage (CRS 4, paranoïa 1) ; exclusions justifiées dans `services/waf/rules/after-crs.conf`.
- Audit ModSecurity sans corps de requête ni en-têtes : aucun mot de passe ni jeton dans les journaux.
- L'IP client vient du WAF seul (`X-Real-IP` écrasé, IP du WAF fixe) : pas d'usurpation par en-tête.
- Conteneurs non-root, système de fichiers en lecture seule, `cap_drop: ALL`, `no-new-privileges`.
- Réseaux internes ; seul le WAF est publié. Prometheus et Grafana : `127.0.0.1` uniquement.
- Accès Docker d'Alloy par un proxy en **lecture seule** (`POST=0`), jamais le socket directement.
- Mots de passe Argon2id à mémoire bornée : une rafale de connexions ne fait pas tomber `auth`.
- Rôles SQL séparés : `payment_svc` ne peut ni supprimer une transaction, ni modifier autre chose
  que le solde, ni lire la table des utilisateurs.

## Limites connues

- **cAdvisor par conteneur** : sous Docker Desktop avec le stockage d'images containerd, cAdvisor
  ne voit que la VM entière. Les ressources par service viennent des métriques de processus.
