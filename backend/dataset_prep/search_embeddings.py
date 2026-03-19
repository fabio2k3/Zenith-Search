from pathlib import Path
import json
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss

BASE_DIR = Path(__file__).resolve().parent
EMB_DIR = BASE_DIR / "embeddings"

MODEL_NAME = "intfloat/multilingual-e5-small"


def load_chunks_jsonl(path: Path):
    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def load_manifest(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(path: Path):
    return faiss.read_index(str(path))


def search(query: str, top_k: int = 5):
    manifest = load_manifest(EMB_DIR / "manifest.json")
    chunks = load_chunks_jsonl(EMB_DIR / "chunks.jsonl")
    index = load_index(EMB_DIR / "faiss.index")

    model = SentenceTransformer(manifest.get("model_name", MODEL_NAME))

    query_vec = model.encode(
        [f"query: {query}"],
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype(np.float32)

    scores, ids = index.search(query_vec, top_k)

    results = []
    for score, idx in zip(scores[0], ids[0]):
        if idx == -1:
            continue
        chunk = chunks[idx]
        results.append({
            "score": float(score),
            "file_name": chunk["file_name"],
            "relative_path": chunk["relative_path"],
            "text": chunk["text"]
        })

    return results


if __name__ == "__main__":
    query = input("Consulta: ").strip()
    top_k = 5

    results = search(query, top_k=top_k)

    print("\nResultados:\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r['score']:.4f} | {r['file_name']}")
        print(r["text"][:500])
        print("-" * 80)