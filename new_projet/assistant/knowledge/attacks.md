# Base de connaissance des incidents — plateforme de paiement Resilience-Alpha

Fiches destinées à l'assistant RAG. Elles décrivent chaque état que la détection peut
identifier, sa signature sur les KPI, son effet sur la plateforme de paiement et la remédiation
recommandée. L'assistant s'en sert pour EXPLIQUER un incident à l'opérateur ; il ne déclenche
aucune action.

## État : normal

Fonctionnement nominal. Le trafic, les connexions et les virements restent dans leurs plages
habituelles ; aucune requête n'est bloquée en bordure de façon notable. Aucune action requise.
Repères typiques : quelques requêtes par seconde, une poignée de virements réussis par seconde,
latence de paiement sous 0,3 s, `api_up = 1`.

## État : ddos (déni de service par saturation)

Déni de service : un volume anormal de requêtes sature l'API et la base, au point de dégrader ou
d'interrompre le service de paiement pour les clients légitimes.

Signature sur les KPI : `edge_req_per_sec` et `req_per_sec` très élevés, `inprogress` (requêtes en
cours) qui monte, `latency_p95_payment_seconds` qui s'allonge, `tx_ok_per_sec` qui chute parce que
les virements légitimes n'aboutissent plus. Le CPU des conteneurs applicatifs augmente.

Enjeu paiement : indisponibilité = virements retardés, perte de confiance. C'est une atteinte à la
DISPONIBILITÉ : une fois la source confinée, le service peut être déclaré rétabli après
vérification.

Remédiation recommandée : bloquer l'IP source en bordure (WAF) / limiter le débit, puis, si le
service reste dégradé, redémarrer le conteneur de l'API ; vérifier la reprise par une sonde
`/health` et une transaction de test réussie.

## État : brute_force (force brute sur l'authentification)

Tentatives de connexion répétées pour deviner un mot de passe ou énumérer des comptes.

Signature sur les KPI : `login_fail_per_sec` très élevé (échecs ou comptes verrouillés),
`latency_p95_login_seconds` qui s'allonge (le hachage des mots de passe consomme du CPU), sans
hausse des virements. Le taux d'échec dépasse largement le bruit d'un trafic normal (quelques
fautes de frappe).

Enjeu paiement : compromission de comptes clients. Atteinte à la disponibilité de
l'authentification et, potentiellement, à la confidentialité des comptes visés.

Remédiation recommandée : bloquer l'IP source en bordure et verrouiller le compte ciblé ; le
verrouillage applicatif après N échecs limite déjà l'attaque. Vérifier qu'un compte sain peut
toujours se connecter.

## État : sql_injection (injection SQL)

Requêtes contenant des charges d'injection SQL, visant à détourner les requêtes de la base pour
lire ou altérer des données.

Signature sur les KPI : `waf_blocked_per_sec` très élevé (le pare-feu applicatif arrête ces
requêtes, réponses 403), `err_4xx_per_sec` en hausse. Les requêtes paramétrées de l'API
neutralisent de toute façon l'injection : `db_errors_per_sec` reste bas.

Enjeu paiement : TENTATIVE DE COMPROMISSION. À distinguer d'une simple indisponibilité : même si
le service répond, on ne déclare pas l'incident « résolu » sur la seule reprise. Une analyse
humaine (journaux, intégrité des données) reste nécessaire.

Remédiation recommandée : CONFINEMENT — bloquer l'IP source, alerter, conserver les journaux. Ne
PAS se contenter de redémarrer : la disponibilité n'est pas le sujet, c'est l'intégrité.

## État : service_down (panne d'un service)

Un service essentiel ne répond plus (ici, la base de données), par panne ou par épuisement de
ressources.

Signature sur les KPI : `api_up = 0`, `db_errors_per_sec` en hausse, `tx_ok_per_sec` à zéro,
`err_5xx_per_sec` en hausse. Le trafic entrant peut rester normal : c'est la plateforme qui ne
traite plus.

Enjeu paiement : interruption directe du service. Atteinte à la DISPONIBILITÉ.

Remédiation recommandée : redémarrer le conteneur en panne, puis les services qui en dépendent si
besoin, par paliers ; vérifier la reprise par `/health` et une transaction de test. Un conteneur
qui redémarre ne suffit pas : la preuve est une transaction réussie après coup.

## État : port_scan (reconnaissance)

Balayage de ports et énumération de chemins pour cartographier la plateforme avant une attaque.
Souvent précurseur, peu dommageable en soi.

Signature sur les KPI : `edge_conn_per_sec` en hausse (beaucoup de connexions neuves),
`waf_404_per_sec` en hausse (sondage de chemins inexistants), sans impact marqué sur les virements.

Enjeu paiement : faible impact immédiat, mais signal d'alerte précoce.

Remédiation recommandée : bloquer l'IP source en bordure et surveiller ; pas de redémarrage requis.
