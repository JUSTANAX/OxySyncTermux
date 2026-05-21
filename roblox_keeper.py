import requests
import time
import os
import sys
import json
import subprocess
import re

# ═══════════════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════════════

VERSION           = "1.9"

DATA_FILE         = "/sdcard/OxySync/data.json"
APK_DIR           = "/sdcard/OxySync/apks/"
HEARTBEAT_DIR     = "/sdcard/OxySync/"
HEARTBEAT_TIMEOUT = 90
PING_INTERVAL     = 60
MAX_SLOTS         = 8

EXECUTORS = {
    "1": {"name": "Delta",    "path": "/sdcard/Delta/autoexec/"},
    "2": {"name": "Vega X",   "path": "/sdcard/VegaX/autoexec/"},
    "3": {"name": "Codex",    "path": "/sdcard/Codex/autoexec/"},
    "4": {"name": "Arceus X", "path": "/sdcard/Arceus X/autoexec/"},
}

SOURCES = {
    "1": {"name": "VegaX", "type": "gdrive", "id": "1YmbcVrTzMUAmgj8-jO3GItxW5e_eodtx", "pattern": "Vegax{slot}.apk"},
}

DEFAULT_PACKAGES = {
    str(i): f"com.roblox.client{'' if i == 1 else i}"
    for i in range(1, MAX_SLOTS + 1)
}

LUA_TEMPLATE = """\
-- OxySync Slot {slot}
local Players         = game:GetService("Players")
local TeleportService = game:GetService("TeleportService")
local VirtualUser     = game:GetService("VirtualUser")

local player      = Players.LocalPlayer
local placeId     = game.PlaceId
local isRejoining = false

player.Idled:Connect(function()
    VirtualUser:Button2Down(Vector2.new(0, 0), workspace.CurrentCamera.CFrame)
    task.wait(1)
    VirtualUser:Button2Up(Vector2.new(0, 0), workspace.CurrentCamera.CFrame)
end)

player.OnTeleport:Connect(function(state)
    if state == Enum.TeleportState.Failed and not isRejoining then
        isRejoining = true
        task.wait(3)
        TeleportService:Teleport(placeId, player)
    end
end)

local function rejoin()
    if isRejoining then return end
    isRejoining = true
    task.wait(2)
    TeleportService:Teleport(placeId, player)
end

game.Close:Connect(rejoin)

task.spawn(function()
    while true do
        task.wait(20)
        if not game:IsLoaded() and not isRejoining then
            rejoin()
        end
    end
end)

task.spawn(function()
    while true do
        pcall(function()
            writefile("/sdcard/OxySync/hb_{slot}.txt", tostring(os.time()))
        end)
        task.wait(30)
    end
end)
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  Data
# ═══════════════════════════════════════════════════════════════════════════════

def load_data() -> dict:
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "drive_folder_id": "1YmbcVrTzMUAmgj8-jO3GItxW5e_eodtx",
            "executor": None,
            "packages": DEFAULT_PACKAGES.copy(),
            "accounts": {str(i): None for i in range(1, MAX_SLOTS + 1)},
        }

def save_data(data: dict):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ═══════════════════════════════════════════════════════════════════════════════
#  Roblox API
# ═══════════════════════════════════════════════════════════════════════════════

def make_session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
    s.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    return s

def get_csrf(session: requests.Session) -> str:
    r = session.post("https://auth.roblox.com/v2/logout")
    return r.headers.get("x-csrf-token", "")

def get_account_info(session: requests.Session) -> dict:
    r = session.get("https://users.roblox.com/v1/users/authenticated")
    return None if r.status_code == 401 else r.json()

def get_presence(session: requests.Session, user_id: int) -> dict:
    try:
        r = session.post(
            "https://presence.roblox.com/v1/presence/users",
            json={"userIds": [user_id]}
        )
        if r.status_code != 200:
            return {"status": "unknown", "game_name": None}
        p = r.json().get("userPresences", [{}])[0]
        status = {0: "offline", 1: "online", 2: "ingame", 3: "studio"}.get(
            p.get("userPresenceType", 0), "offline"
        )
        return {"status": status, "game_name": p.get("lastLocation")}
    except Exception:
        return {"status": "unknown", "game_name": None}

# ═══════════════════════════════════════════════════════════════════════════════
#  Google Drive
# ═══════════════════════════════════════════════════════════════════════════════

def parse_drive_folder_id(url: str) -> str | None:
    url = url.strip()
    m = re.search(r'/folders/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{25,}$', url):
        return url
    return None


def list_drive_folder(folder_id: str) -> dict:
    """Возвращает {filename: file_id} для файлов в публичной папке Google Drive."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        files = {}
        for m in re.finditer(r'id="entry-([a-zA-Z0-9_-]+)"', r.text):
            entry_id = m.group(1)
            segment  = r.text[m.start():m.start() + 2000]
            title_m  = re.search(r'class="flip-entry-title"[^>]*>([^<]+)<', segment)
            if title_m:
                files[title_m.group(1).strip()] = entry_id
        return files
    except Exception:
        return {}


