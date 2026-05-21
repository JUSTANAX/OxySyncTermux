#!/data/data/com.termux/files/usr/bin/bash

# ─── OxySync Installer ──────────────────────────────────────────────────────
INSTALL_DIR="$HOME/.oxysync"
LAUNCHER="$INSTALL_DIR/run.py"
SCRIPT_URL="https://raw.githubusercontent.com/JUSTANAX/OxySyncTermux/main/roblox_keeper.py"
REQ_URL="https://raw.githubusercontent.com/JUSTANAX/OxySyncTermux/main/requirements.txt"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║    OxySync — Установка           ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── 1. Системные пакеты ──────────────────────────────────────────────────────
echo "  [1/3] Установка пакетов..."
pkg install python curl aapt -y -q 2>/dev/null

if ! command -v python &>/dev/null; then
    echo "  Ошибка: Python не установился. Попробуй: pkg install python"
    exit 1
fi

# ── 2. Python библиотеки ─────────────────────────────────────────────────────
echo "  [2/3] Установка библиотек..."
pip install requests -q
if [ $? -ne 0 ]; then
    echo "  Ошибка: не удалось установить библиотеки."
    echo "  Попробуй вручную: pip install requests"
    exit 1
fi

# ── 3. Лаунчер ───────────────────────────────────────────────────────────────
echo "  [3/3] Установка OxySync..."
mkdir -p "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR"

cat > "$LAUNCHER" << PYEOF
import requests, sys

import time
URL = "$SCRIPT_URL"

try:
    r = requests.get(URL, params={"_": int(time.time())}, timeout=15)
    r.raise_for_status()
    exec(compile(r.text, "<oxysync>", "exec"), {"__name__": "__main__"})
except requests.exceptions.ConnectionError:
    print("  Нет интернета. Проверь соединение.")
    sys.exit(1)
except Exception as e:
    print(f"  Ошибка запуска: {e}")
    sys.exit(1)
PYEOF

chmod 600 "$LAUNCHER"

# ── Алиас ────────────────────────────────────────────────────────────────────
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
grep -v "alias oxysync=" "$SHELL_RC" > "$SHELL_RC.tmp" 2>/dev/null && mv "$SHELL_RC.tmp" "$SHELL_RC"
echo "alias oxysync='python $LAUNCHER'" >> "$SHELL_RC"

echo ""
echo "  Установка завершена. Запускаю OxySync..."
echo ""

python "$LAUNCHER"
