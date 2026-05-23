#!/data/data/com.termux/files/usr/bin/bash

# ─── OxySync Installer ──────────────────────────────────────────────────────
INSTALL_DIR="$HOME/.oxysync"
LAUNCHER="$INSTALL_DIR/run.py"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║    OxySync — Установка           ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── 1. Обновление пакетов ────────────────────────────────────────────────────
echo "  [1/4] Обновление пакетов Termux..."
pkg update -y -q 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  Не удалось обновить пакеты, пробую продолжить..."
fi

# ── 2. Системные пакеты ──────────────────────────────────────────────────────
echo "  [2/4] Установка Python, curl, aapt..."
echo "        (может занять 2-5 минут — подожди)"
pkg install python curl aapt -y -q 2>/dev/null

if ! command -v python &>/dev/null; then
    echo ""
    echo "  Ошибка: Python не установился."
    echo "  Попробуй сменить зеркало: termux-change-repo"
    echo "  Затем запусти установку заново."
    exit 1
fi

# ── 3. Python библиотеки ─────────────────────────────────────────────────────
echo "  [3/4] Установка библиотек Python..."
pip install requests -q
if [ $? -ne 0 ]; then
    echo "  Ошибка: не удалось установить библиотеки."
    echo "  Попробуй вручную: pip install requests"
    exit 1
fi

# ── 4. Лаунчер ───────────────────────────────────────────────────────────────
echo "  [4/4] Установка OxySync..."
mkdir -p "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR"

cat > "$LAUNCHER" << 'PYEOF'
import requests, sys, base64, json

API_URL = "https://api.github.com/repos/JUSTANAX/OxySyncTermux/contents/roblox_keeper.py"

try:
    r = requests.get(API_URL, headers={"Accept": "application/vnd.github.v3+json"}, timeout=15)
    r.raise_for_status()
    code = base64.b64decode(r.json()["content"]).decode()
    exec(compile(code, "<oxysync>", "exec"), {"__name__": "__main__"})
except requests.exceptions.ConnectionError:
    print("  Нет интернета. Проверь соединение.")
    sys.exit(1)
except Exception as e:
    print(f"  Ошибка запуска: {e}")
    sys.exit(1)
PYEOF

chmod 600 "$LAUNCHER"

# ── Команда oxysync ──────────────────────────────────────────────────────────
BIN_PATH="$PREFIX/bin/oxysync"
cat > "$BIN_PATH" << SHEOF
#!/data/data/com.termux/files/usr/bin/bash
exec python $LAUNCHER "\$@"
SHEOF
chmod 700 "$BIN_PATH"

echo ""
echo "  ✓ Установка завершена!"
echo "  Теперь ты можешь запускать OxySync командой: oxysync"
echo ""
echo "  Запускаю OxySync..."
echo ""

python "$LAUNCHER" "$@" < /dev/tty