def download_gdrive(file_id: str, dest: str, label: str) -> bool:
    try:
        s   = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        url = (
            f"https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t"
        )
        r = s.get(url, stream=True, timeout=120)
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}")
            return False
        total = int(r.headers.get("content-length", 0))
        done  = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    filled = int(done / total * 30)
                    bar    = "█" * filled + "░" * (30 - filled)
                    print(
                        f"\r    {label}: [{bar}] {done/1024/1024:.1f}/{total/1024/1024:.1f} MB",
                        end="", flush=True,
                    )
        print()
        return True
    except Exception as e:
        print(f"\n    Ошибка: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Gofile
# ═══════════════════════════════════════════════════════════════════════════════

def gofile_guest_token() -> str | None:
    for url, method in [
        ("https://api.gofile.io/accounts/getid", "get"),
        ("https://api.gofile.io/accounts",       "post"),
    ]:
        try:
            r = (requests.get if method == "get" else requests.post)(
                url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("status") == "ok":
                    return d["data"]["token"]
        except Exception:
            continue
    return None

def gofile_wt() -> str:
    """Получает актуальный websiteToken с сайта gofile."""
    UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    WT_PATTERNS = [
        r'"websiteToken"\s*:\s*"([a-zA-Z0-9]+)"',
        r'websiteToken\s*[=:]\s*["\']([a-zA-Z0-9]+)["\']',
        r'wt\s*[=:]\s*"([a-zA-Z0-9]{10,})"',
    ]
    try:
        html = requests.get("https://gofile.io/", headers={"User-Agent": UA}, timeout=15).text
        js_srcs = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
        for js_src in js_srcs[:10]:
            if not js_src.startswith("http"):
                js_src = "https://gofile.io" + (js_src if js_src.startswith("/") else "/" + js_src)
            try:
                js = requests.get(js_src, headers={"User-Agent": UA}, timeout=10).text
                for pat in WT_PATTERNS:
                    m = re.search(pat, js)
                    if m and len(m.group(1)) >= 8:
                        return m.group(1)
            except Exception:
                continue
    except Exception:
        pass
    return "4fd6sg89d7s6"

def list_gofile_folder(content_id: str) -> dict:
    """Возвращает {filename: (link, token)} для файлов в публичной папке gofile."""
    token = gofile_guest_token()
    if not token:
        print("    Не удалось получить токен Gofile")
        return {}
    wt = gofile_wt()
    try:
        r = requests.get(
            f"https://api.gofile.io/contents/{content_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Cookie": f"accountToken={token}",
                "User-Agent": "Mozilla/5.0",
            },
            params={"wt": wt},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"    Gofile API: HTTP {r.status_code} (wt={wt})")
            return {}
        d = r.json()
        if d.get("status") != "ok":
            return {}
        files = {}
        for child in d.get("data", {}).get("children", {}).values():
            if child.get("type") == "file":
                link = child.get("link") or child.get("directLink", "")
                if link:
                    files[child["name"]] = (link, token)
        return files
    except Exception as e:
        print(f"    Gofile exception: {e}")
        return {}

def download_gofile(link: str, token: str, dest: str, label: str) -> bool:
    try:
        r = requests.get(
            link,
            headers={"Cookie": f"accountToken={token}"},
            stream=True, timeout=120,
        )
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}")
            return False
        total = int(r.headers.get("content-length", 0))
        done  = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    filled = int(done / total * 30)
                    bar    = "█" * filled + "░" * (30 - filled)
                    print(
                        f"\r    {label}: [{bar}] {done/1024/1024:.1f}/{total/1024/1024:.1f} MB",
                        end="", flush=True,
                    )
        print()
        return True
    except Exception as e:
        print(f"\n    Ошибка: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  Android utilities
# ═══════════════════════════════════════════════════════════════════════════════

def get_apk_package(apk_path: str) -> str | None:
    try:
        r = subprocess.run(
            ["aapt", "dump", "badging", apk_path],
            capture_output=True, text=True
        )
        for line in r.stdout.splitlines():
            if line.startswith("package: name="):
                return line.split("'")[1]
    except Exception:
        pass
    return None


def is_package_installed(package: str) -> bool:
    r = subprocess.run(["pm", "list", "packages", package], capture_output=True, text=True)
    return package in r.stdout

def is_process_running(package: str) -> bool:
    r = subprocess.run(["pidof", package], capture_output=True, text=True)
    return bool(r.stdout.strip())

def parse_place_id(value: str) -> str | None:
    """Принимает ID, ссылку roblox.com или deep link — возвращает place ID."""
    value = value.strip()
    if value.isdigit():
        return value
    m = re.search(r'roblox\.com/games/(\d+)', value)
    if m:
        return m.group(1)
    m = re.search(r'placeId=(\d+)', value)
    if m:
        return m.group(1)
    return None


def launch_clone(package: str, place_id: str = None):
    if place_id:
        subprocess.run([
            "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", f"roblox://experiences/start?placeId={place_id}",
            "-p", package,
        ], capture_output=True)
    else:
        subprocess.run(
            ["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True
        )

def _su(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["su", "-c", cmd],
        capture_output=True, text=True, stdin=subprocess.DEVNULL
    )

def set_play_protect(enabled: bool):
    val = "1" if enabled else "0"
    _su(f"settings put global package_verifier_enable {val}")
    _su(f"settings put global verifier_verify_adb_installs {val}")

def install_apk_root(apk_path: str) -> bool:
    set_play_protect(False)
    try:
        r = _su(f"pm install -r \"{apk_path}\"")
        return "success" in r.stdout.lower()
    finally:
        set_play_protect(True)

def uninstall_root(package: str):
    _su(f"pm uninstall {package}")

def force_stop(package: str):
    _su(f"am force-stop {package}")

def is_heartbeat_alive(slot: int) -> bool:
    try:
        with open(f"{HEARTBEAT_DIR}hb_{slot}.txt") as f:
            return (time.time() - int(f.read().strip())) < HEARTBEAT_TIMEOUT
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  Download
# ═══════════════════════════════════════════════════════════════════════════════

def download_apk(url: str, dest: str, label: str) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=60)
        if r.status_code != 200:
            print(f"    HTTP {r.status_code} — файл не найден")
            return False
        total = int(r.headers.get("content-length", 0))
        done  = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    filled = int(done / total * 30)
                    bar    = "█" * filled + "░" * (30 - filled)
                    print(
                        f"\r    {label}: [{bar}] {done/1024/1024:.1f}/{total/1024/1024:.1f} MB",
                        end="", flush=True
                    )
        print()
        return True
    except Exception as e:
        print(f"\n    Ошибка: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  Lua
# ═══════════════════════════════════════════════════════════════════════════════

def build_dispatcher(accounts: dict) -> str:
    """Генерирует единый Lua диспетчер для всех аккаунтов."""
    base = LUA_TEMPLATE.replace(
        "-- OxySync Slot {slot}", "-- OxySync Dispatcher"
    ).replace(
        'writefile("/sdcard/OxySync/hb_{slot}.txt"',
        'writefile("/sdcard/OxySync/hb_" .. (game:GetService("Players").LocalPlayer.Name) .. ".txt"'
    )
    # Убираем строку с {slot} из heartbeat
    lines = []
    for line in base.splitlines():
        if "{slot}" not in line:
            lines.append(line)
    base_clean = "\n".join(lines)

    # Блоки пользовательских скриптов
    dispatch_blocks = []
    for slot_str, acc in sorted(accounts.items()):
        if not acc:
            continue
        custom = acc.get("script", "").strip()
        if not custom:
            continue
        username = acc["username"]
        indented = "\n".join(f"    {l}" for l in custom.splitlines())
        dispatch_blocks.append(
            f'if username == "{username}" then\n{indented}\nend'
        )

    if not dispatch_blocks:
        return base_clean

    dispatch_section = (
        "\n-- Мульти-скрипты\n"
        "local username = game:GetService('Players').LocalPlayer.Name\n\n"
        + "\nel".join(dispatch_blocks)
    )

    return base_clean + dispatch_section


def write_lua(executor_path: str, accounts: dict):
    """Записывает единый диспетчер в autoexec."""
    os.makedirs(executor_path, exist_ok=True)
    with open(os.path.join(executor_path, "oxysync.lua"), "w") as f:
        f.write(build_dispatcher(accounts))

# ═══════════════════════════════════════════════════════════════════════════════
#  Display
# ═══════════════════════════════════════════════════════════════════════════════

CY = "\033[1;96m"
YL = "\033[1;93m"
GR = "\033[1;92m"
RS = "\033[0m"
DM = "\033[2m"

W = 34  # inner box width

def _top(title):
    fill = "─" * (W - 3 - len(title))
    print(f"  {CY}┌─ {title} {fill}┐{RS}")

def _row(num, label):
    pad = " " * (W - 5 - len(label))
    print(f"  {CY}│{RS}  {YL}{num}{RS}  {label}{pad}{CY}│{RS}")

def _bot():
    print(f"  {CY}└{'─' * W}┘{RS}")

def banner():
    title   = "OxySync — Roblox Keeper"
    ver     = f"v{VERSION}"
    pad_l   = (W - len(title)) // 2
    pad_r   = W - len(title) - pad_l
    ver_pad = W - len(ver) - 2
    print(f"\n{CY}  ╔{'═' * W}╗{RS}")
    print(f"{CY}  ║{RS}{' ' * pad_l}{GR}{title}{RS}{' ' * pad_r}{CY}║{RS}")
    print(f"{CY}  ║{RS}  {DM}{ver}{RS}{' ' * ver_pad}{CY}║{RS}")
    print(f"{CY}  ╚{'═' * W}╝{RS}\n")

def print_menu():
    _top("КЛОНЫ")
    _row("1", "Установить клоны")
    _row("2", "Обновить клоны")
    _bot()
    print()

    _top("АККАУНТЫ")
    _row("3", "Войти в аккаунт")
    _row("4", "Настройка аккаунтов")
    _bot()
    print()

    _top("ИГРА")
    _row("5", "Мульти-скрипты")
    _row("6", "Запустить игры")
    _bot()
    print()

    print(f"  {DM}0  Выход{RS}\n")

def status_label(status: str) -> str:
    return {"ingame": "В игре", "online": "Онлайн", "offline": "Офлайн", "studio": "Studio"}.get(status, status)

def print_status_card(slot: int, username: str, presence: dict):
    s  = status_label(presence["status"])
    g  = (presence["game_name"] or "—")[:24]
    u  = username[:24]
    print(f"  ┌─ Слот {slot} {'─' * 31}┐")
    print(f"  │  Никнейм : {u:<27}│")
    print(f"  │  Статус  : {s:<27}│")
    print(f"  │  Игра    : {g:<27}│")
    print(f"  └{'─' * 38}┘")

# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 1 & 4 — Install / Reinstall clones
# ═══════════════════════════════════════════════════════════════════════════════

def menu_install_clones(data: dict, reinstall: bool = False):
    title = "Обновление клонов" if reinstall else "Установка клонов"
    print(f"\n[ {title} ]\n")

    source = SOURCES["1"]

    # Executor
    if not data.get("executor"):
        print("  Выбери инжектор:")
        for k, v in EXECUTORS.items():
            print(f"    {k}. {v['name']}")
        ch = input("  Номер: ").strip()
        if ch in EXECUTORS:
            data["executor"] = EXECUTORS[ch]
            save_data(data)

    # Slots
    try:
        count = int(input(f"\n  Сколько клонов? (1-{MAX_SLOTS}): ").strip())
        count = max(1, min(count, MAX_SLOTS))
    except ValueError:
        count = 1

    packages = data.get("packages", DEFAULT_PACKAGES)

    # Получаем список файлов
    if source["type"] == "gdrive":
        print("  Получаю список файлов из Google Drive...", end=" ", flush=True)
        remote_files = {name: ("gdrive", fid) for name, fid in list_drive_folder(source["id"]).items()}
    else:
        print("  Получаю список файлов из Gofile...", end=" ", flush=True)
        remote_files = {name: ("gofile", link, token) for name, (link, token) in list_gofile_folder(source["id"]).items()}

    if remote_files:
        print(f"найдено {len(remote_files)} файл(ов)")
    else:
        print("не удалось получить список файлов\n")
        return
    print()

    for slot in range(1, count + 1):
        pkg      = packages.get(str(slot), DEFAULT_PACKAGES[str(slot)])
        apk_name = source["pattern"].format(slot=slot)
        apk_path = APK_DIR + apk_name

        if not reinstall and is_package_installed(pkg):
            print(f"  Слот {slot}: уже установлен, пропускаю.")
            continue

        if apk_name not in remote_files:
            print(f"  Слот {slot}: файл {apk_name} не найден, пропускаю.")
            continue

        print(f"  Слот {slot}:")
        entry = remote_files[apk_name]
        if entry[0] == "gdrive":
            ok = download_gdrive(entry[1], apk_path, "    Загрузка")
        else:
            ok = download_gofile(entry[1], entry[2], apk_path, "    Загрузка")

        if not ok:
            print(f"    Пропускаю слот {slot}.\n")
            continue

        # Определяем package name из APK
        print(f"    Package name...", end=" ", flush=True)
        detected = get_apk_package(apk_path)
        if detected:
            print(detected)
            packages[str(slot)] = detected
            pkg = detected
            data["packages"] = packages
        else:
            print(f"не удалось, использую: {pkg}")

        # uninstall только если package name сменился
        old_pkg = packages.get(str(slot))
        if reinstall and old_pkg and old_pkg != pkg and is_package_installed(old_pkg):
            print(f"    Package name изменился, удаляю старый...")
            uninstall_root(old_pkg)

        print(f"    Устанавливаю...", end=" ", flush=True)
        if install_apk_root(apk_path):
            print("Готово ✓ (сессия сохранена)")
            print(f"    Инициализация (12 сек)...", end=" ", flush=True)
            launch_clone(pkg)
            time.sleep(12)
            force_stop(pkg)
            print("✓")
        else:
            print("Ошибка установки!")

        save_data(data)

        if data.get("executor"):
            write_lua(data["executor"]["path"], data["accounts"])
        print()

    print("  Готово.\n")

# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 2 — Login
# ═══════════════════════════════════════════════════════════════════════════════

def installed_slots(data: dict) -> list[int]:
    packages = data.get("packages", DEFAULT_PACKAGES)
    return [i for i in range(1, MAX_SLOTS + 1) if is_package_installed(packages.get(str(i), DEFAULT_PACKAGES[str(i)]))]

def menu_login(data: dict):
    print("\n[ Вход в аккаунты ]\n")
    accounts = data.setdefault("accounts", {str(i): None for i in range(1, MAX_SLOTS + 1)})

    slots = installed_slots(data)
    if not slots:
        print("  Нет установленных клонов. Сначала установи клоны (пункт 1).\n")
        return

    print("  Установленные слоты:")
    for i in slots:
        acc = accounts.get(str(i))
        print(f"    Слот {i}: {acc['username'] if acc else '—'}")
    print()

    try:
        slot = int(input(f"  Слот ({slots[0]}-{slots[-1]}): ").strip())
        if slot not in slots:
            raise ValueError
    except ValueError:
        print("  Неверный слот.\n")
        return

    cookie = input(f"\n  Cookie для слота {slot}: ").strip()
    if cookie.startswith(".ROBLOSECURITY="):
        cookie = cookie.split("=", 1)[1]

    session = make_session(cookie)
    info    = get_account_info(session)
    if not info:
        print("  Неверный или просроченный cookie.\n")
        return

    username = info.get("name", "Unknown")
    user_id  = info.get("id", 0)
    accounts[str(slot)] = {"cookie": cookie, "username": username, "user_id": user_id}
    save_data(data)
    print(f"\n  Слот {slot} → {username} (ID: {user_id}) ✓\n")

# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 3 — Launch + Monitor
# ═══════════════════════════════════════════════════════════════════════════════

def menu_launch(data: dict):
    print("\n[ Запуск игр ]\n")
    accounts = data.get("accounts", {})
    packages = data.get("packages", DEFAULT_PACKAGES)
    executor = data.get("executor")

    active = {s: a for s, a in accounts.items() if a is not None}
    if not active:
        print("  Нет аккаунтов. Войди в аккаунты (пункт 2).\n")
        return

    # Генерируем диспетчер перед запуском
    if executor:
        write_lua(executor["path"], data["accounts"])

    sessions = {}
    for slot_str, acc in active.items():
        slot = int(slot_str)
        pkg  = packages.get(slot_str, DEFAULT_PACKAGES.get(slot_str, ""))

        place_id = acc.get("place_id")
        print(f"  Слот {slot} ({acc['username']}): запуск...", end=" ", flush=True)
        launch_clone(pkg, place_id)
        print("✓")

        s = make_session(acc["cookie"])
        try:
            s.headers.update({"X-CSRF-TOKEN": get_csrf(s)})
        except Exception:
            pass
        sessions[slot_str] = s

    print(f"\n  Ожидаю загрузку (25 сек)...")
    time.sleep(25)

    # Status cards
    print("\n" + "─" * 40)
    for slot_str, acc in active.items():
        presence = get_presence(sessions[slot_str], acc["user_id"])
        print_status_card(int(slot_str), acc["username"], presence)
    print("─" * 40)

    print(f"\n  Мониторинг запущен. Ctrl+C — стоп.\n")
    monitor_all(sessions, active, packages)

def monitor_all(sessions: dict, accounts: dict, packages: dict):
    offline_counts = {s: 0 for s in sessions}

    while True:
        ts = time.strftime("%H:%M:%S")
        for slot_str, session in sessions.items():
            acc  = accounts[slot_str]
            pkg  = packages.get(slot_str, DEFAULT_PACKAGES.get(slot_str, ""))
            slot = int(slot_str)
            name = acc["username"]

            try:
                # Краш процесса
                if not is_process_running(pkg):
                    print(f"[{ts}] Слот {slot} ({name}): краш — перезапускаю...")
                    launch_clone(pkg, acc.get("place_id"))
                    offline_counts[slot_str] = 0
                    continue

                # Heartbeat
                if not is_heartbeat_alive(slot):
                    print(f"[{ts}] Слот {slot} ({name}): heartbeat устарел")

                # Presence
                presence  = get_presence(session, acc["user_id"])
                status    = presence["status"]
                game_name = presence["game_name"] or "—"

                if status == "ingame":
                    print(f"[{ts}] Слот {slot} ({name}): В игре — {game_name} ✓")
                    offline_counts[slot_str] = 0
                elif status == "online":
                    print(f"[{ts}] Слот {slot} ({name}): Онлайн")
                    offline_counts[slot_str] = 0
                elif status == "offline":
                    offline_counts[slot_str] += 1
                    print(f"[{ts}] Слот {slot} ({name}): Офлайн ({offline_counts[slot_str]}/3)")
                    if offline_counts[slot_str] >= 3:
                        print(f"[{ts}] Слот {slot}: перезапускаю...")
                        launch_clone(pkg, acc.get("place_id"))
                        offline_counts[slot_str] = 0

            except requests.exceptions.ConnectionError:
                print(f"[{ts}] Нет интернета...")
            except Exception as e:
                if "403" in str(e) or "csrf" in str(e).lower():
                    try:
                        session.headers.update({"X-CSRF-TOKEN": get_csrf(session)})
                    except Exception:
                        pass

        time.sleep(PING_INTERVAL)

# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 3 — Account settings
# ═══════════════════════════════════════════════════════════════════════════════

def menu_account_settings(data: dict):
    print("\n[ Настройка аккаунтов ]\n")
    accounts = data.get("accounts", {})
    active   = {s: a for s, a in accounts.items() if a is not None}

    if not active:
        print("  Нет аккаунтов. Сначала войди в аккаунты (пункт 2).\n")
        return

    # Показываем текущие привязки
    print("  Привязанные плейсы:")
    for slot_str, acc in sorted(active.items()):
        place_id = acc.get("place_id")
        place    = f"Place {place_id}" if place_id else "—"
        print(f"    Слот {slot_str} ({acc['username']}): {place}")
    print()
    print("  1. Привязать плейс к слоту")
    print("  2. Удалить привязку")
    print("  3. Назад\n")

    choice = input("  Выбор: ").strip()
    print()

    active_list = sorted(active.keys(), key=int)

    if choice == "1":
        try:
            slot = int(input(f"  Слот: ").strip())
            if str(slot) not in active:
                print("  Слот не найден.\n")
                return
        except ValueError:
            print("  Неверный слот.\n")
            return

        username = active[str(slot)]["username"]
        print(f"\n  Слот {slot} ({username})")
        print("  Введи Place ID, ссылку roblox.com/games/... или deep link:")
        raw = input("  : ").strip()

        place_id = parse_place_id(raw)
        if not place_id:
            print("  Не удалось определить Place ID. Проверь ввод.\n")
            return

        data["accounts"][str(slot)]["place_id"] = place_id
        save_data(data)
        print(f"\n  Слот {slot} → Place {place_id} ✓\n")

    elif choice == "2":
        try:
            slot = int(input(f"  Слот: ").strip())
            if str(slot) not in active:
                print("  Слот не найден.\n")
                return
        except ValueError:
            print("  Неверный слот.\n")
            return

        data["accounts"][str(slot)].pop("place_id", None)
        save_data(data)
        print(f"  Привязка удалена ✓\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 4 — Multi-scripts
# ═══════════════════════════════════════════════════════════════════════════════

def menu_scripts(data: dict):
    print("\n[ Мульти-скрипты ]\n")
    accounts = data.get("accounts", {})

    active = {s: a for s, a in accounts.items() if a is not None}
    if not active:
        print("  Нет аккаунтов. Сначала войди в аккаунты (пункт 2).\n")
        return

    # Показываем текущие скрипты
    print("  Назначенные скрипты:")
    for slot_str, acc in sorted(active.items()):
        has_script = bool(acc.get("script", "").strip())
        marker     = "✓" if has_script else "—"
        print(f"    Слот {slot_str} ({acc['username']}): {marker}")
    print()
    print("  1. Назначить скрипт слоту")
    print("  2. Удалить скрипт у слота")
    print("  3. Назад\n")

    choice = input("  Выбор: ").strip()

    if choice == "1":
        try:
            slot = int(input(f"\n  Слот: ").strip())
            if str(slot) not in active:
                print("  Слот не найден или пустой.\n")
                return
        except ValueError:
            print("  Неверный слот.\n")
            return

        username = active[str(slot)]["username"]
        print(f"\n  Скрипт для: {username}")
        print("  Вставь Lua скрипт. Когда закончишь — введи END на новой строке:\n")

        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            except EOFError:
                break

        script = "\n".join(lines).strip()
        if not script:
            print("  Пустой скрипт, отмена.\n")
            return

        data["accounts"][str(slot)]["script"] = script
        save_data(data)
        print(f"\n  Скрипт для {username} сохранён ✓")

        # Перегенерируем диспетчер если инжектор настроен
        executor = data.get("executor")
        if executor:
            write_lua(executor["path"], data["accounts"])
            print(f"  Диспетчер обновлён в {executor['path']}")
        print()

    elif choice == "2":
        try:
            slot = int(input(f"\n  Слот: ").strip())
            if str(slot) not in active:
                print("  Слот не найден.\n")
                return
        except ValueError:
            print("  Неверный слот.\n")
            return

        username = active[str(slot)]["username"]
        data["accounts"][str(slot)]["script"] = ""
        save_data(data)
        print(f"\n  Скрипт для {username} удалён ✓\n")

        executor = data.get("executor")
        if executor:
            write_lua(executor["path"], data["accounts"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    banner()
    data = load_data()

    while True:
        print_menu()
        choice = input(f"  {YL}›{RS} ").strip()
        print()

        if choice == "1":
            menu_install_clones(data)
        elif choice == "2":
            menu_install_clones(data, reinstall=True)
        elif choice == "3":
            menu_login(data)
        elif choice == "4":
            menu_account_settings(data)
        elif choice == "5":
            menu_scripts(data)
        elif choice == "6":
            menu_launch(data)
        elif choice == "0":
            print("  Выход.\n")
            break
        else:
            print(f"  {DM}Неверный выбор.{RS}\n")

if __name__ == "__main__":
    try:
        arg = sys.argv[1] if len(sys.argv) > 1 else None
        if arg == "--install":
            data = load_data()
            banner()
            menu_install_clones(data)
        elif arg == "--update":
            data = load_data()
            banner()
            menu_install_clones(data, reinstall=True)
        else:
            main()
    except KeyboardInterrupt:
        print("\n\n  OxySync остановлен.\n")
