#!/usr/bin/env python3
"""
extract_pdfs.py
Pipeline de extracción de texto desde PDFs (orientado a dataset en ESPAÑOL).

Características:
 - Si no hay PDFs en la carpeta, informa y termina sin error.
 - Detecta si Tesseract (OCR) y pdftoppm (Poppler) están disponibles; si faltan,
   el fallback OCR se desactiva automáticamente y se lo registra.
 - Resume automático: no reprocesa PDFs ya extraídos (compara md5).
 - Genera:
    - extracted_text/<doc_id>.txt
    - metadata/metadata.jsonl  (un JSON por línea)
    - logs/extract.log
"""

import os
import sys
import json
import hashlib
import logging
import unicodedata
from pathlib import Path
from tqdm import tqdm
import re
import shutil

# imports opcionales — si faltan, pip install los paquetes en tu venv:
try:
    import pdfplumber
except Exception as e:
    pdfplumber = None
    # no hacemos exit; lo reportamos después

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
except Exception:
    detect = None

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "pdfs"
OUT_TEXT_DIR = BASE_DIR / "extracted_text"
META_DIR = BASE_DIR / "metadata"
LOG_DIR = BASE_DIR / "logs"
META_FILE = META_DIR / "metadata.jsonl"

MIN_TEXT_LENGTH_FOR_NO_OCR = 150  # si pdfplumber extrae menos que esto -> intentar OCR (si está disponible)
DPI_FOR_OCR = 200
TESSERACT_LANG = "spa"            # dataset en español
TESSERACT_CONFIG = "--oem 1 --psm 3"  # engine y segmentación de página
# ----------------------------

