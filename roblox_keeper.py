import requests
import time
import os
import sys
import json
import subprocess
import re
import sqlite3

# ═══════════════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════════════

VERSION           = "3.28"

DATA_FILE            = "/sdcard/OxySync/data.json"
APK_DIR              = "/sdcard/OxySync/apks/"
HEARTBEAT_DIR        = "/sdcard/OxySync/"
LOG_DIR              = "/sdcard/OxySync/logs/"
HEARTBEAT_TIMEOUT    = 90
PING_INTERVAL        = 60
MAX_SLOTS            = 8
COOKIE_CHECK_INTERVAL = 5  # проверять куки каждые N циклов мониторинга

EXECUTORS = {
    "1": {"name": "Delta",    "path": "/sdcard/Delta/autoexec/"},
    "2": {"name": "Vega X",   "path": "/sdcard/VegaX/autoexec/"},
    "3": {"name": "Codex",    "path": "/sdcard/Codex/autoexec/"},
    "4": {"name": "Arceus X", "path": "/sdcard/Arceus X/autoexec/"},
}

SOURCES = {
    "1": {"name": "VegaX", "type": "gdrive", "id": "1YmbcVrTzMUAmgj8-jO3GItxW5e_eodtx", "apk": "com.roblox.clien{letter}.apk"},
    "2": {"name": "Delta", "type": "gdrive", "id": "1_p5ch5lfwk1HJkqcvOSlh-bSozxogswd",  "apk": "Lunex Delta {slot}.apk"},
}

