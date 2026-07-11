"""Bearbetar en georefererad export av sjökortet (KMZ eller bild + world-fil)
till det webbappen visar: antingen en tile-pyramid (docs/chart/tiles/) eller en
enkel bild (docs/chart/chart.jpg), plus docs/chart/bounds.json.

Användning:
  Bild + world-fil, full upplösning som tiles (REKOMMENDERAT för sjökortet):
    py -3 scripts/prepare_chart.py source/chart.png --epsg 3021 --tiles

  Bild + world-fil, en enkel nedskalad bild (enklare men lägre upplösning):
    py -3 scripts/prepare_chart.py source/chart.png --epsg 3021

  KMZ-export (redan i WGS84):
    py -3 scripts/prepare_chart.py source/karta.kmz

EPSG-koden anger bildens koordinatsystem. För Runn-sjökortet är det 3021
(RT90 2,5 gon V). Andra vanliga: 3006 = SWEREF99 TM, 4326 = WGS84/lat-long.
Skriptet omprojicerar allt till Web Mercator (EPSG:3857) som webbkartor använder.

Skriptet letar automatiskt efter en world-fil med samma namn som bilden
(.pgw/.pngw för .png, .jgw för .jpg/.jpeg, .tfw för .tif/.tiff).

Kräver Python-paketen i requirements.txt: pillow, pyproj, rasterio.
"""
import argparse
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

# Kartexporter är stora men betrodda lokala filer — höj Pillows bombskydd.
Image.MAX_IMAGE_PIXELS = 400_000_000

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "chart"
JPEG_QUALITY = 85
MAX_DIMENSION = 8000  # skala ner om längsta sidan överstiger detta, för rimlig filstorlek

# Tile-pyramid (Web Mercator / XYZ, 256×256):
TILE_SIZE = 256
WEB_MERCATOR_R = 20037508.342789244  # halva jordens omkrets i EPSG:3857-meter
TILE_MIN_ZOOM = 8
TILE_MAX_ZOOM = 16  # källan är ~1 m/px ≈ z16; högre zoom skulle bara uppsampla
TILE_JPEG_QUALITY = 80


def save_chart_image(img: Image.Image) -> None:
    img = img.convert("RGB")
    if max(img.size) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(img.size)
        new_size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        print(f"Skalar om bilden till {new_size[0]}x{new_size[1]} px")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "chart.jpg"
    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Skrev {out_path} ({img.width}x{img.height} px, {size_mb:.1f} MB)")


def write_bounds(south: float, west: float, north: float, east: float) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "bounds.json"
    data = {"south": south, "west": west, "north": north, "east": east}
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Skrev {out_path}: {data}")


