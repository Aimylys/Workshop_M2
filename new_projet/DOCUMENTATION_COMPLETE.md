# Resilience-Alpha — Documentation complète du système

*Plateforme de paiement fictive à reprise autonome. Ce document explique la **logique** du système
pour un jury et des coéquipiers : comment on mesure, détecte, explique, remédie et vérifie. Il ne
décrit pas comment lancer les outils ; chaque affirmation correspond au comportement réel du code.*

---

## 1. Vue d'ensemble

Resilience-Alpha simule une petite banque en ligne qui **se défend et se répare sans intervention
humaine**. Le système repose sur une boucle de cinq temps :

**Mesurer → Détecter → Expliquer → Remédier → Vérifier.**

- **Mesurer.** Chaque service écrit des métriques et des journaux. Prometheus en tire une courte
  liste d'indicateurs (les *KPI*), recalculés en continu. C'est la photographie de l'état de la
  plateforme à l'instant présent.
- **Détecter.** Un modèle d'apprentissage (k plus proches voisins) compare cette photographie aux
  situations déjà observées et rend un **verdict** : trafic normal, ou l'un des types d'attaque
  connus, ou « inconnu ».
- **Expliquer.** Un assistant documentaire (RAG) rédige en français, pour l'opérateur, ce que
  signifie l'état détecté et ce qu'il faut faire. Il **explique seulement**.
- **Remédier.** Un moteur exécute une **action prédéfinie** adaptée au type d'incident : bloquer la
  source, redémarrer un service, confiner.
- **Vérifier.** La remédiation ne se déclare jamais réussie sur un simple redémarrage : elle
  **prouve** la reprise par une sonde de santé **et** une transaction de test qui aboutit.

### Une règle structurante : la séparation des rôles

Le système sépare volontairement trois responsabilités, et aucune ne déborde sur l'autre :

| Rôle | Qui | Ce qu'il fait | Ce qu'il ne fait pas |
|---|---|---|---|
| **Décider** | La détection (kNN) | Dit *si* c'est une attaque et *laquelle* | N'agit pas, n'explique pas |
| **Expliquer** | L'assistant RAG | Décrit l'incident et la conduite à tenir | Ne décide pas, n'agit jamais |
| **Agir** | Le moteur de remédiation | Exécute l'action prédéfinie et vérifie | N'improvise aucune action |

Cette séparation est une garantie de sûreté : c'est la détection (déterministe, traçable) qui
déclenche l'action, pas le modèle de langage. L'assistant peut se tromper dans sa prose sans jamais
provoquer d'action sur la plateforme.

---

## 2. La collecte des données

La détection a besoin d'apprendre à quoi ressemblent le trafic normal et chaque attaque. Cette
connaissance vient d'un **jeu de données étiqueté**, construit en observant la plateforme réelle.

### D'où viennent les KPI

Les services (authentification, paiement, pare-feu applicatif) exposent des **métriques brutes**.
Prometheus les interroge régulièrement et, grâce à des **règles d'enregistrement**, en calcule une
liste stable de KPI nommés `kpi:…`. Ce fichier de règles est la **définition unique** : le
collecteur, la détection, le tableau de bord et Grafana lisent tous ces mêmes séries, et aucun ne
réécrit de requête. Changer la façon de mesurer ne se fait donc qu'à un seul endroit.

### Comment Prometheus les calcule, et à quelle fréquence

- Les règles sont réévaluées **toutes les 5 secondes**.
- La plupart des KPI sont des **débits moyennés sur une fenêtre glissante de 30 secondes** (par
  exemple « requêtes par seconde »). Une moyenne sur 30 s lisse le bruit tout en réagissant vite.
- Les sondes de santé internes des conteneurs (`/health`) sont **exclues** des compteurs
  applicatifs, pour ne pas gonfler le trafic « métier » avec de la surveillance technique.
- Un indicateur de disponibilité vaut **1 si les deux API répondent, 0 sinon** : un service arrêté
  ne « disparaît » pas des mesures, il compte comme zéro.

Le collecteur prend une **photographie** de tous les KPI à intervalle régulier (par défaut toutes
les 5 secondes) et écrit une ligne dans le jeu de données. Il applique des garde-fous stricts pour
ne jamais enregistrer de fausse donnée :

- si Prometheus est injoignable, **aucune** ligne n'est écrite (une ligne de zéros étiquetée
  « attaque » empoisonnerait l'apprentissage) ;
