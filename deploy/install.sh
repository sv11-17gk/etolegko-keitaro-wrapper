#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo 'Запустите установку через sudo.' >&2
    exit 1
fi
for program in git docker nginx certbot curl systemctl flock; do
    command -v "$program" >/dev/null || { echo "Нужна программа $program" >&2; exit 1; }
done
docker compose version >/dev/null

checkout=/srv/apps/etolegko-keitaro
site=/etc/nginx/sites-available/etolegko-keitaro.conf
if [[ -e "$site" ]] && ! grep -q '^# Managed by etolegko-keitaro$' "$site"; then
    echo "Конфигурация $site уже существует и управляется отдельно." >&2
    exit 1
fi
if [[ ! -e "$site" ]] && nginx -T 2>/dev/null | grep -E 'server_name[^;]*etolegko\.porfiry\.ru' >/dev/null; then
    echo 'Домен уже настроен в другом конфиге Nginx. Нужна сверка конфигурации.' >&2
    exit 1
fi
if [[ ! -d "$checkout/.git" ]]; then
    install -d /srv/apps
    git clone --branch main https://github.com/sv11-17gk/etolegko-keitaro-wrapper.git "$checkout"
fi
cd "$checkout"
if [[ "$(git remote get-url origin)" != 'https://github.com/sv11-17gk/etolegko-keitaro-wrapper.git' ]]; then
    echo 'Каталог установки связан с другим репозиторием.' >&2
    exit 1
fi
git pull --ff-only origin main
docker compose -f docker-compose.public.yml up -d --build --wait --wait-timeout 120

install -d /var/www/certbot /etc/nginx/sites-available /etc/nginx/sites-enabled
if [[ ! -f /etc/letsencrypt/live/etolegko.porfiry.ru/fullchain.pem ]]; then
    install -m 644 deploy/etolegko-http.conf "$site"
    ln -sfn "$site" /etc/nginx/sites-enabled/etolegko-keitaro.conf
    nginx -t
    systemctl reload nginx
    echo 'Внешний прокси перехватывает HTTP-01. Сертификат подтверждается через DNS.'
    echo 'Certbot покажет TXT-запись _acme-challenge.etolegko.porfiry.ru.'
    echo 'Добавьте её в DNS-зону porfiry.ru и дождитесь распространения, затем нажмите Enter.'
    certbot certonly --manual --preferred-challenges dns \
        --cert-name etolegko.porfiry.ru -d etolegko.porfiry.ru \
        --agree-tos --register-unsafely-without-email
fi
install -m 644 deploy/etolegko.conf "$site"
ln -sfn "$site" /etc/nginx/sites-enabled/etolegko-keitaro.conf
nginx -t
systemctl reload nginx

install -m 644 deploy/etolegko-update.service /etc/systemd/system/
install -m 644 deploy/etolegko-update.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now etolegko-update.timer
install -d /var/lib/etolegko-keitaro
git rev-parse HEAD > /var/lib/etolegko-keitaro/deployed-commit
curl --fail --silent --show-error https://etolegko.porfiry.ru/ >/dev/null
echo 'Демо доступно на https://etolegko.porfiry.ru/'
