# Remédiation automatique (phase 7) — Zero-Touch Recovery

```
détecteur (kNN) ──verdict──► remediation.run ──► engine ──► action prédéfinie ──► VÉRIFICATION ──► journal
                               (anti-rebond)                 bloquer IP / redémarrer   /health + transaction test   (JSONL)
```

La **détection décide**, la **remédiation agit**, l'**assistant RAG explique** : trois rôles séparés
(exigence du sujet). La remédiation n'exécute **que des actions prédéfinies sur des cibles connues**.

## Actions par type

| Type | Nature | Action |
|---|---|---|
| `service_down` | disponibilité | redémarre le conteneur (db, puis api), **vérifie la reprise** |
| `ddos` | disponibilité | bloque l'IP source, redémarre l'API si encore dégradée, vérifie |
| `brute_force` | abus | bloque l'IP source (verrouillage de compte déjà automatique), vérifie le métier |
| `port_scan` | reconnaissance | bloque l'IP source, surveille |
| `sql_injection` | compromission | **confinement seul** : bloque l'IP, alerte — **jamais** « résolu » automatiquement |

- **Arrêt de l'attaque** : en production, l'IP source est **bloquée au WAF** (requêtes en 403).
  Dans le **labo fermé**, l'attaque part de notre propre harnais de test : son IP est la passerelle
  Docker locale, donc protégée (`never_block`) et jamais bloquée. La remédiation la **coupe alors à
  la source** via la console (`POST /api/attacks/<profil>/stop`) — étape `lab-containment` du journal.
  C'est pour cela que, depuis la console, l'attaque s'arrête *vraiment* après la détection.
- **IP source** : retrouvée dans **Loki** (journaux WAF/auth), car les KPI sont agrégés.
- **Preuve de reprise** : `/health` **plus** une **transaction de test réussie** (compte `probe`),
  pas un simple redémarrage.
- **Droits minimaux** : IP validée et hors `never_block` ; redémarrage limité à une liste blanche ;
  aucune commande arbitraire. En production : passer par un proxy Docker à droits « restart » seuls.
- **Anti-boucle** : on n'agit qu'après `DEBOUNCE` détections consécutives, et pas deux fois dans
  `COOLDOWN_S`. Tout est **idempotent** (IP déjà bloquée = rien, service déjà sain = pas de redémarrage).

## Lancer la démo complète (Zero-Touch)

Prérequis : plateforme up, modèle de détection construit, Loki publié sur `127.0.0.1:3100`.

```powershell
# Terminal 1 — supervision
python -m console.app                 # dashboard http://127.0.0.1:8060

# Terminal 2 — remédiation automatique (le pont détection -> action)
python -m remediation.run

# Puis provoquer un incident :
#   panne   : docker compose -f deploy/docker-compose.yml stop db
#   réseau  : attaque depuis le PC attaquant (voir redteam/PC-ATTAQUANT.md)
```

Le dashboard montre alors, sans aucune intervention : le verdict bascule → l'explication RAG
s'affiche → le **journal de remédiation** se remplit (détection → confinement/redémarrage →
vérification → « resolved ») → le service repart et une transaction de test réussit.

## Réinitialiser après une démo

```powershell
python -c "from remediation import actions; [actions.unblock_ip(ip) for ip in actions.list_blocked() if ip!='192.0.2.255']"
```

## Résultats validés

- `service_down` : db arrêtée → détectée → **conteneur redémarré → transaction test n°… réussie →
  « resolved » en ~14 s**, entièrement automatique.
- `sql_injection` : IP source identifiée via Loki → **confinement** (pas de redémarrage, analyse
  humaine requise) — la disponibilité et la compromission sont bien distinguées.
- Blocage d'IP : idempotent, `never_block` respecté (on ne bloque pas sa propre passerelle).

## Limite connue

La détection des attaques **réseau** (ddos/brute_force/sql_injection/port_scan) dépend du modèle
entraîné sur le style d'attaque courant : réentraîner après une collecte avec les attaques douces
(voir `detection/README.md`). La détection de `service_down` ne dépend pas de l'intensité.
