from pathlib import Path
import json
import os
import re
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import faiss

BASE_DIR = Path(__file__).resolve().parent
CHUNKS_DIR = BASE_DIR / "chunks"
OUT_DIR = BASE_DIR / "embeddings"

MODEL_NAME = "intfloat/multilingual-e5-small"
BATCH_SIZE = 64


def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_chunks(chunks_dir: Path):
    """
    Lee todos los .txt dentro de chunks/.
    Cada archivo .txt se considera un chunk.
    """
    files = sorted(chunks_dir.rglob("*.txt"))
    chunks = []

    for idx, path in enumerate(files):
        raw_text = read_text_file(path)
        text = normalize_text(raw_text)

        if not text:
            continue

        chunks.append({
            "id": idx,
            "file_name": path.name,
            "relative_path": str(path.relative_to(chunks_dir)),
            "text": text,
            "length_chars": len(text),
            "length_words": len(text.split())
        })

    return chunks


def embed_texts(model: SentenceTransformer, texts, batch_size=BATCH_SIZE):
    """
    Usa el formato recomendado para E5:
    - passages: "passage: ..."
    - queries: "query: ..."
    """
    passages = [f"passage: {t}" for t in texts]
    embeddings = model.encode(
        passages,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embeddings.astype(np.float32)


def build_faiss_index(embeddings: np.ndarray):
    """
    Como normalizamos embeddings, usamos inner product = cosine similarity.
    """
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def save_jsonl(chunks, path: Path):
    with path.open("w", encoding="utf-8") as f:
        for item in chunks:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_manifest(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    ensure_dirs()

    if not CHUNKS_DIR.exists():
        raise FileNotFoundError(f"No existe la carpeta de chunks: {CHUNKS_DIR}")

    print("Cargando chunks...")
    chunks = load_chunks(CHUNKS_DIR)

    if not chunks:
        raise RuntimeError("No se encontraron chunks válidos (.txt) en la carpeta chunks/")

    print(f"Chunks encontrados: {len(chunks)}")

    texts = [c["text"] for c in chunks]

    print(f"Cargando modelo: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    print("Generando embeddings...")
    embeddings = embed_texts(model, texts, batch_size=BATCH_SIZE)

    if embeddings.shape[0] != len(chunks):
        raise RuntimeError("El número de embeddings no coincide con el número de chunks.")

    print("Construyendo índice FAISS...")
    index = build_faiss_index(embeddings)

    chunks_jsonl_path = OUT_DIR / "chunks.jsonl"
    embeddings_path = OUT_DIR / "embeddings.npy"
    index_path = OUT_DIR / "faiss.index"
    manifest_path = OUT_DIR / "manifest.json"

    print("Guardando chunks.jsonl...")
    save_jsonl(chunks, chunks_jsonl_path)

    print("Guardando embeddings.npy...")
    np.save(embeddings_path, embeddings)

    print("Guardando faiss.index...")
    faiss.write_index(index, str(index_path))

    manifest = {
        "model_name": MODEL_NAME,
        "chunk_count": len(chunks),
        "embedding_dim": int(embeddings.shape[1]),
        "batch_size": BATCH_SIZE,
        "chunks_file": str(chunks_jsonl_path.name),
        "embeddings_file": str(embeddings_path.name),
        "index_file": str(index_path.name),
    }

    print("Guardando manifest.json...")
    save_manifest(manifest_path, manifest)

    print("\n✅ Proceso completado")
    print(f"- Chunks: {len(chunks)}")
    print(f"- Dimensión embedding: {embeddings.shape[1]}")
    print(f"- Índice: {index_path}")


if __name__ == "__main__":
    main()