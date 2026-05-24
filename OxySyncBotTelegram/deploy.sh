#!/bin/bash
# Запускать из папки OxySyncBotTelegram/
# Использование: bash deploy.sh
# Требует: OpenSSH (есть в Windows 11 по умолчанию), Git Bash или WSL

SERVER="${1:-root@138.124.18.150}"
REMOTE="/opt/oxysync-bot"

set -e

echo "[1/4] Подготовка сервера..."
ssh "$SERVER" bash <<'ENDSSH'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3.11 python3.11-venv python3-pip -qq
id oxysync 2>/dev/null || useradd -r -s /bin/false oxysync
mkdir -p /opt/oxysync-bot
ENDSSH

echo "[2/4] Копирование файлов..."
scp api.py bot.py config.py db.py main.py requirements.txt oxysync-bot.service \
    "$SERVER:/opt/oxysync-bot/"

echo "[3/4] Установка зависимостей и регистрация сервиса..."
ssh "$SERVER" bash <<'ENDSSH'
set -e
cd /opt/oxysync-bot
python3.11 -m venv venv
venv/bin/pip install -q -r requirements.txt
cp oxysync-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable oxysync-bot
chown -R oxysync:oxysync /opt/oxysync-bot
ENDSSH

echo ""
echo "=============================="
echo " ГОТОВО. Осталось два шага:"
echo "=============================="
echo ""
echo "1. Создайте .env на сервере:"
echo "   ssh $SERVER"
echo "   nano /opt/oxysync-bot/.env"
echo "   (содержимое — см. .env.example)"
echo ""
echo "2. Запустите бота:"
echo "   ssh $SERVER 'chown oxysync:oxysync /opt/oxysync-bot/.env && systemctl start oxysync-bot && systemctl status oxysync-bot'"
echo ""
echo "Логи в реальном времени:"
echo "   ssh $SERVER 'journalctl -u oxysync-bot -f'"
echo "=============================="
