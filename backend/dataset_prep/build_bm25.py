from __future__ import annotations

import argparse
import json
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List

from rank_bm25 import BM25Okapi

BACKEND_DIR = Path(__file__).resolve().parents[1]

DEFAULT_CHUNKS_CANDIDATES = [
    BACKEND_DIR / "dataset_prep" / "embeddings" / "chunks.jsonl",
    BACKEND_DIR / "dataset_prep" / "chunks" / "chunks.jsonl",
    BACKEND_DIR / "dataset_prep" / "chunks.jsonl",
]

DEFAULT_OUTPUT_DIR = BACKEND_DIR / "dataset_prep" / "bm25"

TOKEN_RE = re.compile(r"[^\wáéíóúüñ]+", re.UNICODE)


def resolve_input_path(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo de entrada: {path}")
        return path

    for candidate in DEFAULT_CHUNKS_CANDIDATES:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No encontré chunks.jsonl. He probado estas rutas:\n"
        + "\n".join(f"- {p}" for p in DEFAULT_CHUNKS_CANDIDATES)
    )


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    text = TOKEN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return [token for token in text.split(" ") if token]


def load_chunks(path: Path) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []

    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"El archivo de chunks debe ser JSONL. Recibido: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            obj = json.loads(line)

            chunk_id = obj.get("chunk_id") or obj.get("id") or f"chunk_{len(chunks)}"
            doc_id = obj.get("doc_id") or obj.get("document_id") or obj.get("source_id")
            source_file = obj.get("source_file") or obj.get("file_name") or obj.get("filename")
            text = obj.get("text") or obj.get("content") or ""

            chunks.append(
                {
                    "chunk_id": str(chunk_id),
                    "doc_id": str(doc_id) if doc_id is not None else None,
                    "source_file": str(source_file) if source_file is not None else None,
                    "text": str(text),
                    "raw": obj,
                    "line_no": line_no,
                }
            )

    if not chunks:
        raise ValueError(f"No se cargó ningún chunk desde {path}")

    return chunks


def build_bm25(tokenized_docs: List[List[str]]) -> BM25Okapi:
    return BM25Okapi(tokenized_docs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Construye el índice BM25 de Zenith.")
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Ruta a chunks.jsonl. Si no se indica, busca rutas por defecto.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directorio donde guardar bm25.pkl y stats.",
    )
    args = parser.parse_args()

    input_path = resolve_input_path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[BM25] Leyendo chunks desde: {input_path}")
    chunks = load_chunks(input_path)

    print(f"[BM25] Chunks cargados: {len(chunks)}")
    tokenized_docs = [tokenize(chunk["text"]) for chunk in chunks]

    print("[BM25] Construyendo índice...")
    bm25 = build_bm25(tokenized_docs)

    bm25_path = output_dir / "bm25.pkl"
    stats_path = output_dir / "bm25_stats.json"
    corpus_path = output_dir / "bm25_corpus.jsonl"

    with bm25_path.open("wb") as f:
        pickle.dump(bm25, f)

    stats = {
        "documents": len(chunks),
        "average_document_length": float(bm25.avgdl),
        "vocabulary_size": int(len(bm25.idf)),
        "output_bm25_path": str(bm25_path),
        "input_chunks_path": str(input_path),
    }

    with stats_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    with corpus_path.open("w", encoding="utf-8") as f:
        for i, (chunk, tokens) in enumerate(zip(chunks, tokenized_docs)):
            record = {
                "idx": i,
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "source_file": chunk["source_file"],
                "token_count": len(tokens),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print("[BM25] OK")
    print(f"[BM25] Guardado: {bm25_path}")
    print(f"[BM25] Guardado: {stats_path}")
    print(f"[BM25] Guardado: {corpus_path}")


if __name__ == "__main__":
    main()