# The Local Studio — frontend container (static site + API reverse proxy).
#
# nginx serves the landing page, the studio and the preset previews, and proxies
# /api/ and /health to the backend container over the internal network. The
# backend has no host port, so this proxy is the only way to reach the API.

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

COPY index.html studio.html script.js /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
COPY icons/ /usr/share/nginx/html/icons/
COPY previews/ /usr/share/nginx/html/previews/

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
