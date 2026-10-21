# Base de connaissances des attaques — Project Resilience-Alpha

Ce document décrit chaque type d'attaque, les signatures observables dans les
KPI, leur signification, et la remédiation recommandée. Il est fourni à Ollama
comme contexte pour analyser une mesure en direct.

Les KPI disponibles (par seconde sauf indication) :
- req_per_sec        : requêtes totales reçues
- err_5xx_per_sec    : erreurs serveur (500, 503)
- err_4xx_per_sec    : erreurs client (400, 401, 404)
- login_fail_per_sec : échecs de connexion
- login_ok_per_sec   : connexions réussies
- sql_errors_per_sec : erreurs SQL
- tx_ok_per_sec      : transactions réussies
- tx_err_per_sec     : transactions en erreur
- inprogress         : requêtes en cours à l'instant T
- latency_p95        : temps de réponse au 95e percentile (secondes)
- api_cpu_per_sec    : CPU consommé par l'API
- api_net_rx_per_sec : octets reçus

---

## normal
Signification : fonctionnement sain de la plateforme de paiement.
Signature : req_per_sec faible et stable (environ 10 à 30), latency_p95 basse
(< 0.3 s), peu ou pas d'erreurs, login_fail proche de 0, transactions qui
réussissent.
Remédiation : aucune. Le service est utilisable.

## ddos
Signification : attaque par saturation (déni de service). L'attaquant inonde
l'API de requêtes pour épuiser ses ressources et rendre le service indisponible
pour les vrais utilisateurs.
Signature : req_per_sec très élevé (plusieurs centaines), latency_p95 qui
explose (> 2 s, parfois > 10 s), inprogress élevé, api_cpu élevé, apparition
d'err_5xx quand le service sature.
Remédiation : limiter le débit (rate limiting), bloquer l'IP source dans le WAF,
puis redémarrer le service si nécessaire pour vider la file d'attente.

## brute_force
Signification : tentative de deviner un mot de passe en essayant un grand nombre
de combinaisons sur la page de connexion.
Signature : login_fail_per_sec très élevé, err_4xx (401) en hausse, le tout
concentré sur /login. req_per_sec peut rester modéré : ce n'est pas le volume
global qui trahit l'attaque mais le taux d'échecs de connexion.
Remédiation : bloquer l'IP source, verrouiller temporairement le compte visé,
imposer un délai entre tentatives.

## sql_injection
Signification : l'attaquant insère du code SQL dans les entrées de l'application
pour manipuler la base de données (lire, modifier ou extraire des données).
Signature : sql_errors_per_sec en hausse, err_5xx en hausse, présence de motifs
suspects dans les requêtes. Le volume de requêtes reste souvent normal.
Remédiation : bloquer l'IP, activer le filtrage WAF sur les motifs d'injection,
vérifier l'intégrité de la base de données.

## service_down
Signification : un composant critique (par exemple la base de données) est tombé
ou a été arrêté. Ce n'est pas une attaque réseau mais une panne.
Signature : err_5xx_per_sec très élevé, tx_ok_per_sec qui tombe à 0, l'API
répond en erreur bien que recevant des requêtes.
Remédiation : redémarrer le conteneur défaillant, vérifier que le service répond
à nouveau via la sonde /health.

## port_scan
Signification : reconnaissance. L'attaquant sonde les ports pour découvrir les
services exposés avant une attaque plus ciblée.
Signature : surtout visible au niveau réseau (connexions multiples sur des ports
variés). Laisse peu de traces dans les KPI applicatifs ; peut légèrement
augmenter api_net_rx sans changer req_per_sec.
Remédiation : alerter, bloquer l'IP source, vérifier que seuls les ports requis
sont exposés.