def handle_kmz(path: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            sys.exit("Hittade ingen .kml inuti KMZ-filen.")
        kml_text = zf.read(kml_names[0]).decode("utf-8", errors="replace")

        def grab(tag: str) -> float:
            m = re.search(rf"<{tag}>\s*([-\d.]+)\s*</{tag}>", kml_text)
            if not m:
                sys.exit(f"Hittade ingen <{tag}> i KML-filen (förväntade en LatLonBox).")
            return float(m.group(1))

        north = grab("north")
        south = grab("south")
        east = grab("east")
        west = grab("west")

        img_names = [
            n for n in zf.namelist()
            if n.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff"))
        ]
        if not img_names:
            sys.exit("Hittade ingen bildfil inuti KMZ-filen.")
        # Ta den största bildfilen om det finns flera (t.ex. ikoner för legend).
        img_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
        with zf.open(img_names[0]) as f:
            img = Image.open(f)
            img.load()

    save_chart_image(img)
    write_bounds(south, west, north, east)


WORLD_FILE_EXTENSIONS = {
    ".png": ".pgw",
    ".jpg": ".jgw",
    ".jpeg": ".jgw",
    ".tif": ".tfw",
    ".tiff": ".tfw",
}


def find_world_file(image_path: Path) -> Path:
    ext = image_path.suffix.lower()
    candidates = []
    if ext in WORLD_FILE_EXTENSIONS:
        candidates.append(image_path.with_suffix(WORLD_FILE_EXTENSIONS[ext]))
    candidates.append(image_path.with_suffix(image_path.suffix + "w"))
    for c in candidates:
        if c.exists():
            return c
    sys.exit(
        f"Hittade ingen world-fil för {image_path.name}. "
        f"Sökte efter: {', '.join(c.name for c in candidates)}"
    )


def reproject_to_web_mercator(img, src_transform, epsg):
    """Warpar bilden från käll-CRS (EPSG:`epsg`) till Web Mercator (EPSG:3857) så att
    den matchar Leaflets interna projektion pixel för pixel. Returnerar (PIL-bild,
    (south, west, north, east)). Detta tar bort rutnätsrotationen och olinjäriteten
    som annars ger några tiotals meters fel vid kartkanterna."""
    import numpy as np
    from rasterio.crs import CRS
    from rasterio.warp import (
        Resampling,
        calculate_default_transform,
        reproject,
        transform_bounds,
    )

    src_crs = CRS.from_epsg(epsg)
    dst_crs = CRS.from_epsg(3857)
    arr = np.asarray(img.convert("RGB"))  # (H, W, 3)
    height, width = arr.shape[:2]

    # Källans utsträckning i käll-CRS (från world-filens affina transform).
    left = src_transform.c
    top = src_transform.f
    right = left + width * src_transform.a
    bottom = top + height * src_transform.e  # e (px-höjd) är normalt negativt

    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, dst_crs, width, height,
        left=left, bottom=bottom, right=right, top=top,
    )

    # Fyll med vitt (255) så de små kilarna vid hörnen — som uppstår för att en
    # roterad källruta inte fyller den axelparallella målrutan — smälter in mot
    # sjökortets vita bakgrund i stället för att bli svarta trianglar.
    dst = np.full((3, dst_h, dst_w), 255, dtype=np.uint8)
    for i in range(3):
        reproject(
            source=np.ascontiguousarray(arr[:, :, i]),
            destination=dst[i],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            init_dest_nodata=False,  # behåll vår vita fyllning i hörnkilarna
        )

    warped = Image.fromarray(np.transpose(dst, (1, 2, 0)), "RGB")

    # Målrutan är axelparallell i EPSG:3857, så dess hörn ger en exakt lat/long-ruta.
    m_left = dst_transform.c
    m_top = dst_transform.f
    m_right = m_left + dst_w * dst_transform.a
    m_bottom = m_top + dst_h * dst_transform.e
    west, south, east, north = transform_bounds(
        dst_crs, CRS.from_epsg(4326), m_left, m_bottom, m_right, m_top
    )
    return warped, (south, west, north, east)


def _write_source_geotiff(img, src_transform, epsg, dst_path):
    """Skriver käll-PIL-bilden som en georefererad GeoTIFF (i käll-CRS) med
    översiktsnivåer, så tile-genereringen kan läsa nedskalade utsnitt snabbt."""
    import numpy as np
    import rasterio
    from rasterio.crs import CRS
    from rasterio.enums import Resampling

    arr = np.asarray(img.convert("RGB"))  # (H, W, 3)
    height, width = arr.shape[:2]
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 3,
        "dtype": "uint8",
        "crs": CRS.from_epsg(epsg),
        "transform": src_transform,
        "photometric": "RGB",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "DEFLATE",
    }
    with rasterio.open(dst_path, "w", **profile) as dst:
        for i in range(3):
            dst.write(np.ascontiguousarray(arr[:, :, i]), i + 1)
        dst.build_overviews([2, 4, 8, 16, 32, 64], Resampling.average)


def _tile_bounds_3857(x, y, z):
    """Web Mercator-gränser (minx, miny, maxx, maxy) för en XYZ-tile."""
    span = 2 * WEB_MERCATOR_R / (2 ** z)
    minx = -WEB_MERCATOR_R + x * span
    maxy = WEB_MERCATOR_R - y * span
    return minx, maxy - span, minx + span, maxy


