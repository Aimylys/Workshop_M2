# Lancer les attaques depuis le PC attaquant

Guide court pour jouer les attaques contre la plateforme **depuis un autre PC**, sur le réseau
fermé de l'équipe (point d'accès Windows `192.168.137.1`, ou hotspot téléphone). Tout vise
uniquement **votre hôte** ; jamais le campus ni un tiers (sujet §3.4 / §9).

## Pré-requis

1. **Côté hôte** : la plateforme tourne et le WAF est exposé sur le réseau (voir le README,
   section « Démonstration avec le PC attaquant » : `EDGE_BIND` + règle de pare-feu 8088).
2. **PC attaquant** : connecté au **même** réseau que l'hôte. Vérifier :
   ```
   ping <IP_DE_L_HOTE>
   ```
3. Remplacer `<IP_DE_L_HOTE>` ci-dessous par l'IP réelle (ex. `192.168.137.1`, ou l'IP donnée
   par le téléphone comme `192.168.43.5`).

---

## Option A — le harnais Python (recommandé : aucune installation)

Copier le dossier `labtest/` sur le PC attaquant (Python 3 suffit, aucune dépendance). Puis,
dans le dossier qui contient `labtest/` :

```powershell
# 1. autoriser explicitement l'IP de l'hôte (sinon le garde-fou refuse)
$env:LABTEST_ALLOW = "<IP_DE_L_HOTE>"
$BASE = "http://<IP_DE_L_HOTE>:8088"

# 2. lancer une attaque (60 s). Profils : ddos | brute_force | sql_injection | port_scan
python -m labtest.run_scenario ddos          --base $BASE --duration 60
python -m labtest.run_scenario brute_force    --base $BASE --duration 60
python -m labtest.run_scenario sql_injection  --base $BASE --duration 60
python -m labtest.run_scenario port_scan      --base $BASE --duration 60
```

Sous Linux/Mac (PC attaquant Kali par ex.) :
```bash
export LABTEST_ALLOW=<IP_DE_L_HOTE>
python3 -m labtest.run_scenario ddos --base http://<IP_DE_L_HOTE>:8088 --duration 60
```

**Panne de service** (`service_down`) : elle s'opère sur l'hôte (arrêt du conteneur db), pas
depuis le PC attaquant :
```powershell
docker compose -f deploy/docker-compose.yml stop db    # sur l'HÔTE
```

---

## Option B — outils standards (si le PC attaquant les a)

| Attaque | Commande (depuis le PC attaquant) |
|---|---|
| DDoS | `hey -z 60s -c 50 http://<IP_DE_L_HOTE>:8088/api/pay/health` |
| Force brute | `hydra -l admin -P mdp.txt <IP_DE_L_HOTE> -s 8088 http-post-form "/api/auth/login:username=^USER^&password=^PASS^:C=/:401"` |
| Injection SQL | `sqlmap -u "http://<IP_DE_L_HOTE>:8088/api/pay/accounts?id=1" --batch --level=2` |
| Reconnaissance | `nmap -sS -p 1-10000 <IP_DE_L_HOTE>` |

> ⚠️ Sur ce poste à 2 cœurs, garder une intensité **modérée** (`-c 50` pour hey, etc.) : un flot
> trop fort bloque la VM Docker Desktop. Le but est de produire la *signature*, pas d'écrouler l'hôte.

---

## Voir l'effet (sur l'hôte)

- **Dashboard SOC** : `python -m console.app` → http://127.0.0.1:8060 (verdict, KPI, explication RAG).
- **Grafana** : http://127.0.0.1:3000 (courbes de trafic et journaux).

Le détecteur doit basculer sur le type d'attaque quelques secondes après le début (fenêtre de
30 s), puis revenir à « normal » après l'arrêt.
