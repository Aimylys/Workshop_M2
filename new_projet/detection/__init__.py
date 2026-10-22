"""Détection d'attaque par similarité (k plus proches voisins sur les profils de KPI étiquetés).

Approche : on indexe les instantanés de KPI étiquetés collectés sur la plateforme, puis on
classe l'état courant par vote de ses k voisins les plus proches (distance euclidienne sur des
KPI standardisés). C'est de l'apprentissage par l'exemple — pas de réseau entraîné « from
scratch » : l'index EST le modèle. La détection DÉCIDE (et déclenchera la remédiation) ;
l'assistant RAG, lui, se contente d'EXPLIQUER le verdict.
"""
