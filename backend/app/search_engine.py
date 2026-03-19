from pathlib import Path
import json
from typing import List, Dict, Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


class SearchEngine:
    def __init__(self, embeddings_dir: str | Path):
        self.embeddings_dir = Path(embeddings_dir)
        self.manifest_path = self.embeddings_dir / "manifest.json"
        self.chunks_path = self.embeddings_dir / "chunks.jsonl"
        self.index_path = self.embeddings_dir / "faiss.index"

        self.model_name = None
        self.model = None
        self.index = None
        self.chunks = []

        self._load()

    def _load(self) -> None:
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"No existe: {self.manifest_path}")
        if not self.chunks_path.exists():
            raise FileNotFoundError(f"No existe: {self.chunks_path}")
        if not self.index_path.exists():
            raise FileNotFoundError(f"No existe: {self.index_path}")

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.model_name = manifest.get("model_name", "intfloat/multilingual-e5-small")

        self.model = SentenceTransformer(self.model_name)
        self.index = faiss.read_index(str(self.index_path))

        self.chunks = []
        with self.chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                self.chunks.append(json.loads(line))

        if len(self.chunks) == 0:
            raise RuntimeError("chunks.jsonl está vacío")

    def _embed_query(self, query: str) -> np.ndarray:
        vec = self.model.encode(
            [f"query: {query}"],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype(np.float32)
        return vec

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []

        top_k = max(1, min(int(top_k), 20))
        query_vec = self._embed_query(query.strip())

        scores, ids = self.index.search(query_vec, top_k)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1 or idx >= len(self.chunks):
                continue

            chunk = self.chunks[idx]
            text = chunk.get("text", "")
            snippet = text[:500].replace("\n", " ").strip()

            results.append({
                "score": float(score),
                "file_name": chunk.get("file_name", ""),
                "relative_path": chunk.get("relative_path", ""),
                "text": snippet
            })

        return results