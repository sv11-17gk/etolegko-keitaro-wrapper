#!/usr/bin/env bash
set -euo pipefail

cd /srv/apps/etolegko-keitaro
exec 9>/run/lock/etolegko-keitaro.lock
flock -n 9 || exit 0

git fetch origin main
current_commit=$(git rev-parse HEAD)
remote_commit=$(git rev-parse origin/main)
deployment_commit=$(cat /var/lib/etolegko-keitaro/deployed-commit 2>/dev/null || true)
if [[ "$current_commit" == "$remote_commit" && "$deployment_commit" == "$remote_commit" ]]; then
    exit 0
fi

git merge --ff-only origin/main
docker compose -f docker-compose.public.yml up -d --build --wait --wait-timeout 120
curl --fail --silent --show-error http://127.0.0.1:18081/openapi.json >/dev/null
install -d /var/lib/etolegko-keitaro
printf '%s\n' "$remote_commit" > /var/lib/etolegko-keitaro/deployed-commit