def generate_tiles(img, src_transform, epsg, encrypt=False):
    """Genererar en XYZ-tile-pyramid i docs/chart/tiles/ genom att warpa källan
    till Web Mercator on-the-fly. Returnerar WGS84-gränserna (south, west, north, east).

    Med encrypt=True krypteras varje ruta med huvudnyckeln (AES-256-GCM) och sparas
    som .bin i stället för .jpg — då kan kartan bara läsas med en giltig köpkod."""
    import numpy as np
    import rasterio
    from rasterio.crs import CRS
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds as transform_from_bounds
    from rasterio.warp import reproject, transform_bounds

    master_key = None
    if encrypt:
        import access
        master_key = access.load_or_create_master_key()

    dst_crs = CRS.from_epsg(3857)
    tiles_root = OUT_DIR / "tiles"
    if tiles_root.exists():
        shutil.rmtree(tiles_root)
    ext = "bin" if encrypt else "jpg"
    manifest_tiles = []  # webbrelativa sökvägar för service workerns offline-cache

    tmp_dir = Path(tempfile.mkdtemp(prefix="chart_tiles_"))
    src_tif = tmp_dir / "src.tif"
    try:
        print("Skriver temporär GeoTIFF med översiktsnivåer...")
        _write_source_geotiff(img, src_transform, epsg, src_tif)

        with rasterio.open(src_tif) as src:
            # Kartans utsträckning i Web Mercator resp. WGS84.
            left, bottom, right, top = transform_bounds(src.crs, dst_crs, *src.bounds)
            west, south, east, north = transform_bounds(src.crs, CRS.from_epsg(4326), *src.bounds)
            src_bands = [rasterio.band(src, i + 1) for i in range(3)]

            total = 0
            for z in range(TILE_MIN_ZOOM, TILE_MAX_ZOOM + 1):
                span = 2 * WEB_MERCATOR_R / (2 ** z)
                x0 = int((left + WEB_MERCATOR_R) / span)
                x1 = int((right + WEB_MERCATOR_R) / span)
                y0 = int((WEB_MERCATOR_R - top) / span)
                y1 = int((WEB_MERCATOR_R - bottom) / span)
                z_count = 0
                for tx in range(x0, x1 + 1):
                    for ty in range(y0, y1 + 1):
                        minx, miny, maxx, maxy = _tile_bounds_3857(tx, ty, z)
                        tile_transform = transform_from_bounds(
                            minx, miny, maxx, maxy, TILE_SIZE, TILE_SIZE
                        )
                        # Förfyll vitt så delar av rutan utanför kartan blir vita, inte svarta.
                        dst = np.full((3, TILE_SIZE, TILE_SIZE), 255, dtype=np.uint8)
                        for i in range(3):
                            reproject(
                                source=src_bands[i],
                                destination=dst[i],
                                dst_transform=tile_transform,
                                dst_crs=dst_crs,
                                resampling=Resampling.bilinear,
                                init_dest_nodata=False,
                            )
                        # Hoppa över tiles som är helt utanför kartan (bara vit fyllning).
                        if int(dst.min()) == 255:
                            continue
                        tile_dir = tiles_root / str(z) / str(tx)
                        tile_dir.mkdir(parents=True, exist_ok=True)
                        tile_img = Image.fromarray(np.transpose(dst, (1, 2, 0)), "RGB")
                        buf = io.BytesIO()
                        tile_img.save(buf, "JPEG", quality=TILE_JPEG_QUALITY, optimize=True)
                        if encrypt:
                            (tile_dir / f"{ty}.bin").write_bytes(
                                access.encrypt_bytes(master_key, buf.getvalue())
                            )
                        else:
                            (tile_dir / f"{ty}.jpg").write_bytes(buf.getvalue())
                        manifest_tiles.append(f"chart/tiles/{z}/{tx}/{ty}.{ext}")
                        z_count += 1
                total += z_count
                print(f"  z{z}: {z_count} rutor")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    pattern = "*.bin" if encrypt else "*.jpg"
    size_mb = sum(f.stat().st_size for f in tiles_root.rglob(pattern)) / (1024 * 1024)
    kind = "krypterade rutor (.bin)" if encrypt else "rutor (.jpg)"
    print(f"Skrev {total} {kind} till {tiles_root} ({size_mb:.1f} MB)")

    # Manifest för service workern (offline): lista över rutor + versionsstämpel.
    # Ny version vid varje körning gör att en uppdaterad karta laddas om offline.
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    manifest_path = OUT_DIR / "tiles-manifest.json"
    manifest_path.write_text(
        json.dumps({"version": version, "count": len(manifest_tiles), "tiles": manifest_tiles}),
        encoding="utf-8",
    )
    print(f"Skrev {manifest_path} (version {version})")
    return south, west, north, east