# Crear carpetas necesarias
for d in (PDF_DIR, OUT_TEXT_DIR, META_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# logging
logging.basicConfig(
    filename=str(LOG_DIR / "extract.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)


def file_md5(path: Path, block_size: int = 65536) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            h.update(block)
    return h.hexdigest()


def clean_text(text: str) -> str:
    """
    Limpieza orientada a textos en español:
    - normaliza saltos de línea en párrafos
    - elimina cortes por guion al final de línea (guiones por separación de palabra)
    - normaliza unicode (NFC)
    - reduce saltos múltiples
    """
    if not text:
        return ""

    # normalizar unicode (acentos, etc.)
    text = unicodedata.normalize("NFC", text)

    # reemplazar \r\n y \r por \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # eliminar guiones por corte de línea: "par-\nte" -> "parte"
    text = re.sub(r"(?i)(\w)-\n(\w)", r"\1\2", text)

    # unir saltos de línea que no separan párrafos:
    lines = text.split("\n")
    new_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            new_lines.append("")  # párrafo vacío
            continue
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if next_line and next_line.strip() and re.match(r"^[a-záéíóúñü]", next_line.strip(), flags=re.IGNORECASE):
            new_lines.append(stripped + " ")
        else:
            new_lines.append(stripped + "\n")
    text = "".join(new_lines)

    # colapsar saltos múltiples y espacios
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    return text


def extract_text_pdfplumber(path: Path) -> str:
    if pdfplumber is None:
        logging.warning("pdfplumber no está instalado — no se puede extraer texto nativo.")
        return ""
    text_parts = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                try:
                    p_text = page.extract_text()
                except Exception as e:
                    logging.debug("pdfplumber page extract error: %s", e)
                    p_text = None
                if p_text:
                    text_parts.append(p_text)
    except Exception as e:
        logging.warning("pdfplumber failed for %s: %s", path.name, e)
    return "\n\n".join(text_parts)


def ocr_pdf(path: Path, dpi: int = DPI_FOR_OCR, poppler_available: bool = True) -> str:
    """
    Convierte a imagen y hace OCR por página. Requiere:
    - pdf2image (convert_from_path)
    - pdftoppm (poppler) en PATH O pasar poppler_path
    - pytesseract y tesseract en PATH
    """
    if convert_from_path is None:
        logging.warning("pdf2image no instalado — OCR no disponible.")
        return ""
    if pytesseract is None:
        logging.warning("pytesseract no instalado — OCR no disponible.")
        return ""
    if not poppler_available:
        logging.warning("Poppler (pdftoppm) no disponible — OCR no posible.")
        return ""

    text_parts = []
    try:
        # convert_from_path usará pdftoppm desde PATH
        images = convert_from_path(str(path), dpi=dpi)
        for img in images:
            try:
                img_grey = img.convert("L")
            except Exception:
                img_grey = img
            try:
                txt = pytesseract.image_to_string(img_grey, lang=TESSERACT_LANG, config=TESSERACT_CONFIG)
            except Exception as e:
                logging.warning("pytesseract failed on page image: %s", e)
                txt = ""
            if txt:
                text_parts.append(txt)
    except Exception as e:
        logging.error("OCR failed for %s: %s", path.name, e)
    return "\n\n".join(text_parts)


def detect_language_safe(text: str) -> str:
    if not text or len(text) < 50:
        return "es"  # forzamos 'es' porque tu dataset es español
    if detect is None:
        return "es"
    try:
        lang = detect(text)
        if lang and lang.startswith("es"):
            return "es"
        return lang
    except Exception:
        return "es"


def already_processed(path: Path, md5: str) -> bool:
    if not META_FILE.exists():
        return False
    try:
        with open(META_FILE, "r", encoding="utf8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                    if m.get("filename") == path.name and m.get("md5") == md5:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def process_pdf(path: Path, allow_ocr: bool, poppler_available: bool) -> dict:
    """
    Procesa un PDF y retorna el metadata dict.
    Guarda el .txt en OUT_TEXT_DIR.
    """
    doc_id = path.stem
    out_txt = OUT_TEXT_DIR / f"{doc_id}.txt"
    md5 = file_md5(path)
    stat = path.stat()

    if already_processed(path, md5):
        logging.info("Skipping %s (already extracted)", path.name)
        # leer y devolver la metadata existente si quieres, pero aquí devolvemos resumen
        return {
            "doc_id": doc_id,
            "filename": path.name,
            "md5": md5,
            "skipped": True
        }

    # 1) intento extracción textual
    raw_text = extract_text_pdfplumber(path)
    used_method = "pdfplumber"

    # 2) fallback a OCR si es necesario y permitido
    if (not raw_text or len(raw_text.strip()) < MIN_TEXT_LENGTH_FOR_NO_OCR) and allow_ocr:
        logging.info("Text too short (%s) for %s -> trying OCR", len(raw_text or ""), path.name)
        ocr_text = ocr_pdf(path, dpi=DPI_FOR_OCR, poppler_available=poppler_available)
        if ocr_text and len(ocr_text.strip()) > len(raw_text or ""):
            raw_text = ocr_text
            used_method = "ocr"
        else:
            logging.info("OCR didn't improve or failed for %s", path.name)
    else:
        if (not raw_text or len(raw_text.strip()) < MIN_TEXT_LENGTH_FOR_NO_OCR) and not allow_ocr:
            logging.info("Text short but OCR disabled or not available for %s; keeping extracted text (may be empty).", path.name)

    cleaned = clean_text(raw_text or "")

    # detectar idioma (opcional)
    lang = detect_language_safe(cleaned)

    # guardar .txt
    try:
        with out_txt.open("w", encoding="utf8") as f:
            f.write(cleaned)
    except Exception as e:
        logging.error("Failed to write text for %s : %s", path.name, e)

    # metadata
    metadata = {
        "doc_id": doc_id,
        "filename": path.name,
        "md5": md5,
        "bytes": stat.st_size,
        "pages": None,
        "extract_method": used_method,
        "text_len": len(cleaned),
        "lang": lang,
        "txt_path": str(out_txt.relative_to(BASE_DIR)),
    }

    # intentar rellenar pages y metadatos si pdfplumber puede
    try:
        if pdfplumber is not None:
            with pdfplumber.open(str(path)) as pdf:
                metadata["pages"] = len(pdf.pages)
                pdf_meta = pdf.metadata or {}
                if pdf_meta:
                    metadata["pdf_metadata"] = {k: str(v) for k, v in pdf_meta.items()}
    except Exception:
        pass

    # append metadata a metadata.jsonl
    try:
        with open(META_FILE, "a", encoding="utf8") as mf:
            mf.write(json.dumps(metadata, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error("Could not write metadata for %s: %s", path.name, e)

    logging.info("Processed %s -> %s (len=%d, method=%s)", path.name, out_txt.name, metadata["text_len"], used_method)
    return metadata


def main():
    # Detectar disponibilidad de herramientas externas
    tesseract_path = shutil.which("tesseract")
    poppler_path = shutil.which("pdftoppm")  # pdftoppm viene con Poppler
    allow_ocr = bool(tesseract_path and pytesseract is not None and convert_from_path is not None)
    poppler_available = bool(poppler_path and convert_from_path is not None)

    if not tesseract_path:
        logging.warning("Tesseract no encontrado en PATH. OCR desactivado. Instala Tesseract si necesitas OCR.")
    else:
        logging.info("Tesseract encontrado: %s", tesseract_path)

    if not poppler_path:
        logging.warning("pdftoppm (Poppler) no encontrado en PATH. OCR con pdf2image puede fallar.")
    else:
        logging.info("pdftoppm (Poppler) encontrado: %s", poppler_path)

    # Recolectar PDFs (busca recursivamente, mayúsculas/minúsculas)
    pdf_files = sorted([p for p in PDF_DIR.rglob("*") if p.suffix.lower() == ".pdf"])
    if not pdf_files:
        logging.info("No PDFs found in %s. Nothing to do.", PDF_DIR)
        return 0

    logging.info("Found %d pdf(s) to process in %s", len(pdf_files), PDF_DIR)

    results = []
    try:
        for p in tqdm(pdf_files, desc="Procesando PDFs"):
            try:
                m = process_pdf(p, allow_ocr=allow_ocr, poppler_available=poppler_available)
                results.append(m)
            except Exception as e:
                logging.exception("Error processing %s: %s", p.name, e)
    except KeyboardInterrupt:
        logging.warning("Procesamiento interrumpido por el usuario.")
    logging.info("Done. Processed %d files.", len(results))
    return 0


if __name__ == "__main__":
    rc = main()
    # Exit con código 0 (ok) o rc si necesitas (ahora rc será 0 en ejecución normal)
    sys.exit(rc)