"""Skapar en eller flera UNIKA köpkoder till det kodskyddade sjökortet.

Varje kod är slumpmässig och egen för en köpare. Skriptet:
  * lägger till en inslagen nyckel per kod i docs/access/codes.json (checkas in),
  * antecknar koden i klartext i source/issued_codes.csv (din lokala liggare,
    checkas INTE in), så du vet vilken kod som gått till vem.

Användning:
  py -3 scripts/mint_code.py                 # en kod
  py -3 scripts/mint_code.py --count 10      # tio koder
  py -3 scripts/mint_code.py --note "Kalle"  # med anteckning i liggaren

Skicka den utskrivna koden till köparen via SMS eller mail. Publicera sedan
ändringen i codes.json (git add docs/access/codes.json && git commit && git push).

Att SPÄRRA en kod: leta upp raden i source/issued_codes.csv, ta bort motsvarande
entry (samma "label") ur docs/access/codes.json och pusha. Se README.md.
"""
import argparse
import csv
import secrets
from datetime import date

import access

# Teckenuppsättning utan lättförväxlade tecken (0/O, 1/I/L).
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUPS = 3
GROUP_LEN = 4  # RUNN-XXXX-XXXX-XXXX ≈ 60 bitars entropi

LEDGER_PATH = access.ROOT / "source" / "issued_codes.csv"


def generate_code() -> str:
    groups = [
        "".join(secrets.choice(ALPHABET) for _ in range(GROUP_LEN))
        for _ in range(GROUPS)
    ]
    return "RUNN-" + "-".join(groups)


def append_ledger(rows):
    new_file = not LEDGER_PATH.exists()
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["label", "code", "issued", "note"])
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=1, help="Antal koder att skapa (standard 1)")
    parser.add_argument("--note", default="", help="Valfri anteckning till liggaren (t.ex. köparens namn)")
    args = parser.parse_args()

    master_key = access.load_or_create_master_key()
    codes = access.load_codes()

    today = date.today().isoformat()
    existing_labels = [e.get("label", "") for e in codes["entries"]]
    seq = len([lbl for lbl in existing_labels if lbl.startswith(today)]) + 1

    minted, ledger_rows = [], []
    for _ in range(args.count):
        code = generate_code()
        label = f"{today} #{seq}"
        seq += 1
        entry = access.wrap_master_key(master_key, code, codes)
        entry["label"] = label
        codes["entries"].append(entry)
        minted.append(code)
        ledger_rows.append([label, code, today, args.note])

    access.save_codes(codes)
    append_ledger(ledger_rows)

    print(f"\nSkapade {len(minted)} kod(er). Totalt aktiva koder: {len(codes['entries'])}\n")
    for code in minted:
        print("   " + code)
    print(
        "\nSkicka koden till köparen. Publicera sedan:\n"
        "   git add docs/access/codes.json\n"
        '   git commit -m "Ny köpkod"\n'
        "   git push\n"
        f"Liggare uppdaterad: {LEDGER_PATH}"
    )


if __name__ == "__main__":
    main()
