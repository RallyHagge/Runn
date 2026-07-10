"""Delade krypto-hjälpfunktioner för det kodskyddade sjökortet.

Modell (ingen server behövs):
  * Alla kartrutor krypteras med EN slumpmässig huvudnyckel K (AES-256-GCM).
    K ligger i source/master.key och lämnar aldrig din dator / repot.
  * Varje köpkod låser upp K: K "slås in" (wrappas) under en nyckel som
    härleds ur koden med PBKDF2. De inslagna kopiorna ligger i
    docs/access/codes.json (ofarligt publikt — värdelöst utan en giltig kod).
  * I webbläsaren skriver kunden sin kod, K packas upp och rutorna
    dekrypteras lokalt. Ingen inloggning kopplas till mail eller lösenord.

Att lägga till en köpare = köra scripts/mint_code.py (en rad läggs till i
codes.json). Att spärra en kod = ta bort dess rad. Se README.md.
"""
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Dessa parametrar MÅSTE stämma överens med webbläsarkoden i docs/app.js.
PBKDF2_ITERATIONS = 150_000
KDF_SALT_BYTES = 16
KEY_BYTES = 32  # AES-256
IV_BYTES = 12   # GCM-standard

ROOT = Path(__file__).resolve().parent.parent
MASTER_KEY_PATH = ROOT / "source" / "master.key"   # hemlig, gitignore:ad
CODES_PATH = ROOT / "docs" / "access" / "codes.json"  # publik, wrappade nycklar


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


def load_or_create_master_key(path: Path = MASTER_KEY_PATH) -> bytes:
    """Läser huvudnyckeln K, eller skapar en ny om den saknas. K måste vara
    samma vid kryptering av rutor och vid utfärdande av koder, så filen ska
    behållas (och hållas hemlig). Radera den bara om du medvetet vill byta
    nyckel — då måste alla rutor krypteras om och alla koder utfärdas på nytt."""
    if path.exists():
        return unb64(path.read_text(encoding="ascii").strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(KEY_BYTES)
    path.write_text(b64(key), encoding="ascii")
    print(f"Skapade ny huvudnyckel: {path} (HEMLIG — checka aldrig in den)")
    return key


def load_codes(path: Path = CODES_PATH) -> dict:
    """Läser codes.json, eller skapar strukturen (med ett fast KDF-salt) om den
    saknas."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "cipher": "AES-GCM",
        "kdf": {
            "algo": "PBKDF2-HMAC-SHA256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": b64(os.urandom(KDF_SALT_BYTES)),
        },
        "entries": [],
    }


def save_codes(codes: dict, path: Path = CODES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(codes, indent=2, ensure_ascii=False), encoding="utf-8")


def _derive_kek(code: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(code.encode("utf-8"))


def wrap_master_key(master_key: bytes, code: str, codes: dict) -> dict:
    """Slår in huvudnyckeln under en kod och returnerar en entry för codes.json."""
    salt = unb64(codes["kdf"]["salt"])
    kek = _derive_kek(code, salt, codes["kdf"]["iterations"])
    iv = os.urandom(IV_BYTES)
    data = AESGCM(kek).encrypt(iv, master_key, None)
    return {"iv": b64(iv), "data": b64(data)}


def encrypt_bytes(master_key: bytes, plaintext: bytes) -> bytes:
    """Krypterar godtyckliga bytes (t.ex. en JPEG-ruta): returnerar iv || ciphertext+tag."""
    iv = os.urandom(IV_BYTES)
    return iv + AESGCM(master_key).encrypt(iv, plaintext, None)
