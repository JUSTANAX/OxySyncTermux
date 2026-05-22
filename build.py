"""
OxySync — build obfuscated release
Запуск: python build.py
Результат: dist/roblox_keeper.py
"""

import marshal, zlib, base64, os, sys, hashlib, random, string

SRC  = "roblox_keeper.py"
DIST = "dist"
OUT  = os.path.join(DIST, "roblox_keeper.py")

def random_var(n=12):
    return "_" + "".join(random.choices(string.ascii_lowercase, k=n))

def build():
    print(f"[*] Читаю {SRC}...")
    with open(SRC, "r", encoding="utf-8") as f:
        source = f.read()

    print("[*] Компилирую...")
    code = compile(source, "<protected>", "exec")

    print("[*] Сжимаю и кодирую...")
    raw     = marshal.dumps(code)
    key     = hashlib.sha256(b"oxysync_key_2024").digest()
    xored   = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    payload = base64.b85encode(zlib.compress(xored, level=9)).decode()

    key_b85 = base64.b85encode(key).decode()

    v1, v2, v3, v4, v5 = (random_var() for _ in range(5))

    loader = (
        "import marshal as _m,zlib as _z,base64 as _b,hashlib as _h\n"
        f"{v1}={payload!r}\n"
        f"{v2}={key_b85!r}\n"
        f"{v3}=_h.sha256(b'oxysync_key_2024').digest()\n"
        f"{v4}=bytes(b^{v3}[i%len({v3})]for i,b in enumerate(_z.decompress(_b.b85decode({v1}))))\n"
        f"{v5}=_m.loads({v4})\n"
        f"exec({v5})\n"
    )

    os.makedirs(DIST, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(loader)

    src_kb  = os.path.getsize(SRC) / 1024
    out_kb  = os.path.getsize(OUT) / 1024
    print(f"[+] Готово: {OUT}")
    print(f"    Исходник : {src_kb:.1f} KB")
    print(f"    Результат: {out_kb:.1f} KB")

    # Достаём версию из исходника
    version = "unknown"
    for line in source.splitlines():
        if line.startswith('VERSION'):
            version = line.split('"')[1]
            break

    # Пушим в публичный репо
    print(f"\n[*] Пушу в публичный репо (v{version})...")
    import subprocess
    r = subprocess.run(
        ["git", "add", "roblox_keeper.py"],
        cwd=DIST
    )
    r = subprocess.run(
        ["git", "commit", "-m", f"v{version}"],
        cwd=DIST, capture_output=True, text=True
    )
    if "nothing to commit" in r.stdout + r.stderr:
        print("[!] Изменений нет, пуш пропущен.")
    else:
        subprocess.run(["git", "push"], cwd=DIST)
        print(f"[+] Запушено: v{version}")

if __name__ == "__main__":
    build()