- juste après un redémarrage de Prometheus, la fenêtre de 30 s est incomplète ; le collecteur
  **attend** d'avoir assez d'échantillons avant d'enregistrer ;
- il évite les doublons en vérifiant que les règles ont bien été recalculées depuis la dernière
  ligne ;
- un KPI sans valeur (par exemple la latence quand il n'y a aucune requête) laisse une **case
  vide**, jamais un zéro inventé.

### Le « trafic normal de référence » et pourquoi il est indispensable

Un générateur simule des **clients fictifs** (alice, bob, charlie) qui se connectent, consultent
leurs comptes et leur historique, et se font de petits virements. Fait important : il inclut une
**petite part de fautes de frappe** au mot de passe (environ 3 %). Un trafic réel en contient ; sans
cela, le modèle prendrait la moindre erreur de connexion pour une attaque par force brute.

Ce trafic normal est la **référence** du système. La détection ne raisonne pas dans l'absolu : elle
mesure l'écart par rapport au normal. Sans une bonne base « normale », impossible de dire qu'un
indicateur est « anormalement » haut. C'est pourquoi la collecte fait toujours tourner le trafic
normal en fond, y compris pendant les attaques.

### L'étiquetage par type d'état

Chaque ligne du jeu de données porte une **étiquette** : `normal`, `ddos`, `brute_force`,
`sql_injection`, `port_scan` ou `service_down`. L'étiquette courante est pilotée par un petit
fichier que l'équipe change juste avant de lancer une attaque, puis remet à `normal` à la fin.
Chaque changement est horodaté pour la traçabilité.

À chaque changement d'étiquette, le collecteur ouvre un nouvel **épisode** (un numéro qui
s'incrémente). Un épisode est un bloc continu de lignes du même état. Cette notion est essentielle
pour mesurer honnêtement la qualité : on entraîne le modèle sur certains épisodes et on le teste sur
d'autres, jamais vus, ce qui évite qu'il « triche » en reconnaissant deux lignes voisines d'une même
attaque.

Une session de collecte complète enchaîne automatiquement : une phase de chauffe en trafic normal,
puis, pour chaque passage, les cinq états les uns après les autres avec un retour au normal entre
chaque. On obtient ainsi un jeu de données équilibré et étiqueté sans intervention manuelle.

---

## 3. La détection par apprentissage (k plus proches voisins)

### De l'état courant à un vecteur de KPI

À chaque instant, la plateforme est résumée par un **vecteur de 18 KPI** (débits, latences,
disponibilité, indicateurs du pare-feu, etc. — voir le catalogue en section 6). On écarte
volontairement les mesures propres à la machine (mémoire, CPU de la machine virtuelle entière) :
elles dépendent du poste et ne se généralisent pas d'un environnement à l'autre.

### Comment la décision est prise

Le modèle est un **k plus proches voisins** (kNN). Son fonctionnement est simple et transparent :

1. Toutes les mesures sont d'abord **standardisées** (chaque KPI est ramené à une échelle commune),
   pour qu'un KPI à grandes valeurs n'écrase pas les autres.
2. Pour l'état courant, on cherche les **k exemples les plus proches** (par défaut 15) parmi toutes
   les situations déjà observées et étiquetées.
3. Le verdict est le **vote majoritaire** de ces voisins : l'étiquette la plus représentée gagne.

Le modèle « apprend » en **mémorisant** les exemples étiquetés ; il n'y a pas d'entraînement lourd
au sens d'un réseau de neurones. L'index EST le modèle. C'est conforme à la contrainte du projet :
pas de création ni d'entraînement d'un modèle à partir de zéro.

### La confiance et le cas « inconnu »

Le verdict est accompagné de deux nombres :

- **La confiance** : la proportion des k voisins qui sont d'accord. Si 13 voisins sur 15 disent
  « ddos », la confiance est de 87 %. Une confiance faible signale un état ambigu, à la frontière
  entre deux situations connues.
- **La distance** : à quel point l'état courant est éloigné de ses voisins. Si cette distance
  dépasse un **seuil** (calé sur la dispersion observée dans les données), le modèle refuse de
  classer de force et répond **« inconnu »**. Ce seuil est volontairement généreux : un faux
  « inconnu » empêcherait la remédiation de se déclencher, ce qui est pire qu'une étiquette d'attaque
  légèrement imprécise.

Le verdict fournit aussi les **indicateurs déclencheurs** : les KPI qui s'écartent le plus de la
moyenne normale (au moins deux écarts-types), triés du plus marquant au moins marquant. Ce sont eux
qui rendent la décision **explicable** et qui alimentent l'assistant.

### Pourquoi du ML et pas de simples seuils

On pourrait écrire des règles du type « si plus de 100 requêtes par seconde, alors DDoS ». C'est
fragile pour plusieurs raisons :

- **Les seuils sont arbitraires et instables.** La bonne valeur dépend de l'heure, de la charge
  normale, du matériel. Un seuil réglé un jour est faux le lendemain.
- **Les attaques se ressemblent sur un seul KPI.** Un pic de requêtes peut venir d'un DDoS comme
  d'un afflux légitime. C'est la **combinaison** des KPI qui distingue les états (par exemple : trafic
  en bordure très élevé **et** virements qui chutent **et** latence qui s'allonge).
- **Le ML raisonne sur la forme globale.** Le kNN compare le vecteur entier à des situations réelles
  déjà vues : il capture ces combinaisons sans qu'on ait à les énoncer une par une.
- **C'est maintenable.** Ajouter un nouveau type d'incident, c'est collecter des exemples étiquetés,
  pas réécrire une forêt de `si… alors…`.

---

## 4. L'assistant RAG

### Son rôle : expliquer, jamais agir

Quand la détection signale un incident, l'assistant produit une **explication en français** de 2 à
4 phrases : ce que signifie l'état, son risque pour une plateforme de paiement, et la remédiation
recommandée. Il est explicitement cantonné à ce rôle. Son instruction interne lui interdit de
proposer d'exécuter lui-même une action et de sortir du contexte qu'on lui fournit. Même s'il était
imprécis, il ne pourrait rien déclencher : il n'a aucun accès au système.

### Comment il récupère la bonne connaissance (RAG)

RAG signifie « génération augmentée par la recherche ». Au lieu de demander au modèle de langage de
répondre de mémoire (au risque d'inventer), on procède en deux temps :

1. **Recherche.** On a une **base de connaissance** : des fiches décrivant chaque état, sa
   signature sur les KPI, son enjeu et sa remédiation. Ces fiches sont transformées en vecteurs et
   rangées dans un index de similarité (FAISS). À partir du type d'incident, on récupère les
   quelques fiches les plus pertinentes.
2. **Rédaction.** On fournit ces fiches, **et uniquement elles**, comme contexte à un modèle de
   langage **local** (llama3.2 à 3 milliards de paramètres, exécuté sur la machine via Ollama,
   conforme à la limite du sujet). Le modèle résume ce contexte en une explication claire, en tenant
   compte des indicateurs déclencheurs transmis par la détection.

La base de connaissance a deux origines : des **fiches écrites à la main** (une par état) et des
**fiches générées automatiquement** à partir du jeu de données réel (la signature chiffrée observée
pour chaque état). L'assistant cite ses **sources**, et ne lève jamais d'erreur vers le tableau de
bord : si le modèle local est indisponible, il renvoie un message clair au lieu de planter.

### Pourquoi il est séparé de la détection

Un modèle de langage peut « halluciner ». Le laisser décider ou agir serait dangereux. En le
confinant à l'explication, on obtient le meilleur des deux mondes : une décision **fiable et
traçable** (le kNN) et une restitution **lisible par un humain** (le RAG), sans jamais confier le
pilotage de la plateforme au composant le moins prévisible.

---

## 5. Catalogue des attaques

Chaque attaque est jouée par un **harnais de laboratoire** contre la plateforme, sur un réseau
fermé. Les profils utilisent **peu de connexions persistantes** et un débit borné : sur la machine
de démonstration (deux cœurs), c'est le nombre de connexions simultanées qui sature, pas le débit ;
on produit donc la *signature* de l'attaque sans écrouler l'observabilité.

### 5.1 DDoS — déni de service par saturation

- **Ce que c'est.** Un volume anormal de requêtes envoyées vers un point d'entrée public (ici la
  sonde de santé du service de paiement), via quelques connexions maintenues ouvertes et réutilisées.
- **Ce qu'elle cherche.** Saturer l'infrastructure (pare-feu, API, base) pour **dégrader ou
  interrompre** le service des clients légitimes. C'est une atteinte à la **disponibilité**.
- **Comment elle se manifeste.** Le pare-feu en bordure voit son volume de requêtes exploser ; le
  nombre de requêtes en cours de traitement monte ; la latence des paiements s'allonge ; le CPU des
  conteneurs applicatifs augmente. Détail important et fidèle à notre code : comme la cible est une
  sonde `/health`, exclue des compteurs applicatifs, c'est l'indicateur de **bordure**
  (`edge_req_per_sec`) qui porte la signature, pas le compteur de requêtes « métier ».
- **Effet observable.** Si du trafic légitime tourne en parallèle, les virements réussis par seconde
  chutent : le service devient inutilisable pour les vrais clients.

### 5.2 Force brute — sur l'authentification

- **Ce que c'est.** Des tentatives de connexion répétées avec de mauvais mots de passe. Le harnais
  vise volontairement un compte **inexistant** (« admin »), pour produire des échecs sans verrouiller
  un vrai compte de démonstration.
- **Ce qu'elle cherche.** Deviner un mot de passe ou énumérer des comptes — donc **compromettre**
  des comptes clients.
- **Comment elle se manifeste.** Le nombre d'échecs de connexion par seconde explose, bien au-delà
  du bruit des fautes de frappe du trafic normal. La latence de connexion s'allonge, parce que le
  hachage sécurisé des mots de passe (Argon2) consomme du CPU à chaque tentative.
- **Effet observable.** Pas d'impact sur les virements ; l'empreinte est concentrée sur
  l'authentification. Un verrouillage applicatif après un certain nombre d'échecs limite déjà
  l'attaque.

### 5.3 Injection SQL

- **Ce que c'est.** Des requêtes contenant des charges d'injection SQL, envoyées sur un paramètre
  d'URL d'une API.
- **Ce qu'elle cherche.** Détourner les requêtes vers la base pour **lire ou altérer des données** —
  une atteinte à l'**intégrité/confidentialité**, pas à la disponibilité.
- **Comment elle se manifeste.** Le pare-feu applicatif (ModSecurity, règles OWASP) **détecte et
  bloque** ces requêtes avec une réponse 403, avant qu'elles n'atteignent l'application. La signature
  est donc le nombre de **requêtes bloquées en bordure par seconde** qui monte fortement. Les requêtes
  de l'API étant de toute façon paramétrées, les erreurs de base restent basses.
- **Effet observable.** Le service continue de répondre normalement. C'est précisément le piège :
  l'absence d'indisponibilité ne veut pas dire qu'il ne s'est rien passé. C'est pourquoi cet état est
  traité comme une **tentative de compromission** (voir section 8).

### 5.4 Scan de ports / reconnaissance

- **Ce que c'est.** Un balayage de chemins d'API inexistants (`/api/pay/…`, `/api/auth/…` suivis de
  chaînes aléatoires), pour cartographier la plateforme.
- **Ce qu'elle cherche.** Préparer une attaque future en découvrant les points d'entrée. Peu
  dommageable en soi, mais c'est un **signal d'alerte précoce**.
- **Comment elle se manifeste.** Le nombre de réponses **404** vues par le pare-feu par seconde
  monte (chemins inexistants sondés). Selon la façon de se connecter, le nombre de nouvelles
  connexions en bordure peut augmenter aussi.
- **Effet observable.** Aucun impact marqué sur les virements ni sur la disponibilité.

### 5.5 Panne de service

- **Ce que c'est.** Un service essentiel ne répond plus. Dans la démonstration, on arrête le
  conteneur de la base de données. (Cette panne s'opère sur l'hôte, pas via le réseau.)
- **Ce qu'elle cherche.** Représenter une défaillance — panne matérielle, épuisement de ressources,
  incident d'exploitation. Atteinte directe à la **disponibilité**.
- **Comment elle se manifeste.** L'indicateur de disponibilité tombe à **0**, les erreurs de base
  montent, les virements réussis tombent à zéro, les erreurs serveur (5xx) augmentent. Le trafic
  entrant, lui, peut rester parfaitement normal : c'est la plateforme qui ne **traite** plus, pas le
  client qui a disparu.
- **Effet observable.** Interruption nette du service de paiement, sans signal d'attaque réseau.

---

## 6. Catalogue des KPI

Les KPI sont regroupés par origine. **Source** indique d'où vient la mesure brute. **Unité** et
**interprétation** disent comment la lire. La colonne **Détection** indique si le KPI entre dans le
vecteur du modèle (18 KPI) ou s'il n'est que du contexte.

### 6.1 Trafic applicatif (mesuré par les services de paiement et d'authentification)

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `req_per_sec` | Requêtes applicatives traitées (hors `/health`) | Compteur applicatif | req/s | Haut = forte charge métier | oui |
| `err_4xx_per_sec` | Erreurs client (4xx) côté application | Compteur applicatif | req/s | Haut = requêtes refusées/mauvaises | oui |
| `err_5xx_per_sec` | Erreurs serveur (5xx) côté application | Compteur applicatif | req/s | Haut = l'application échoue (souvent panne) | oui |
| `inprogress` | Requêtes en cours de traitement simultanément | Jauge applicative | nombre | Haut = saturation, traitements qui s'accumulent | oui |
| `latency_p95_payment_seconds` | 95ᵉ centile du temps de réponse des paiements | Histogramme applicatif | secondes | Haut = paiements lents (saturation, base en difficulté) | oui |
| `latency_p95_login_seconds` | 95ᵉ centile du temps de réponse des connexions | Histogramme applicatif | secondes | Haut = connexions lentes (CPU du hachage sous force brute) | oui |

### 6.2 Authentification

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `login_ok_per_sec` | Connexions réussies | Compteur applicatif (auth) | req/s | Haut = activité de connexion normale | oui |
| `login_fail_per_sec` | Connexions en échec ou comptes verrouillés | Compteur applicatif (auth) | req/s | Haut = force brute (bien au-delà des fautes de frappe) | oui |

### 6.3 Métier (paiement)

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `tx_ok_per_sec` | Virements réussis | Compteur applicatif (paiement) | req/s | **Bas = service dégradé** (DDoS, panne) ; c'est le cœur du métier | oui |
| `tx_failed_per_sec` | Virements en échec | Compteur applicatif (paiement) | req/s | Haut = l'opération métier échoue | oui |
| `db_errors_per_sec` | Erreurs d'accès à la base | Compteur applicatif (paiement) | req/s | Haut = base indisponible ou en difficulté | oui |

### 6.4 Disponibilité

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `api_up` | 1 si auth **et** paiement répondent, 0 sinon | Santé de collecte Prometheus | 0 ou 1 | **0 = panne** (le signal le plus fort de `service_down`) | oui |

### 6.5 Bordure (pare-feu / WAF)

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `edge_req_per_sec` | Requêtes reçues par le pare-feu (toutes, `/health` compris) | Exportateur du serveur en bordure | req/s | Haut = flot en entrée (signature du DDoS) | oui |
| `edge_connections` | Connexions actives en bordure | Exportateur du serveur en bordure | nombre | Haut = nombreuses connexions ouvertes | oui |
| `edge_conn_per_sec` | Nouvelles connexions TCP acceptées par seconde | Exportateur du serveur en bordure | conn/s | Haut = ouverture massive de connexions (scan) | oui |
| `waf_404_per_sec` | Réponses 404 vues par le pare-feu | Journaux du WAF, agrégés par l'agent de logs | req/s | Haut = sondage de chemins inexistants (reconnaissance) | oui |
| `waf_blocked_per_sec` | Requêtes bloquées (403) par le pare-feu | Journaux du WAF, agrégés par l'agent de logs | req/s | Haut = attaques web arrêtées en bordure (injection SQL) | oui |

### 6.6 Ressources

| KPI | Mesure | Source | Unité | Haut / bas signifie | Détection |
|---|---|---|---|---|---|
| `api_cpu_cores` | CPU consommé par les services applicatifs | Métriques de processus des services | cœurs | Haut = charge de calcul (saturation, hachage) | oui |
| `api_mem_bytes` | Mémoire des services applicatifs | Métriques de processus des services | octets | Contexte ; dépend du poste | non (contexte) |
| `host_cpu_cores` | CPU de la machine virtuelle Docker entière | cAdvisor (cgroup racine) | cœurs | Contexte ; dépend du poste | non (contexte) |
| `host_mem_bytes` | Mémoire de la machine virtuelle Docker entière | cAdvisor (cgroup racine) | octets | Contexte ; dépend du poste | non (contexte) |

Note sur les sources : les compteurs 403/404 du pare-feu ne sont pas des métriques natives du
serveur ; ils sont **reconstruits à partir des journaux JSON** du WAF par l'agent de collecte de
logs, puis exposés comme métriques. Les mesures « machine entière » viennent de cAdvisor, car sous
Docker Desktop il ne peut pas fournir la consommation **par conteneur** ; c'est pourquoi on utilise
plutôt les métriques de processus des services, et pourquoi les mesures « machine » sont écartées de
la détection (elles ne se généralisent pas d'un poste à l'autre).

---

## 7. Signature de chaque attaque

Le tableau croisé ci-dessous résume **quels KPI bougent et dans quel sens** pour chaque état.
Légende : **↑↑** forte hausse · **↑** hausse · **↓** baisse · **0** passe à zéro · **—** peu ou pas
d'effet.

| KPI \ État | normal | ddos | brute_force | sql_injection | port_scan | service_down |
|---|---|---|---|---|---|---|
| `edge_req_per_sec` | ligne de base | **↑↑** | ↑ | ↑ | ↑ | — |
| `req_per_sec` (hors /health) | ligne de base | — | ↑ | — | ↑ | — |
| `inprogress` | bas | **↑** | — | — | — | — |
| `latency_p95_payment_seconds` | bas | **↑** | — | — | — | — (pas de trafic traité) |
| `latency_p95_login_seconds` | bas | — | **↑** | — | — | — |
| `login_fail_per_sec` | ~0 (fautes de frappe) | — | **↑↑** | — | — | — |
| `waf_blocked_per_sec` | ~0 | — | — | **↑↑** | — | — |
| `waf_404_per_sec` | ~0 | — | — | — | **↑↑** | — |
| `edge_conn_per_sec` | bas | — | — | — | ↑ | — |
| `tx_ok_per_sec` | normal | **↓** | — | — | — | **0** |
| `db_errors_per_sec` | ~0 | — | — | — | — | **↑** |
| `err_5xx_per_sec` | ~0 | — | — | — | — | **↑** |
| `api_up` | 1 | 1 | 1 | 1 | 1 | **0** |
| `api_cpu_cores` | bas | ↑ | ↑ | — | — | — |

### Ce qui distingue chaque état

- **DDoS vs panne.** Les deux touchent la disponibilité et font chuter les virements. Mais le DDoS
  arrive **avec** un flot en bordure (`edge_req_per_sec` ↑↑) et l'API reste debout (`api_up` = 1),
  tandis que la panne est **silencieuse en entrée** mais fait tomber `api_up` à 0 et monter les
  erreurs de base.
- **Force brute vs trafic normal.** Le trafic normal contient quelques échecs de connexion (fautes
  de frappe). La force brute se reconnaît à un `login_fail_per_sec` **très au-dessus** de ce bruit,
  accompagné d'une latence de connexion qui s'allonge.
- **Injection SQL vs scan.** Les deux sont des attaques web vues en bordure, mais l'injection
  déclenche des **blocages 403** (`waf_blocked_per_sec`) alors que le scan produit des **404**
  (`waf_404_per_sec`). Ce sont deux compteurs distincts.
- **Injection SQL vs DDoS.** L'injection ne cherche pas à saturer : `inprogress`, latence et
  virements restent normaux. Seul le compteur de requêtes bloquées monte.

C'est bien la **combinaison** de ces signaux, et non un seul seuil, qui permet au modèle de séparer
les types — d'où le choix de l'apprentissage plutôt que de règles fixes (section 3).

---

## 8. La remédiation automatique

La remédiation reçoit le **verdict** de la détection (le type et la confiance) et exécute une action
**prédéfinie** selon la nature de l'incident. Le déroulé général est : **confiner → (selon la
nature) agir → vérifier → journaliser.**

### 8.1 La logique par type

| État | Nature | Action menée | Pourquoi celle-là |
|---|---|---|---|
| `service_down` | disponibilité | Redémarrage du conteneur en panne, par paliers (base puis API), puis vérification | Une panne se répare en relançant le service, mais seule une transaction réussie prouve la reprise |
| `ddos` | disponibilité | Arrêt de la source ; si le service reste dégradé, redémarrage de l'API, puis vérification | Couper l'origine du flot d'abord ; ne redémarrer que si nécessaire |
| `brute_force` | abus | Arrêt de la source ; vérification qu'un compte sain se connecte encore | Le verrouillage applicatif limite déjà l'attaque ; on confirme que le métier fonctionne |
| `port_scan` | reconnaissance | Arrêt de la source, surveillance ; pas de redémarrage | Peu dommageable ; on bloque et on observe |
| `sql_injection` | compromission | **Confinement seul** : arrêt de la source, alerte ; **jamais « résolu » automatiquement** | L'enjeu est l'intégrité, pas la disponibilité : un humain doit analyser |

### 8.2 Comment l'attaque est réellement stoppée (production vs laboratoire fermé)

Identifier **qui** attaque se fait à partir des **journaux** : on interroge l'agrégateur de logs pour
trouver, sur une courte fenêtre, l'adresse IP la plus active correspondant au type d'attaque
(beaucoup de 403 pour l'injection, beaucoup de 404 pour le scan, beaucoup d'échecs de connexion pour
la force brute, etc.).

- **En production.** L'adresse de l'attaquant est **ajoutée à la liste de blocage du pare-feu**, qui
  est rechargé à chaud. Ses requêtes suivantes sont rejetées en bordure (403). L'attaque est stoppée
  pour de vrai, sans toucher aux clients légitimes.
- **En laboratoire fermé.** L'attaque part de notre propre harnais, sur la machine ; son adresse est
  une **passerelle interne protégée**, qu'on ne doit jamais bloquer (sous peine de couper notre
  propre infrastructure). Dans ce cas, la remédiation **coupe l'attaque à sa source** en demandant à
  la console d'arrêter le profil d'attaque en cours. C'est pourquoi, en démonstration locale,
  l'attaque **s'arrête réellement** après la détection, au lieu de tourner dans le vide.

Cette double logique est un choix assumé : le mécanisme « réel » (blocage d'IP en bordure) reste en
place et fonctionne depuis un vrai poste attaquant ; le repli « laboratoire » rend la démonstration
visible sur une seule machine, sans prétendre bloquer une adresse qu'on a de toute façon le devoir
de protéger.

### 8.3 La vérification de la reprise (le point crucial)

Un conteneur qui redémarre ne **prouve** rien. La remédiation n'accepte de déclarer un incident
résolu que si **deux conditions** sont réunies, avec plusieurs ré-essais :

1. **Sonde de santé.** Les points `/health` de l'authentification **et** du paiement répondent
   correctement.
2. **Transaction de test.** Un compte technique dédié (« probe ») se connecte, puis effectue un
   **vrai virement de 0,01 €** vers un compte de collecte. La reprise n'est validée que si ce
   virement **aboutit** réellement.

C'est cette transaction de bout en bout qui fait la différence entre « le service répond » et « le
service fonctionne ». Tant qu'elle échoue, l'incident reste ouvert et une intervention humaine est
réclamée.

### 8.4 Les garde-fous

La remédiation est conçue pour ne **jamais devenir elle-même une faille** :

- **Droits minimaux.** Elle ne fait que des actions prédéfinies sur des cibles connues : bloquer une
  adresse **validée** et hors liste protégée, ou redémarrer un service appartenant à une **liste
  blanche**. Aucune commande arbitraire n'est possible.
- **Liste « jamais bloquée ».** La boucle locale, les passerelles internes et l'hôte ne peuvent
  jamais être bloqués : la défense ne peut pas se couper elle-même.
- **Idempotence.** Bloquer une adresse déjà bloquée ne fait rien ; un service déjà sain n'est pas
  redémarré. Rejouer une action est sans effet de bord.
- **Anti-rebond et délai de repos.** On n'agit qu'après plusieurs détections consécutives du même
  type (pour ne pas réagir à un pic isolé), et pas deux fois de suite dans un court délai (pour
  éviter les boucles d'action).
- **Confiance minimale.** En dessous d'un seuil de confiance du verdict, on n'agit pas.
- **Confinement de l'injection SQL sans résolution automatique.** Une compromission est confinée
  (source coupée, alerte, journaux conservés) mais **jamais** déclarée « résolue » par la machine :
  l'intégrité des données relève d'une analyse humaine.
- **Journalisation.** Chaque étape (détection → confinement → redémarrage éventuel → vérification →
  clôture) est tracée, avec son horodatage et son résultat. Le tableau de bord l'affiche en direct.

### 8.5 Le déclenchement

La remédiation peut se déclencher de deux façons, avec la **même** logique et les mêmes garde-fous :

- **Automatique** : une boucle interroge la détection en continu et agit dès qu'une attaque est
  confirmée (reprise autonome complète).
- **Sur action de l'opérateur** : le tableau de bord propose, dès qu'une attaque est détectée, un
  bouton pour déclencher le script de remédiation, et affiche ensuite la neutralisation et le retour
  du trafic à la normale. Cela correspond à une supervision « humain dans la boucle » : la machine
  propose, l'opérateur confirme d'un clic, le script fait le reste et prouve la reprise.

---

## 9. Garanties de sécurité — pourquoi la défense n'est pas une faille

- **Données entièrement fictives.** Aucun client, aucune somme réelle. Aucun secret en clair dans le
  dépôt : les mots de passe et clés sont des fichiers séparés, non versionnés.
- **Pare-feu en mode blocage.** Les attaques web (dont l'injection SQL) sont arrêtées en bordure par
  les règles OWASP. L'audit du pare-feu est configuré **sans** corps de requête ni en-têtes : aucun
  mot de passe ni jeton ne se retrouve dans les journaux.
- **Pas d'usurpation par en-tête.** L'adresse du client utilisée par la plateforme vient **du
  pare-feu seul**, pas d'un en-tête que l'attaquant pourrait falsifier.
- **Conteneurs durcis.** Exécution sans privilèges, système de fichiers en lecture seule, capacités
  système retirées, interdiction d'élever ses droits. Réseaux internes cloisonnés : seul le pare-feu
  est exposé ; l'observabilité et la base ne sont pas publiées hors de la machine.
- **Accès Docker en lecture seule** pour l'agent d'observation : il passe par un intermédiaire qui
  interdit toute écriture, jamais par l'accès direct.
- **Rôles de base de données séparés.** Chaque service a le **strict nécessaire** : le service de
  paiement ne peut ni lire la table des utilisateurs, ni supprimer une transaction.
- **Mots de passe à hachage borné en mémoire** : une rafale de connexions ne fait pas tomber le
  service d'authentification.
- **Remédiation à droits minimaux** (voir 8.4) : actions prédéfinies seulement, cibles validées,
  rien d'arbitraire.
- **Attaques strictement locales.** Le harnais d'attaque refuse toute cible hors du réseau fermé de
  l'équipe : la boucle locale est permise, une adresse publique est **toujours** refusée, et joindre
  un autre poste exige une autorisation explicite. Les attaques ne quittent jamais le réseau d'équipe.

---

## 10. Limites connues et pistes d'amélioration

### Limites

- **Qualité de la détection liée au jeu de données.** Le modèle ne reconnaît que ce qu'il a observé.
  S'il a été entraîné sur des attaques d'une certaine intensité et qu'on joue ensuite des attaques
  plus douces (ou l'inverse), les verdicts deviennent imprécis. Une collecte suivie d'un
  ré-apprentissage avec les profils d'attaque **actuels** est nécessaire pour fiabiliser la détection
  réseau. La reprise sur **panne** (`service_down`), elle, ne dépend pas de l'intensité : elle repose
  sur un signal franc (disponibilité à 0).
- **Machine à deux cœurs.** C'est le nombre de connexions simultanées qui sature la machine virtuelle
  Docker, pas le débit. Les attaques sont donc volontairement **modérées** : on cherche la signature,
  pas l'effondrement. Cela limite l'ampleur des démonstrations de DDoS.
- **Mesure par conteneur indisponible** sous Docker Desktop (stockage d'images containerd) : on se
  rabat sur les métriques de processus des services, et on écarte les mesures « machine entière » de
  la détection.
- **Délai de détection.** Les KPI étant moyennés sur 30 secondes, il faut une demi-minute environ
  pour que la signature d'une attaque monte et que le verdict bascule.
- **Dépendance au modèle de langage local** pour l'explication : sans lui, la détection et la
  remédiation fonctionnent toujours, mais l'analyse en langage naturel est absente (un message clair
  le signale).

### Pistes d'amélioration

- **Collectes régulières et nombreux épisodes** pour améliorer la généralisation et mesurer la
  précision par type d'attaque (matrice de confusion).
- **Enrichir la base de connaissance** du RAG (procédures, cas limites) pour des explications plus
  fines.
- **Signaux supplémentaires** : variété des adresses sources, profils temporels, pour mieux séparer
  un afflux légitime d'un DDoS.
- **Passage à l'échelle** au-delà de deux cœurs pour des démonstrations d'attaques plus intenses et
  un blocage d'IP externe grandeur nature.
- **Durcissement de la chaîne de remédiation** : en production, passer par un intermédiaire Docker
  n'autorisant que l'action « redémarrer », pour réduire encore la surface de droits.

---

*Fin du document. Les trois rôles — la détection décide, l'assistant explique, la remédiation agit
et vérifie — restent la clé de lecture de tout le système.*