DEFAULT_PACKAGES = {
    str(i): f"com.roblox.clien{chr(ord('a') + i)}"
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
            d = json.load(f)
    except Exception:
        d = {
            "drive_folder_id": "1YmbcVrTzMUAmgj8-jO3GItxW5e_eodtx",
            "executor": None,
            "packages": DEFAULT_PACKAGES.copy(),
            "accounts": {str(i): None for i in range(1, MAX_SLOTS + 1)},
        }
    d.setdefault("settings", {})
    d["settings"].setdefault("ping_interval", PING_INTERVAL)
    d["settings"].setdefault("cookie_check_interval", COOKIE_CHECK_INTERVAL)
    return d

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


def get_drive_folder_name(folder_id: str) -> str:
    """Возвращает название публичной папки Google Drive (только заголовок страницы)."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        m = re.search(r'<title>([^<]+)</title>', r.text)
        if m:
            return m.group(1).replace(" - Google Drive", "").strip()
    except Exception:
        pass
    return ""

def list_drive_folder(folder_id: str) -> tuple[str, dict]:
    """Возвращает (название_папки, {filename: file_id}) для публичной папки Google Drive."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        text = r.text

        # Название папки — содержит версию если она указана в имени на Drive
        folder_name = ""
        title_m = re.search(r'<title>([^<]+)</title>', text)
        if title_m:
            folder_name = title_m.group(1).replace(" - Google Drive", "").strip()

        # Собираем позиции всех заголовков и entry ID в документе
        titles  = [(m.start(), m.group(1).strip())
                   for m in re.finditer(r'class="flip-entry-title"[^>]*>([^<]+)<', text)]
        entries = [(m.start(), m.group(1))
                   for m in re.finditer(r'id="entry-([a-zA-Z0-9_-]+)"', text)]

        if not titles or not entries:
            return folder_name, {}

        # Оба списка уже отсортированы по позиции — каждый заголовок принадлежит
        # ближайшему entry ID в документе. Сортируем и соединяем попарно.
        titles.sort()
        entries.sort()

        files = {}
        for (_, title), (_, entry_id) in zip(titles, entries):
            files[title] = entry_id
        return folder_name, files
    except Exception:
        return "", {}


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

def get_package_data_dir(package: str) -> str:
    """Возвращает реальный dataDir пакета через pm dump (клоны могут хранить данные не по имени пакета)."""
    r = _su(f"pm dump {package} | grep dataDir")
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("dataDir="):
            return line.split("=", 1)[1].strip()
    return f"/data/user/0/{package}"

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
    r = _su(f"pidof {package}")
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
        _su(f"am start -a android.intent.action.VIEW -d 'roblox://experiences/start?placeId={place_id}' -p {package}")
    else:
        _su(f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p {package}")

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

def get_auth_ticket(session: requests.Session) -> tuple[str | None, str]:
    try:
        csrf = get_csrf(session)
        session.headers.update({
            "X-CSRF-TOKEN": csrf,
            "Referer": "https://www.roblox.com",
            "Origin":  "https://www.roblox.com",
        })
        r = session.post("https://auth.roblox.com/v1/authentication-ticket", timeout=10)
        ticket = r.headers.get("rbx-authentication-ticket")
        if ticket:
            return ticket, ""
        return None, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return None, str(e)

def login_clone(package: str, cookie: str) -> bool:
    """Логинит клон через официальный auth ticket Roblox."""
    session = make_session(cookie)
    ticket, err = get_auth_ticket(session)
    if not ticket:
        print(f"ticket: {err} ", end="", flush=True)
        return False
    force_stop(package)
    time.sleep(1)
    # Сначала запускаем приложение, чтобы оно успело инициализироваться
    launch_clone(package)
    time.sleep(5)
    # Запускаем через ActivityProtocol — активити которая обрабатывает roblox:// ссылки
    result = _su(
        f"am start -n {package}/com.roblox.client.ActivityProtocol"
        f" -a android.intent.action.VIEW"
        f" -d 'roblox://authenticate?ticket={ticket}&returnToApp=1'"
    )
    if result.returncode == 0:
        return True
    # Если ActivityProtocol не найден — пробуем без указания активити
    result2 = _su(
        f"am start -a android.intent.action.VIEW"
        f" -d 'roblox://authenticate?ticket={ticket}&returnToApp=1'"
        f" -p {package}"
    )
    return result2.returncode == 0

def _create_webview_db(path: str):
    """Создаёт WebView Cookies базу с точной схемой Chromium (версия 15)."""
    conn = sqlite3.connect(path)
    cur  = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY,
            value LONGVARCHAR
        );
        INSERT OR REPLACE INTO meta VALUES('version','15');
        INSERT OR REPLACE INTO meta VALUES('last_compatible_version','15');
        CREATE TABLE IF NOT EXISTS cookies (
            creation_utc       INTEGER NOT NULL,
            top_frame_site_key TEXT NOT NULL,
            host_key           TEXT NOT NULL,
            name               TEXT NOT NULL,
            value              TEXT NOT NULL,
            encrypted_value    BLOB DEFAULT '',
            path               TEXT NOT NULL,
            expires_utc        INTEGER NOT NULL,
            is_secure          INTEGER NOT NULL,
            is_httponly        INTEGER NOT NULL,
            last_access_utc    INTEGER NOT NULL,
            has_expires        INTEGER NOT NULL DEFAULT 1,
            is_persistent      INTEGER NOT NULL DEFAULT 1,
            priority           INTEGER NOT NULL DEFAULT 1,
            samesite           INTEGER NOT NULL DEFAULT -1,
            source_scheme      INTEGER NOT NULL DEFAULT 0,
            source_port        INTEGER NOT NULL DEFAULT -1,
            is_same_party      INTEGER NOT NULL DEFAULT 0,
            UNIQUE (top_frame_site_key, host_key, name, path)
        );
    """)
    conn.commit()
    conn.close()

def extract_cookie(package: str) -> str | None:
    """Читает .ROBLOSECURITY из WebView SQLite базы клона."""
    tmp     = "/sdcard/OxySync/tmp_read_cookies"
    tmp_wal = "/sdcard/OxySync/tmp_read_cookies-wal"

    internal_pkg = package.replace("client", "clien")
    data_dir     = get_package_data_dir(package)
    candidates   = list(dict.fromkeys([
        f"/data/data/{internal_pkg}",
        f"/data/user/0/{internal_pkg}",
        data_dir,
        f"/data/data/{package}",
        f"/data/user/0/{package}",
    ]))

    found = None
    for cand in candidates:
        r = _su(f"find {cand}/app_webview -name 'Cookies' 2>/dev/null")
        hits = [p.strip() for p in r.stdout.splitlines() if p.strip()]
        if hits:
            found = hits[0]
            break

    if not found:
        return None

    _su(f"cp '{found}-wal' '{tmp_wal}' 2>/dev/null; chmod 666 '{tmp_wal}' 2>/dev/null")
    if _su(f"cp '{found}' '{tmp}' && chmod 666 '{tmp}'").returncode != 0:
        return None

    try:
        conn = sqlite3.connect(tmp)
        cur  = conn.cursor()
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cur.execute(
            "SELECT value FROM cookies "
            "WHERE host_key='.roblox.com' AND name='.ROBLOSECURITY' LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None
    finally:
        _su(f"rm -f '{tmp}' '{tmp_wal}'")


def inject_cookie(package: str, cookie: str) -> bool:
    """Записывает .ROBLOSECURITY напрямую в WebView SQLite базу клона (без запуска приложения)."""
    force_stop(package)
    time.sleep(1)

    tmp     = "/sdcard/OxySync/tmp_cookies"
    tmp_wal = "/sdcard/OxySync/tmp_cookies-wal"

    # Клоны хранят WebView данные под внутренним именем пакета (без 't': clientb → clienb)
    # pm dump возвращает dataDir лаунчера (com.og.launcher), а реальные куки лежат глубже
    internal_pkg = package.replace("client", "clien")
    data_dir     = get_package_data_dir(package)
    candidates   = list(dict.fromkeys([
        f"/data/data/{internal_pkg}",
        f"/data/user/0/{internal_pkg}",
        data_dir,
        f"/data/data/{package}",
        f"/data/user/0/{package}",
    ]))

    # Ищем существующий файл Cookies среди всех кандидатов
    found    = []
    app_base = None
    for cand in candidates:
        r = _su(f"find {cand}/app_webview -name 'Cookies' 2>/dev/null")
        hits = [p.strip() for p in r.stdout.splitlines() if p.strip()]
        if hits:
            found    = hits
            app_base = cand
            break
    created = False

    if found:
        db_path = found[0]
        # Копируем DB и WAL вместе чтобы sqlite3 увидел консистентное состояние
        _su(f"cp '{db_path}-wal' '{tmp_wal}' 2>/dev/null; chmod 666 '{tmp_wal}' 2>/dev/null")
        if _su(f"cp '{db_path}' '{tmp}' && chmod 666 '{tmp}'").returncode != 0:
            print(f"    Не удалось скопировать базу")
            return False
    else:
        print(f"    [dbg] Cookies не найден ни в одном пути — создаю с нуля")
        app_base = f"/data/data/{internal_pkg}"
        db_path  = f"{app_base}/app_webview/Default/Cookies"
        try:
            _create_webview_db(tmp)
            created = True
        except Exception as e:
            print(f"    Не удалось создать базу: {e}")
            return False

    try:
        conn = sqlite3.connect(tmp)
        cur  = conn.cursor()

        # Принудительно сбрасываем WAL в основной файл и переключаемся в rollback-режим
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cur.execute("PRAGMA journal_mode=DELETE")

        cur.execute("PRAGMA table_info(cookies)")
        columns = {row[1] for row in cur.fetchall()}

        cur.execute(
            "DELETE FROM cookies WHERE host_key='.roblox.com' AND name='.ROBLOSECURITY'"
        )

        now    = int(time.time() * 1_000_000) + 11644473600 * 1_000_000
        fields = ["creation_utc", "host_key", "name", "value", "path", "expires_utc",
                  "is_secure", "is_httponly", "last_access_utc",
                  "has_expires", "is_persistent", "priority", "encrypted_value"]
        values = [now, '.roblox.com', '.ROBLOSECURITY', cookie, '/',
                  99999999999999999, 1, 1, now, 1, 1, 1, b'']

        optional = [
            ("top_frame_site_key", ""), ("samesite", -1),
            ("source_scheme", 0), ("source_port", -1),
            ("is_same_party", 0),
        ]
        for col, val in optional:
            if col in columns:
                fields.append(col)
                values.append(val)

        placeholders = ",".join(["?"] * len(fields))
        cur.execute(
            f"INSERT INTO cookies ({','.join(fields)}) VALUES ({placeholders})",
            values
        )
        conn.commit()
        conn.close()

        owner = _su(f"stat -c '%u:%g' {app_base}").stdout.strip()

        if created:
            parent = db_path.rsplit("/", 1)[0]
            _su(f"mkdir -p '{parent}'")
            if owner:
                # Чиним владельца на всю цепочку директорий
                _su(f"chown {owner} '{parent}' '{parent.rsplit('/', 1)[0]}' 2>/dev/null")

        cp = _su(f"cp '{tmp}' '{db_path}'")
        if cp.returncode != 0:
            print(f"    Не удалось скопировать базу в app_webview")
            _su(f"rm -f '{tmp}' '{tmp_wal}'")
            return False

        if owner:
            _su(f"chown {owner} '{db_path}'")
        # Убираем WAL/SHM — база уже в rollback-режиме, они не нужны
        _su(f"rm -f '{db_path}-wal' '{db_path}-shm'")
        # Восстанавливаем SELinux контекст (без этого приложение не прочитает файл)
        _su(f"restorecon '{db_path}' 2>/dev/null || chcon u:object_r:app_data_file:s0 '{db_path}' 2>/dev/null")
        _su(f"chmod 600 '{db_path}'")
        _su(f"rm -f '{tmp}' '{tmp_wal}'")
        return True
    except Exception as e:
        print(f"    SQLite ошибка: {e}")
        _su(f"rm -f '{tmp}' '{tmp_wal}'")
        return False

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

def _desc(text):
    pad = " " * (W - 5 - len(text))
    print(f"  {CY}│{RS}     {DM}{text}{pad}{CY}│{RS}")

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
    _desc("Скачать и установить клоны Roblox")
    _row("2", "Обновить клоны")
    _desc("Обновить клоны, аккаунты сохранятся")
    _row("3", "Удалить клоны")
    _desc("Удалить все клоны с устройства")
    _bot()
    print()

    _top("АККАУНТЫ")
    _row("4", "Войти в аккаунт")
    _desc("Войти в аккаунт через куки")
    _row("5", "Настройка аккаунтов")
    _desc("Привязать игру, управление слотами")
    _bot()
    print()

    _top("ИГРА")
    _row("6", "Мульти-скрипты")
    _desc("Авто-скрипт при входе в игру")
    _row("7", "Запустить игры")
    _desc("Запустить аккаунты и следить за ними")
    _bot()
    print()

    _top("ПРОЧЕЕ")
    _row("8", "Настройки")
    _desc("Экзекутор и параметры проверок")
    _row("9", "Помощь")
    _desc("Инструкция по настройке и запуску")
    _bot()
    print()

    print(f"  {DM}0  Выход{RS}\n")

def format_ingame(secs: int) -> str:
    if secs <= 0:
        return "—"
    h = secs // 3600
    m = (secs % 3600) // 60
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м"
    return f"{secs}с"

def print_slots_panel(data: dict):
    accounts = data.get("accounts", {})
    active   = [(i, accounts[str(i)]) for i in range(1, MAX_SLOTS + 1) if accounts.get(str(i))]
    if not active:
        return
    _top("СЛОТЫ")
    for i, acc in active:
        nick = acc["username"][:14]
        mark = f"{GR}✓{RS}"
        igt  = format_ingame(acc.get("ingame_total", 0))
        row  = f"  {i:<2}  {nick:<14}  {mark}  {igt:<9}"
        print(f"  {CY}│{RS}{row}{CY}│{RS}")
    _bot()
    print()

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
#  Logging
# ═══════════════════════════════════════════════════════════════════════════════

_log_handle = None
_log_date   = None

def log(msg: str):
    global _log_handle, _log_date
    print(msg)
    today = time.strftime("%Y-%m-%d")
    try:
        if _log_date != today:
            if _log_handle:
                _log_handle.close()
            os.makedirs(LOG_DIR, exist_ok=True)
            _log_handle = open(f"{LOG_DIR}{today}.log", "a", encoding="utf-8")
            _log_date   = today
        _log_handle.write(msg + "\n")
        _log_handle.flush()
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 1 & 4 — Install / Reinstall clones
# ═══════════════════════════════════════════════════════════════════════════════

def menu_install_clones(data: dict, reinstall: bool = False):
    title = "Обновление клонов" if reinstall else "Установка клонов"
    print(f"\n[ {title} ]\n")

    # Выбор пачки клонов (если источников больше одного — показываем меню)
    source_keys = list(SOURCES.keys())
    if len(source_keys) > 1:
        print("  Загружаю версии пачек...", end=" ", flush=True)
        folder_labels = {}
        for k in source_keys:
            s = SOURCES[k]
            if s["type"] == "gdrive":
                name = get_drive_folder_name(s["id"])
                folder_labels[k] = name if name else s["name"]
            else:
                folder_labels[k] = s["name"]
        print("готово\n")

        print("  Выбери пачку клонов:")
        for k in source_keys:
            print(f"    {k}. {folder_labels[k]}")
        ch = input("\n  Номер: ").strip()
        source = SOURCES.get(ch, SOURCES[source_keys[0]])
        print()
    else:
        source = SOURCES[source_keys[0]]

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
    print(f"  {YL}⚠ Лимиты клонов по VIP на сервисе:{RS}")
    print(f"  {DM}  UVIP → 1-2   GVIP → 3-4   SVIP → 6-8{RS}")
    print(f"  {DM}  Превышение лимита нарушает правила сервиса.{RS}\n")
    try:
        count = int(input(f"  Сколько клонов? (1-{MAX_SLOTS}): ").strip())
        count = max(1, min(count, MAX_SLOTS))
    except ValueError:
        count = 1

    packages = data.get("packages", DEFAULT_PACKAGES)

    # Получаем список файлов
    if source["type"] == "gdrive":
        print("  Получаю список файлов из Google Drive...", end=" ", flush=True)
        folder_name, gdrive_files = list_drive_folder(source["id"])
        remote_files = {name: ("gdrive", fid) for name, fid in gdrive_files.items()}
    else:
        print("  Получаю список файлов из Gofile...", end=" ", flush=True)
        folder_name = source["name"]
        remote_files = {name: ("gofile", link, token) for name, (link, token) in list_gofile_folder(source["id"]).items()}

    if remote_files:
        print(f"найдено {len(remote_files)} файл(ов)")
        if folder_name:
            print(f"  Пачка: {GR}{folder_name}{RS}")
    else:
        print("не удалось получить список файлов\n")
        return
    print()

    apk_template = source.get("apk", "com.roblox.clien{letter}.apk")

    for slot in range(1, count + 1):
        pkg      = packages.get(str(slot), DEFAULT_PACKAGES[str(slot)])
        letter   = chr(ord('a') + slot)
        apk_name = apk_template.format(slot=slot, letter=letter)
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
        old_pkg  = packages.get(str(slot), pkg)
        if detected:
            print(detected)
            pkg = detected
        else:
            print(f"не удалось, использую: {pkg}")

        # uninstall только если package name сменился
        if reinstall and old_pkg and old_pkg != pkg and is_package_installed(old_pkg):
            print(f"    Package name изменился, удаляю старый...")
            uninstall_root(old_pkg)

        print(f"    Устанавливаю...", end=" ", flush=True)
        if install_apk_root(apk_path):
            packages[str(slot)] = pkg
            data["packages"] = packages
            os.remove(apk_path)
            print("Готово ✓")
            print(f"    Инициализация (12 сек)...", end=" ", flush=True)
            launch_clone(pkg)
            time.sleep(12)
            force_stop(pkg)
            print("✓")

            # Восстанавливаем или запрашиваем аккаунт после установки
            if reinstall:
                acc = data.get("accounts", {}).get(str(slot))
                if acc and acc.get("cookie"):
                    print(f"    Восстанавливаю {acc['username']}...", end=" ", flush=True)
                    if inject_cookie(pkg, acc["cookie"]):
                        print("✓")
                    elif login_clone(pkg, acc["cookie"]):
                        print("✓ (auth ticket)")
                    else:
                        print("не удалось — войди через пункт 4")
                else:
                    # Пробуем достать куки из самого клона
                    print(f"    Аккаунт для слота {slot} не найден.")
                    print(f"    Ищу куки в клоне...", end=" ", flush=True)
                    cookie = extract_cookie(pkg)
                    if cookie:
                        print("найдено")
                        info = get_account_info(make_session(cookie))
                        if info:
                            username = info.get("name", "Unknown")
                            user_id  = info.get("id", 0)
                            data["accounts"][str(slot)] = {
                                "cookie": cookie, "username": username, "user_id": user_id
                            }
                            print(f"    {username} ✓")
                        else:
                            print(f"    Куки истёк — введи новый через пункт 4.")
                            cookie = None
                    else:
                        print("не найдено")

                    # Если не удалось — предлагаем ввести вручную
                    if not cookie:
                        print(f"    Введи куки вручную (или Enter — пропустить):")
                        cookie = input(f"    Куки: ").strip()
                        if cookie:
                            if cookie.startswith(".ROBLOSECURITY="):
                                cookie = cookie.split("=", 1)[1]
                            info = get_account_info(make_session(cookie))
                            if info:
                                username = info.get("name", "Unknown")
                                user_id  = info.get("id", 0)
                                data["accounts"][str(slot)] = {
                                    "cookie": cookie, "username": username, "user_id": user_id
                                }
                                print(f"    {username} — вхожу...", end=" ", flush=True)
                                if inject_cookie(pkg, cookie):
                                    print("✓")
                                elif login_clone(pkg, cookie):
                                    print("✓ (auth ticket)")
                                else:
                                    print("не удалось — войди через пункт 4")
                            else:
                                print(f"    Неверный куки, пропускаю.")
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

def menu_delete_clones(data: dict):
    print("\n[ Удаление клонов ]\n")
    packages = data.get("packages", DEFAULT_PACKAGES)
    slots    = installed_slots(data)

    if not slots:
        print("  Нет установленных клонов.\n")
        return

    print("  Установленные клоны:")
    for i in slots:
        print(f"    Слот {i}: {packages.get(str(i), DEFAULT_PACKAGES[str(i)])}")
    print()
    confirm = input("  Удалить все? (y/N): ").strip().lower()
    if confirm != "y":
        print("  Отмена.\n")
        return
    print()
    for i in slots:
        pkg = packages.get(str(i), DEFAULT_PACKAGES[str(i)])
        print(f"  Слот {i}: удаляю...", end=" ", flush=True)
        force_stop(pkg)
        uninstall_root(pkg)
        print("✓")
    print("\n  Готово.\n")

def _do_login(data: dict, slot: int, cookie: str) -> bool:
    """Валидирует куки, сохраняет аккаунт и инжектит в клон. Возвращает True при успехе."""
    if cookie.startswith(".ROBLOSECURITY="):
        cookie = cookie.split("=", 1)[1]

    info = get_account_info(make_session(cookie))
    if not info:
        print("  Неверный или просроченный куки.")
        return False

    username = info.get("name", "Unknown")
    user_id  = info.get("id", 0)
    data["accounts"][str(slot)] = {"cookie": cookie, "username": username, "user_id": user_id}
    save_data(data)
    print(f"  Слот {slot} → {GR}{username}{RS} (ID: {user_id}) ✓")

    pkg = data.get("packages", DEFAULT_PACKAGES).get(str(slot), DEFAULT_PACKAGES[str(slot)])
    if is_package_installed(pkg):
        print(f"  Вхожу в клон...", end=" ", flush=True)
        if inject_cookie(pkg, cookie):
            print("✓")
        elif login_clone(pkg, cookie):
            print("✓ (auth ticket)")
        else:
            print("не удалось — войди вручную")
    else:
        print(f"  Клон не установлен — войди вручную после установки")
    return True


def menu_login(data: dict):
    print("\n[ Вход в аккаунты ]\n")
    data.setdefault("accounts", {str(i): None for i in range(1, MAX_SLOTS + 1)})
    accounts = data["accounts"]

    slots = installed_slots(data)
    if not slots:
        print("  Нет установленных клонов. Сначала установи клоны (пункт 1).\n")
        return

    print("  Установленные слоты:")
    for i in slots:
        acc = accounts.get(str(i))
        print(f"    Слот {i}: {acc['username'] if acc else '—'}")
    print()

    # Несколько слотов — предлагаем bulk-режим
    if len(slots) > 1:
        print("  1. Войти в один слот")
        print("  2. Вставить сразу несколько куки\n")
        choice = input("  Выбор: ").strip()
        print()

        if choice == "2":
            print(f"  Вставляй куки по одной на строку.")
            print(f"  Слоты по порядку: {' → '.join(str(s) for s in slots)}")
            print(f"  Пустая строка = закончить.\n")

            cookies = []
            for i, slot in enumerate(slots):
                acc = accounts.get(str(slot))
                cur = f" (сейчас: {acc['username']})" if acc else ""
                raw = input(f"  Слот {slot}{cur}: ").strip()
                if not raw:
                    break
                cookies.append((slot, raw))

            if not cookies:
                print("  Отмена.\n")
                return

            print()
            for slot, cookie in cookies:
                _do_login(data, slot, cookie)
                print()
            return

    # Один слот
    try:
        slot = int(input(f"  Слот ({slots[0]}-{slots[-1]}): ").strip())
        if slot not in slots:
            raise ValueError
    except ValueError:
        print("  Неверный слот.\n")
        return

    cookie = input(f"\n  Куки для слота {slot}: ").strip()
    print()
    _do_login(data, slot, cookie)
    print()

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

    # Выбор слотов
    print("  Доступные слоты:")
    for s, a in sorted(active.items(), key=lambda x: int(x[0])):
        print(f"    {s}. {a['username']}")
    print()
    raw = input("  Слоты (через запятую, Enter = все): ").strip()
    if raw:
        chosen = {x.strip() for x in raw.split(",")}
        active = {s: a for s, a in active.items() if s in chosen}
        if not active:
            print("  Ни один из указанных слотов не найден.\n")
            return
    print()

    # Генерируем диспетчер перед запуском
    if executor:
        write_lua(executor["path"], data["accounts"])

    sessions = {}
    for slot_str, acc in sorted(active.items(), key=lambda x: int(x[0])):
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

    print(f"\n  Ожидаю загрузку (45 сек)...")
    time.sleep(45)

    # Status cards
    print("\n" + "─" * 40)
    for slot_str, acc in sorted(active.items(), key=lambda x: int(x[0])):
        presence = get_presence(sessions[slot_str], acc["user_id"])
        print_status_card(int(slot_str), acc["username"], presence)
    print("─" * 40)

    ping_interval = data.get("settings", {}).get("ping_interval", PING_INTERVAL)
    print(f"\n  Мониторинг запущен. Интервал: {ping_interval} сек.")
    print(f"  {DM}Для остановки нажми кнопку CTRL в Termux, затем C.{RS}\n")
    try:
        monitor_all(sessions, active, packages, data)
    except KeyboardInterrupt:
        # Сохраняем накопленное время в игре при выходе
        save_data(data)
        print("\n\n  Мониторинг остановлен.\n")

def monitor_all(sessions: dict, accounts: dict, packages: dict, data: dict):
    settings        = data.get("settings", {})
    ping_interval   = settings.get("ping_interval", PING_INTERVAL)
    cookie_interval = settings.get("cookie_check_interval", COOKIE_CHECK_INTERVAL)

    offline_counts  = {s: 0 for s in sessions}
    check_counters  = {s: 0 for s in sessions}
    invalid_cookies: set = set()
    ingame_start:   dict = {}
    restart_cooldown: dict = {}
    last_save = time.time()
    cycle     = 0

    while True:
        cycle += 1
        ts = time.strftime("%H:%M:%S")
        print(f"\n  {DM}{'─' * 36}{RS}")
        print(f"  {DM}Проверка #{cycle} · {ts}{RS}")
        for slot_str, session in sessions.items():
            if slot_str in invalid_cookies:
                continue

            # Пропускаем N циклов после рестарта — клон ещё грузится
            if slot_str in restart_cooldown:
                restart_cooldown[slot_str] -= 1
                if restart_cooldown[slot_str] <= 0:
                    del restart_cooldown[slot_str]
                continue

            acc  = accounts[slot_str]
            pkg  = packages.get(slot_str, DEFAULT_PACKAGES.get(slot_str, ""))
            slot = int(slot_str)
            name = acc["username"]

            try:
                check_counters[slot_str] += 1
                if check_counters[slot_str] >= cookie_interval:
                    check_counters[slot_str] = 0
                    if get_account_info(session) is None:
                        log(f"[{ts}] Слот {slot} ({name}): КУКИ ИСТЁК — слот отключён от мониторинга")
                        invalid_cookies.add(slot_str)
                        force_stop(pkg)
                        if slot_str in ingame_start:
                            elapsed = int(time.time() - ingame_start.pop(slot_str))
                            acc["ingame_total"] = acc.get("ingame_total", 0) + elapsed
                        continue

                if not is_process_running(pkg):
                    log(f"[{ts}] Слот {slot} ({name}): краш — перезапускаю...")
                    launch_clone(pkg, acc.get("place_id"))
                    offline_counts[slot_str] = 0
                    restart_cooldown[slot_str] = 3
                    continue

                if not is_heartbeat_alive(slot):
                    log(f"[{ts}] Слот {slot} ({name}): heartbeat устарел")

                presence  = get_presence(session, acc["user_id"])
                status    = presence["status"]
                game_name = presence["game_name"] or "—"

                if status == "ingame":
                    if slot_str not in ingame_start:
                        ingame_start[slot_str] = time.time()
                    log(f"[{ts}] Слот {slot} ({name}): В игре — {game_name} ✓")
                    offline_counts[slot_str] = 0
                else:
                    if slot_str in ingame_start:
                        elapsed = int(time.time() - ingame_start.pop(slot_str))
                        acc["ingame_total"] = acc.get("ingame_total", 0) + elapsed
                    if status == "online":
                        log(f"[{ts}] Слот {slot} ({name}): Онлайн")
                        offline_counts[slot_str] = 0
                    elif status == "offline":
                        offline_counts[slot_str] += 1
                        log(f"[{ts}] Слот {slot} ({name}): Офлайн ({offline_counts[slot_str]}/3)")
                        if offline_counts[slot_str] >= 3:
                            log(f"[{ts}] Слот {slot}: перезапускаю...")
                            force_stop(pkg)
                            launch_clone(pkg, acc.get("place_id"))
                            offline_counts[slot_str] = 0
                            restart_cooldown[slot_str] = 3

            except requests.exceptions.ConnectionError:
                log(f"[{ts}] Нет интернета...")
            except Exception as e:
                if "403" in str(e) or "csrf" in str(e).lower():
                    try:
                        session.headers.update({"X-CSRF-TOKEN": get_csrf(session)})
                    except Exception:
                        pass

        now = time.time()
        if now - last_save >= 300:
            for s, start in list(ingame_start.items()):
                acc = accounts.get(s)
                if acc:
                    elapsed = int(now - start)
                    acc["ingame_total"] = acc.get("ingame_total", 0) + elapsed
                    ingame_start[s] = now
            save_data(data)
            last_save = now

        for remaining in range(ping_interval, 0, -1):
            print(f"\r  {DM}Следующая проверка через {remaining} сек...{' ' * 5}{RS}",
                  end="", flush=True)
            time.sleep(1)
        print(f"\r{' ' * 50}\r", end="", flush=True)

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
    print("  3. Сбросить слот")
    print("  4. Назад\n")

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

    elif choice == "3":
        try:
            slot = int(input(f"  Слот: ").strip())
            if str(slot) not in active:
                print("  Слот не найден.\n")
                return
        except ValueError:
            print("  Неверный слот.\n")
            return

        name = active[str(slot)]["username"]
        confirm = input(f"  Сбросить слот {slot} ({name})? (y/N): ").strip().lower()
        if confirm != "y":
            print("  Отмена.\n")
            return
        data["accounts"][str(slot)] = None
        save_data(data)
        executor = data.get("executor")
        if executor:
            write_lua(executor["path"], data["accounts"])
        print(f"  Слот {slot} сброшен ✓\n")


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
#  Menu 7 — Settings
# ═══════════════════════════════════════════════════════════════════════════════

def menu_settings(data: dict):
    print("\n[ Настройки ]\n")
    current  = data.get("executor")
    settings = data.setdefault("settings", {})
    settings.setdefault("ping_interval", PING_INTERVAL)
    settings.setdefault("cookie_check_interval", COOKIE_CHECK_INTERVAL)

    print(f"  Инжектор  : {current['name'] if current else '—'}")
    print(f"  Пинг      : каждые {settings['ping_interval']} сек")
    print(f"  Куки-чек  : каждые {settings['cookie_check_interval']} циклов\n")

    print("  1. Сменить инжектор")
    print("  2. Интервал мониторинга (сек)")
    print("  3. Частота проверки куки (циклов)")
    print("  4. Назад\n")

    choice = input("  Выбор: ").strip()

    if choice == "1":
        print("\n  Выбери инжектор:")
        for k, v in EXECUTORS.items():
            print(f"    {k}. {v['name']}")
        ch = input("  Номер: ").strip()
        if ch not in EXECUTORS:
            print("  Неверный выбор.\n")
            return
        data["executor"] = EXECUTORS[ch]
        save_data(data)
        if any(data.get("accounts", {}).values()):
            write_lua(data["executor"]["path"], data["accounts"])
        print(f"\n  Инжектор -> {data['executor']['name']} ✓\n")

    elif choice == "2":
        try:
            val = int(input("  Интервал (сек, 10-300): ").strip())
            val = max(10, min(300, val))
            settings["ping_interval"] = val
            save_data(data)
            print(f"  Интервал -> {val} сек ✓\n")
        except ValueError:
            print("  Неверный ввод.\n")

    elif choice == "3":
        try:
            val = int(input("  Проверять куки каждые N циклов (1-20): ").strip())
            val = max(1, min(20, val))
            settings["cookie_check_interval"] = val
            save_data(data)
            print(f"  Куки-чек -> каждые {val} циклов ✓\n")
        except ValueError:
            print("  Неверный ввод.\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  Menu 9 — Help
# ═══════════════════════════════════════════════════════════════════════════════

def menu_help():
    print("\n[ Помощь — Быстрый старт ]\n")

    steps = [
        ("Шаг 1 · Установить клоны  (пункт 1)",
         ["Выбери пачку клонов VegaX или Delta и",
          "количество. Каждый клон — отдельный",
          "Roblox с независимым аккаунтом."]),
        ("Шаг 2 · Получить куки аккаунта",
         ["На ПК: зайди на roblox.com, открой F12,",
          "вкладка Application → Cookies → roblox.com,",
          "найди .ROBLOSECURITY и скопируй значение.",
          "На телефоне: браузер Kiwi + расширение.",
          "Куки выглядят как длинная строка букв."]),
        ("Шаг 3 · Войти в аккаунт  (пункт 4)",
         ["Выбери слот и вставь куки — скрипт",
          "автоматически зайдёт в клон."]),
        ("Шаг 4 · Привязать игру  (пункт 5)",
         ["Укажи ссылку на игру или Place ID:",
          "  roblox.com/games/XXXXXXXXX",
          "Без привязки клон запустится в меню."]),
        ("Шаг 5 · Настроить экзекутор  (пункт 8)",
         ["Выбери свой экзекутор: Delta, Vega X и т.д.",
          "Это нужно для авто-скриптов в игре.",
          "Без экзекутора мониторинг работает."]),
        ("Шаг 6 · Запустить  (пункт 7)",
         ["Клоны запустятся и начнётся мониторинг.",
          "При краше скрипт перезапустит их сам."]),
    ]

    for title, lines in steps:
        print(f"  {GR}{title}{RS}")
        for line in lines:
            print(f"    {DM}{line}{RS}")
        print()

    print(f"  {YL}Частые вопросы{RS}\n")

    faqs = [
        ("Вход не сработал",
         ["Куки могли устареть — обнови через пункт 4.",
          "Убедись что куки начинается с _|WARNING"]),
        ("Куки истёк во время мониторинга",
         ["Слот автоматически отключается.",
          "Зайди снова через пункт 4."]),
        ("Heartbeat устарел",
         ["Экзекутор не запустил скрипт.",
          "Проверь ключ экзекутора и папку autoexec.",
          "На мониторинг не влияет — просто инфо."]),
        ("Клон не устанавливается",
         ["Скрипт отключает Play Protect автоматом.",
          "Если не помогло — отключи вручную в",
          "настройках Google Play."]),
        ("Аккаунт вылетел после обновления клона",
         ["Скрипт восстанавливает куки сам после",
          "переустановки (пункт 2)."]),
    ]

    for q, lines in faqs:
        print(f"  {YL}? {q}{RS}")
        for line in lines:
            print(f"    {DM}{line}{RS}")
        print()

    input(f"  {DM}Enter — назад{RS}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    banner()
    data = load_data()

    while True:
        print_slots_panel(data)
        print_menu()
        choice = input(f"  {YL}›{RS} ").strip()
        print()

        if choice == "1":
            menu_install_clones(data)
        elif choice == "2":
            menu_install_clones(data, reinstall=True)
        elif choice == "3":
            menu_delete_clones(data)
        elif choice == "4":
            menu_login(data)
        elif choice == "5":
            menu_account_settings(data)
        elif choice == "6":
            menu_scripts(data)
        elif choice == "7":
            menu_launch(data)
        elif choice == "8":
            menu_settings(data)
        elif choice == "9":
            menu_help()
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
