#!/data/data/com.termux/files/usr/bin/bash
# Запускать в Termux на своём Android устройстве.
# Собирает нативный ARM64 бинарник совместимый с Bionic libc.

set -e

REPO="JUSTANAX/OxySyncTermux"
SCRIPT="roblox_keeper.py"

echo ""
echo "  OxySync — сборка Android бинарника"
echo ""

# Зависимости
echo "  [1/4] Установка компилятора..."
pkg install -y python clang binutils 2>/dev/null

echo "  [2/4] Установка Nuitka..."
pip install nuitka zstandard requests -q

# Качаем актуальный исходник
echo "  [3/4] Загрузка исходника..."
curl -fsSL "https://raw.githubusercontent.com/$REPO/main/$SCRIPT" -o "$SCRIPT"

echo "  [4/4] Компиляция (~5-15 минут)..."
python -m nuitka \
  --onefile \
  --output-filename=oxysync-android \
  --include-package=requests \
  --assume-yes-for-downloads \
  --no-progressbar \
  "$SCRIPT"

rm -f "$SCRIPT"

echo ""
echo "  ✓ Готово: oxysync-android"
echo ""
echo "  Теперь загрузи файл в GitHub Releases вручную:"
echo "  https://github.com/$REPO/releases/tag/latest"
echo ""
echo "  Или через gh cli:"
echo "  gh release upload latest oxysync-android --repo $REPO --clobber"
echo ""
