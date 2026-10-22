"""Console de démonstration (locale, 127.0.0.1) : deux interfaces.

  /          dashboard SOC : trafic en direct, verdict (attaque ou normal), explication RAG,
             remédiation recommandée.
  /attacker  console attaquant : lance/arrête les profils d'attaque LOCAUX (labtest).

Sépare clairement les deux rôles du sujet : le PC Attaquant (console attaquant) et la supervision
défensive (dashboard). La console n'est publiée que sur la boucle locale.
"""
