#!/usr/bin/env python3
"""
download_dataset_with_metadata.py (nueva versión con títulos arXiv)

Descarga PDFs variados (arXiv por topics + fuentes públicas) hasta alcanzar TARGET_MB.
Cuando la fuente es arXiv, guarda el PDF con el título del paper (prefijado por el arXiv id)
Ejemplo de saved_name: "2306.04338v1 - Transformers for Image Classification.pdf"

Uso:
  python download_dataset_with_metadata.py

Requisitos:
  pip install requests
"""

import re
import time
import json
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse, quote_plus
from datetime import datetime

import requests

# ========== CONFIG ==========
TARGET_MB = 50
TARGET_BYTES = TARGET_MB * 1024 * 1024
DEST_DIR = Path("pdfs")
DEST_DIR.mkdir(exist_ok=True)
METADATA_FILE = DEST_DIR / "metadata.jsonl"

HEADERS = {"User-Agent": "ZenithDatasetDownloader/1.0"}

ARXIV_API = "http://export.arxiv.org/api/query?search_query=all:{}&start={}&max_results={}"

TOPICS = [
    "machine learning", "biology", "physics", "mathematics", "art history",
    "astronomy", "chemistry", "neuroscience", "philosophy", "economics"
]

PUBLIC_PDFS = [
    "https://www.nasa.gov/sites/default/files/atoms/files/nasa_sp-2016-6105.pdf",
    "https://www.nasa.gov/sites/default/files/atoms/files/nasa_earth_science_vision_2050.pdf",
]

ARXIV_BATCH = 20
MAX_PER_TOPIC = 60
API_DELAY = 1.0
# ============================

INVALID_CHARS_RE = re.compile(r'[^A-Za-z0-9ñÑáéíóúÁÉÍÓÚüÜ \.\-_()]')

def parse_filename_from_cd(content_disp: str):
    """Extrae filename desde Content-Disposition (si existe)."""
    if not content_disp:
        return None
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", content_disp, flags=re.IGNORECASE)
    if m:
        name = m.group(1).strip().strip('"')
        try:
            name = unquote(name)
        except Exception:
            pass
        return name
    m2 = re.search(r'filename=\"?([^\";]+)\"?', content_disp, flags=re.IGNORECASE)
    if m2:
        name = m2.group(1).strip().strip('"')
        try:
            name = unquote(name)
        except Exception:
            pass
        return name
    return None

def sanitize_filename(name: str, max_len: int = 200) -> str:
    """Sanea y trunca un nombre de archivo, asegura extensión .pdf"""
    if not name:
        base = "document"
        ext = ".pdf"
    else:
        name = name.strip()
        parsed = Path(name)
        base = parsed.stem or "document"
        ext = parsed.suffix or ".pdf"
        if not ext.lower().endswith(".pdf"):
            ext = ".pdf"
    # eliminar chars inválidos
    base = re.sub(INVALID_CHARS_RE, "", base)
    base = re.sub(r"\s+", " ", base).strip()
    max_base = max_len - len(ext)
    if len(base) > max_base:
        base = base[:max_base]
    safe = f"{base}{ext}"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    return safe

def unique_path(dest_dir: Path, candidate_name: str) -> Path:
    """Si existe candidate_name, añade sufijo -1, -2, ... para hacerlo único."""
    dest = dest_dir / candidate_name
    if not dest.exists():
        return dest
    base, ext = candidate_name.rsplit(".", 1) if "." in candidate_name else (candidate_name, "pdf")
    i = 1
    while True:
        new_name = f"{base}-{i}.{ext}"
        dest = dest_dir / new_name
        if not dest.exists():
            return dest
        i += 1

def compute_md5(path: Path, block_size: int = 65536) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            h.update(block)
    return h.hexdigest()

# ---- arXiv parsing: devolvemos lista de dicts {url, arxiv_id, title}
def parse_arxiv_entries(feed_xml_text: str):
    """Extrae (pdf_url, arxiv_id, title) de cada <entry> del feed"""
    entries = []
    parts = feed_xml_text.split("<entry>")
    for part in parts[1:]:
        try:
            # id
            if "<id>" in part:
                pid = part.split("<id>")[1].split("</id>")[0].strip()
                # pid example: http://arxiv.org/abs/2306.04338v1
                arxiv_id = pid.rstrip("/").split("/")[-1]
                pdf_url = pid.replace("abs", "pdf") + ".pdf"
            else:
                continue
            # title (limpiar tags)
            title = "untitled"
            if "<title>" in part:
                raw_title = part.split("<title>")[1].split("</title>")[0].strip()
                # eliminar saltos de línea y espacios extras
                title = " ".join(raw_title.split())
            entries.append({"url": pdf_url, "arxiv_id": arxiv_id, "title": title})
        except Exception:
            continue
    return entries

def gather_arxiv_links(topics, per_topic=MAX_PER_TOPIC, batch=ARXIV_BATCH):
    all_entries = []
    seen_urls = set()
    for topic in topics:
        print(f"\n🔎 Buscando en arXiv: '{topic}'")
        start = 0
        collected = 0
        while collected < per_topic:
            query = quote_plus(topic)
            url = ARXIV_API.format(query, start, batch)
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
                if r.status_code != 200:
                    print(f"  ⚠ arXiv API devolvió {r.status_code}, deteniendo topic '{topic}'")
                    break
                entries = parse_arxiv_entries(r.text)
                if not entries:
                    break
                for e in entries:
                    if e["url"] not in seen_urls:
                        # construir candidate_name a partir de id + title
                        # ejemplo: "2306.04338v1 - A great title.pdf"
                        safe_title = sanitize_filename(e["title"])
                        candidate_name = f"{e['arxiv_id']} - {safe_title}"
                        e["preferred_name"] = candidate_name  # sin extensión; sanitize function later adds .pdf
                        all_entries.append(e)
                        seen_urls.add(e["url"])
                        collected += 1
                        if collected >= per_topic:
                            break
                start += batch
                time.sleep(API_DELAY)
            except Exception as ex:
                print(f"  ⚠ Error consultando arXiv: {ex}")
                break
        print(f"  → {collected} enlaces recogidos para '{topic}'")
    return all_entries

