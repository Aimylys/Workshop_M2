"""Remédiation automatique (Zero-Touch Recovery).

Reçoit le verdict de la détection et exécute une action CORRECTIVE prédéfinie selon le type
d'attaque, puis VÉRIFIE la reprise (sonde /health + transaction de test réussie) et journalise
tout. Droits minimaux : uniquement des actions prédéfinies sur des cibles connues (liste de
blocage du WAF, redémarrage de services d'une liste blanche) — jamais de commande arbitraire.

La détection DÉCIDE, la remédiation AGIT, l'assistant RAG EXPLIQUE : trois rôles séparés.
"""
