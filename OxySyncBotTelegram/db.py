import aiosqlite
import secrets
import time
import struct
import hmac
import hashlib
import base64
from config import DB_PATH, SERVER_SECRET


def _generate_token(user_id: int) -> str:
    """
    Формат: OXY-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX  (39 символов)
    Структура 20 байт:
      [0:8]  user_id  (uint64 big-endian)
      [8:16] случайные байты (64 бит энтропии)
      [16:20] HMAC-SHA256(SERVER_SECRET, uid+rand)[:4]
    """
    uid_bytes  = struct.pack(">Q", user_id)
    rand_bytes = secrets.token_bytes(8)
    mac        = hmac.new(
        SERVER_SECRET.encode(),
        uid_bytes + rand_bytes,
        hashlib.sha256,
    ).digest()[:4]
    raw     = uid_bytes + rand_bytes + mac          # 20 байт → 32 base32-символа без паддинга
    encoded = base64.b32encode(raw).decode()
    return f"OXY-{encoded[0:8]}-{encoded[8:16]}-{encoded[16:24]}-{encoded[24:32]}"


def decode_token(token: str) -> int | None:
    """
    Верифицирует токен и возвращает user_id.
    Возвращает None если токен подделан или повреждён.
    """
    try:
        encoded = token.replace("OXY-", "").replace("-", "")
        raw     = base64.b32decode(encoded)
        if len(raw) != 20:
            return None
        uid_bytes, rand_bytes, mac = raw[:8], raw[8:16], raw[16:]
        expected = hmac.new(
            SERVER_SECRET.encode(),
            uid_bytes + rand_bytes,
            hashlib.sha256,
        ).digest()[:4]
        if not hmac.compare_digest(mac, expected):
            return None
        return struct.unpack(">Q", uid_bytes)[0]
    except Exception:
        return None


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id      INTEGER UNIQUE NOT NULL,
                username   TEXT,
                plan       TEXT NOT NULL DEFAULT 'free',
                expires_at INTEGER,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                token      TEXT UNIQUE NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                device_id  TEXT NOT NULL,
                last_seen  INTEGER,
                is_banned  INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, device_id)
            );
        """)
        await db.commit()


async def get_or_create_user(tg_id: int, username: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)

        now = int(time.time())
        await db.execute(
            "INSERT INTO users (tg_id, username, plan, created_at) VALUES (?,?,?,?)",
            (tg_id, username, "free", now),
        )
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)) as cur:
            return dict(await cur.fetchone())


async def get_or_create_token(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT token FROM tokens WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["token"]

        token = _generate_token(user_id)
        await db.execute(
            "INSERT INTO tokens (user_id, token, created_at) VALUES (?,?,?)",
            (user_id, token, int(time.time())),
        )
        await db.commit()
        return token


async def get_user_by_token(token: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.* FROM users u
            JOIN tokens t ON t.user_id = u.id
            WHERE t.token = ?
            """,
            (token,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def register_device(user_id: int, device_id: str) -> bool:
    """Регистрирует устройство. Возвращает False если оно забанено."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = int(time.time())
        await db.execute(
            """
            INSERT INTO devices (user_id, device_id, last_seen, is_banned)
            VALUES (?,?,?,0)
            ON CONFLICT(user_id, device_id)
            DO UPDATE SET last_seen = excluded.last_seen
            """,
            (user_id, device_id, now),
        )
        await db.commit()
        async with db.execute(
            "SELECT is_banned FROM devices WHERE user_id=? AND device_id=?",
            (user_id, device_id),
        ) as cur:
            row = await cur.fetchone()
        return not bool(row["is_banned"])


async def set_plan(tg_id: int, plan: str, days: int = 0):
    expires_at = int(time.time()) + days * 86400 if days else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET plan=?, expires_at=? WHERE tg_id=?",
            (plan, expires_at, tg_id),
        )
        await db.commit()


async def ban_device(device_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE devices SET is_banned=1 WHERE device_id=?", (device_id,)
        )
        await db.commit()


async def list_users(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