def head_content_length(url: str):
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=12)
        if r.status_code >= 400:
            return None
        cl = r.headers.get("content-length")
        if cl and cl.isdigit():
            return int(cl)
    except Exception:
        pass
    return None

def download_pdf_with_original_name(url: str, dest_dir: Path, session: requests.Session, preferred_name: str = None):
    """
    Descarga URL, si preferred_name se pasa, lo usa para saved_name (titulo).
    De lo contrario usa Content-Disposition o URL.
    """
    try:
        resp = session.get(url, headers=HEADERS, stream=True, timeout=40)
    except Exception as e:
        print(f"  ❌ Error de conexión: {e}")
        return None

    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code} para {url}")
        return None

    # Determinar original_name desde header o URL (para metadata)
    cd = resp.headers.get("content-disposition", "")
    original_name = parse_filename_from_cd(cd)
    if not original_name:
        try:
            parsed = urlparse(url)
            original_name = unquote(Path(parsed.path).name) or "document.pdf"
        except Exception:
            original_name = "document.pdf"

    # Si el caller pasó preferred_name (por ejemplo título arXiv), lo usamos como base para el saved_name.
    if preferred_name:
        # preferred_name puede venir ya saneado parcialmente; aseguramos ext y sanitize
        candidate = sanitize_filename(preferred_name + ".pdf")
    else:
        candidate = sanitize_filename(original_name)

    dest_path = unique_path(dest_dir, candidate)

    tmp = dest_path.with_suffix(dest_path.suffix + ".part")
    bytes_written = 0
    try:
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    bytes_written += len(chunk)
        tmp.replace(dest_path)
    except Exception as e:
        print(f"  ❌ Error escribiendo archivo: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    md5 = compute_md5(dest_path)
    meta = {
        "url": url,
        "original_name": original_name,
        "saved_name": dest_path.name,
        "path": str(dest_path.resolve()),
        "bytes": bytes_written,
        "md5": md5,
        "content_type": resp.headers.get("content-type"),
        "fetched_at": datetime.utcnow().isoformat() + "Z"
    }
    return meta

def append_metadata(meta: dict, metadata_file: Path):
    try:
        with open(metadata_file, "a", encoding="utf8") as mf:
            mf.write(json.dumps(meta, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  ❌ Error guardando metadata: {e}")

def main():
    print("🚀 Iniciando descarga del dataset (objetivo {} MB)".format(TARGET_MB))
    total = 0
    # cargar metadata existente para no duplicar por md5/filename
    known_md5 = set()
    known_saved = set()
    if METADATA_FILE.exists():
        try:
            for line in METADATA_FILE.read_text(encoding="utf8").splitlines():
                if not line.strip():
                    continue
                j = json.loads(line)
                if j.get("md5"):
                    known_md5.add(j["md5"])
                if j.get("saved_name"):
                    known_saved.add(j["saved_name"])
                total += int(j.get("bytes", 0))
        except Exception:
            pass

    print("  Ya descargado (según metadata): {:.2f} MB".format(total / 1024 / 1024))

    # reunir candidatos (con preferred_name cuando venga de arXiv)
    arxiv_entries = gather_arxiv_links(TOPICS)
    candidates = []
    for e in arxiv_entries:
        # cada e es dict con keys url, arxiv_id, title, preferred_name
        candidates.append({"url": e["url"], "preferred_name": e.get("preferred_name")})
    # añadir fuentes públicas (sin preferred_name)
    for u in PUBLIC_PDFS:
        candidates.append({"url": u, "preferred_name": None})

    print("\n📋 Candidatos totales:", len(candidates))

    session = requests.Session()

    for item in candidates:
        if total >= TARGET_BYTES:
            break
        url = item["url"]
        preferred = item.get("preferred_name")
        print("\n➡ Procesando:", url)
        cl = head_content_length(url)
        if cl is not None and cl + total > TARGET_BYTES:
            print(f"  ↳ Saltando (content-length {cl} bytes excede objetivo restante).")
            continue
        meta = download_pdf_with_original_name(url, DEST_DIR, session, preferred_name=preferred)
        if not meta:
            print("  ↳ Descarga fallida o no es PDF válido.")
            continue
        # evitar duplicados por contenido
        if meta["md5"] in known_md5:
            print("  ↳ Archivo duplicado por contenido (md5), eliminado.")
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except Exception:
                pass
            continue
        append_metadata(meta, METADATA_FILE)
        known_md5.add(meta["md5"])
        known_saved.add(meta["saved_name"])
        total += int(meta["bytes"])
        print("  ↳ Guardado:", meta["saved_name"], f"({round(meta['bytes']/1024/1024,2)} MB)")
        print("  ↳ Total acumulado: {:.2f} MB".format(total / 1024 / 1024))
        time.sleep(0.8)

    print("\n✅ Proceso finalizado. Total descargado: {:.2f} MB".format(total / 1024 / 1024))
    print("📁 Archivos en:", str(DEST_DIR.resolve()))
    print("📄 Metadata:", str(METADATA_FILE.resolve()))

if __name__ == "__main__":
    main()