def handle_image_with_worldfile(path: Path, epsg: int, tiles: bool = False, encrypt: bool = False) -> None:
    world_path = find_world_file(path)
    values = [float(line.strip()) for line in world_path.read_text().splitlines() if line.strip()]
    if len(values) != 6:
        sys.exit(f"Förväntade 6 rader i world-filen {world_path}, hittade {len(values)}.")
    px_w, rot_y, rot_x, px_h, origin_x, origin_y = values

    img = Image.open(path)
    img.load()
    width, height = img.size

    if epsg == 4326:
        # Redan i lat/long — töjs korrekt av Leaflet utan omprojicering.
        min_x = origin_x - px_w / 2
        max_x = min_x + width * px_w
        max_y = origin_y - px_h / 2  # px_h är normalt negativt
        min_y = max_y + height * px_h
        save_chart_image(img)
        write_bounds(min_y, min_x, max_y, max_x)
        return

    try:
        from rasterio.transform import Affine
    except ImportError:
        sys.exit(
            "Behöver 'rasterio' för att omprojicera till Web Mercator. "
            "Installera med: py -3 -m pip install rasterio"
        )
    # Affin transform (kol, rad) -> (x, y) i käll-CRS. World-filens origin är centrum
    # av övre vänstra pixeln; rasterio vill ha övre vänstra hörnet.
    src_transform = Affine(
        px_w, rot_x, origin_x - px_w / 2,
        rot_y, px_h, origin_y - px_h / 2,
    )
    if tiles:
        extra = " (krypterat)" if encrypt else ""
        print(f"Genererar tile-pyramid från EPSG:{epsg} (z{TILE_MIN_ZOOM}–{TILE_MAX_ZOOM}){extra}...")
        south, west, north, east = generate_tiles(img, src_transform, epsg, encrypt=encrypt)
        write_bounds(south, west, north, east)
        return
    if encrypt:
        sys.exit("--encrypt kräver --tiles.")

    print(f"Omprojicerar från EPSG:{epsg} till Web Mercator (EPSG:3857)...")
    warped, (south, west, north, east) = reproject_to_web_mercator(img, src_transform, epsg)

    save_chart_image(warped)
    write_bounds(south, west, north, east)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Sökväg till .kmz eller bildfil (.png/.jpg/.tif)")
    parser.add_argument("--epsg", type=int, help="EPSG-kod för bildens koordinatsystem (krävs för bild+world-fil om det inte redan är EPSG:4326)")
    parser.add_argument(
        "--tiles",
        action="store_true",
        help="Generera en tile-pyramid (docs/chart/tiles/) i full upplösning i "
        "stället för en enda nedskalad bild. Rekommenderas för bästa skärpa.",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        help="Kryptera rutorna med huvudnyckeln så kartan bara kan läsas med en "
        "köpkod (kräver --tiles). Se scripts/mint_code.py och README.md.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Hittar inte filen: {args.input}")

    if args.input.suffix.lower() == ".kmz":
        handle_kmz(args.input)
    elif args.input.suffix.lower() in WORLD_FILE_EXTENSIONS:
        if args.epsg is None:
            sys.exit("Ange --epsg för bild + world-fil, t.ex. --epsg 3006 (SWEREF99 TM) eller --epsg 4326 (WGS84).")
        handle_image_with_worldfile(args.input, args.epsg, tiles=args.tiles, encrypt=args.encrypt)
    else:
        sys.exit(f"Filtypen stöds inte: {args.input.suffix}")


if __name__ == "__main__":
    main()
