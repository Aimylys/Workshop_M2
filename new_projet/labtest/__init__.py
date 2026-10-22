"""Harnais de test de résilience — USAGE STRICTEMENT LOCAL.

Génère, contre LES PROPRES CONTENEURS de la plateforme (démonstrateur fictif, 127.0.0.1),
les profils de charge qui produisent les signatures KPI de chaque état. Sert à alimenter la
détection : sans ces signatures, il n'y a rien à détecter.

Toutes les cibles passent par guard.ensure_local() : le harnais REFUSE toute adresse hors
boucle locale ou hors réseau du laboratoire (192.168.137.x). Il ne contient aucun outil
offensif généraliste et ne vise aucun système tiers.
"""
