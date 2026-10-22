# WAF : Nginx + ModSecurity + OWASP Core Rule Set, seul point d'entrée de la plateforme.
FROM owasp/modsecurity-crs:4.29.0-nginx-alpine-202609301109

# Journal d'accès JSON sur stdout (collecté par Alloy -> Loki, exploité par le SIEM et la détection)
COPY logging.conf.template /etc/nginx/templates/conf.d/logging.conf.template

# Règles maison, via le mécanisme standard du CRS : rules/*.conf est inclus par ordre
# alphabétique, donc REQUEST-900 passe avant le CRS et RESPONSE-999 après lui.
# (L'image annonce /opt/modsecurity/rules/{before,after}-crs mais ne l'inclut pas.)
COPY rules/before-crs.conf /etc/modsecurity.d/owasp-crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf
COPY rules/after-crs.conf  /etc/modsecurity.d/owasp-crs/rules/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf

USER root
# Liste de blocage : fichier dans un volume partagé avec la remédiation (phase 7).
# Le WAF la relit au rechargement de nginx (signal HUP).
RUN mkdir -p /etc/modsecurity.d/blocklist \
 && printf '# IP bloquées par la remédiation automatique (une par ligne)\n192.0.2.255\n' \
      > /etc/modsecurity.d/blocklist/blocked_ips.txt \
 && chown -R nginx:nginx /etc/modsecurity.d/blocklist
USER nginx
