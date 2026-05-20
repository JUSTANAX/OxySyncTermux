#!/data/data/com.termux/files/usr/bin/bash

# ─── OxySync Installer ──────────────────────────────────────────────────────
INSTALL_DIR="$HOME/.oxysync"
LAUNCHER="$INSTALL_DIR/run.py"
TOKEN_FILE="$INSTALL_DIR/.token"
CONFIG_FILE="$INSTALL_DIR/.cfg"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║    OxySync — Установка           ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── Зависимости ─────────────────────────────────────────────────────────────
echo "  [1/4] Установка системных пакетов..."
pkg install python curl aapt -y -q 2>/dev/null

if ! command -v python &>/dev/null; then
    echo "  Ошибка: Python не установился. Попробуй: pkg install python"
    exit 1
fi

echo "  [2/4] Установка Python библиотек..."
REQ_URL="https://raw.githubusercontent.com/JUSTANAX/OxySyncTermux/main/requirements.txt"
TMP_REQ="/tmp/oxysync_requirements.txt"

curl -sSL "$REQ_URL" -o "$TMP_REQ" 2>/dev/null || {
    echo "  Не удалось скачать requirements.txt, ставлю базовые пакеты..."
    echo "requests>=2.28.0,<3.0.0" > "$TMP_REQ"
}

pip install -r "$TMP_REQ" -q
if [ $? -ne 0 ]; then
    echo "  Ошибка: не удалось установить библиотеки."
    echo "  Попробуй вручную: pip install requests"
    exit 1
fi
rm -f "$TMP_REQ"

# ── Данные репозитория ───────────────────────────────────────────────────────
echo ""
echo "  [3/4] Настройка репозитория"
echo ""
read -p "  GitHub пользователь : " GH_USER
read -p "  Название репозитория: " GH_REPO
read -p "  Ветка (Enter = main) : " GH_BRANCH
GH_BRANCH="${GH_BRANCH:-main}"
read -p "  Файл скрипта (Enter = roblox_keeper.py): " GH_FILE
GH_FILE="${GH_FILE:-roblox_keeper.py}"
echo ""
read -s -p "  GitHub Token (ввод скрыт): " GH_TOKEN
echo ""

if [ -z "$GH_TOKEN" ]; then
    echo "  Токен не введён. Выход."
    exit 1
fi

# ── Скрытая папка ────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR"

# Кодируем токен в base64 и сохраняем
echo "$GH_TOKEN" | base64 > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

# Сохраняем конфиг репо (не секретный)
cat > "$CONFIG_FILE" << EOF
GH_USER=$GH_USER
GH_REPO=$GH_REPO
GH_BRANCH=$GH_BRANCH
GH_FILE=$GH_FILE
EOF
chmod 600 "$CONFIG_FILE"

# ── Лаунчер ──────────────────────────────────────────────────────────────────
cat > "$LAUNCHER" << 'PYEOF'
import sys
import os

# Проверка зависимостей перед запуском
def check_deps():
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    if missing:
        print(f"  Отсутствуют библиотеки: {', '.join(missing)}")
        print(f"  Запусти: pip install {' '.join(missing)}")
        sys.exit(1)

check_deps()

import requests
import base64

INSTALL_DIR = os.path.expanduser("~/.oxysync")
TOKEN_FILE  = os.path.join(INSTALL_DIR, ".token")
CONFIG_FILE = os.path.join(INSTALL_DIR, ".cfg")


def load_config() -> dict:
    cfg = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def load_token() -> str:
    with open(TOKEN_FILE) as f:
        return base64.b64decode(f.read().strip()).decode().strip()


def fetch_script(cfg: dict, token: str) -> str:
    url = (
        f"https://api.github.com/repos/{cfg['GH_USER']}/{cfg['GH_REPO']}"
        f"/contents/{cfg['GH_FILE']}?ref={cfg['GH_BRANCH']}"
    )
    r = requests.get(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3.raw",
        },
        timeout=15,
    )
    if r.status_code == 401:
        print("  Ошибка: токен недействителен или истёк.")
        sys.exit(1)
    if r.status_code == 404:
        print("  Ошибка: репозиторий или файл не найден.")
        sys.exit(1)
    r.raise_for_status()
    return r.text


try:
    cfg    = load_config()
    token  = load_token()
    code   = fetch_script(cfg, token)
    exec(compile(code, "<oxysync>", "exec"), {"__name__": "__main__"})
except FileNotFoundError:
    print("  OxySync не установлен. Запусти установщик заново.")
    sys.exit(1)
except requests.exceptions.ConnectionError:
    print("  Нет интернета. Проверь соединение.")
    sys.exit(1)
except Exception as e:
    print(f"  Ошибка: {e}")
    sys.exit(1)
PYEOF

chmod 600 "$LAUNCHER"

# ── Алиас ────────────────────────────────────────────────────────────────────
echo "  [4/4] Регистрация команды oxysync..."

SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

grep -v "alias oxysync=" "$SHELL_RC" > "$SHELL_RC.tmp" 2>/dev/null && mv "$SHELL_RC.tmp" "$SHELL_RC"
echo "alias oxysync='python $LAUNCHER'" >> "$SHELL_RC"

# Очищаем переменные из памяти
unset GH_TOKEN

echo ""
echo "  ✓ Установка завершена!"
echo ""
echo "  Перезапусти Termux или выполни:"
echo "    source $SHELL_RC"
echo ""
echo "  Затем запускай: oxysync"
echo ""
