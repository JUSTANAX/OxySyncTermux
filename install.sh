#!/data/data/com.termux/files/usr/bin/bash

REPO="JUSTANAX/OxySyncTermux"
BIN_PATH="$PREFIX/bin/oxysync"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║    OxySync — Установка           ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── Определяем какой бинарник качать ─────────────────────────────────────────
if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
    BIN_NAME="oxysync-android"
    IS_TERMUX=1
else
    BIN_NAME="oxysync-linux"
    IS_TERMUX=0
fi

BIN_URL="https://github.com/$REPO/releases/latest/download/$BIN_NAME"

# ── curl ─────────────────────────────────────────────────────────────────────
if ! command -v curl &>/dev/null; then
    echo "  Устанавливаю curl..."
    pkg install curl -y -q 2>/dev/null
fi

# ── Скачиваем ─────────────────────────────────────────────────────────────────
echo "  Скачиваю OxySync..."
if curl -fL "$BIN_URL" -o "$BIN_PATH" --progress-bar 2>/dev/null; then
    chmod 700 "$BIN_PATH"
    echo ""
    echo "  ✓ Установка завершена!"
    echo "  Запускай командой: oxysync"
    echo ""
    echo "  Запускаю OxySync..."
    echo ""
    exec oxysync "$@" < /dev/tty
else
    # ── Фолбэк: Python если бинарник ещё не собран ───────────────────────────
    echo "  Бинарник не найден, использую Python..."
    echo ""

    pkg install python curl -y -q 2>/dev/null
    pip install requests -q

    INSTALL_DIR="$HOME/.oxysync"
    LAUNCHER="$INSTALL_DIR/run.py"
    mkdir -p "$INSTALL_DIR"
    chmod 700 "$INSTALL_DIR"

    cat > "$LAUNCHER" << 'PYEOF'
import requests, sys, base64

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

    cat > "$BIN_PATH" << SHEOF
#!/data/data/com.termux/files/usr/bin/bash
exec python $LAUNCHER "\$@"
SHEOF
    chmod 700 "$BIN_PATH"

    echo "  ✓ Установка завершена (Python режим)!"
    echo ""
    python "$LAUNCHER" "$@" < /dev/tty
fi
