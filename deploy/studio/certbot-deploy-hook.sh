#!/bin/sh
# Host-owned Certbot deploy hook; install separately from application CD.
set -eu

[ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/studio.cloud-nodes.net ] || exit 0

/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
