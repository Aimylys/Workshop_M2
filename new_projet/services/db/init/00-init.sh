#!/bin/sh
# Exécuté UNE SEULE FOIS par l'image postgres, au premier démarrage (volume vide).
# Les mots de passe des rôles applicatifs sont lus dans les secrets Docker, jamais en clair ici.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" \
  -v auth_pw="$(cat /run/secrets/auth_db_password)" \
  -v pay_pw="$(cat /run/secrets/payment_db_password)" \
  -f /docker-entrypoint-initdb.d/sql/schema.sql
