from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


TOKEN_RE = re.compile(r"[^\wáéíóúüñ]+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    text = TOKEN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return [token for token in text.split(" ") if token]


class HybridSearchEngine:
    """
    Motor híbrido:
    - BM25: coincidencia léxica
    - FAISS + embeddings: coincidencia semántica
    - Fusión: Reciprocal Rank Fusion (RRF)
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        query_prefix: str = "query: ",
        rrf_k: int = 60,
        bm25_candidates: int = 50,
        vector_candidates: int = 50,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
        device: Optional[str] = None,
    ) -> None:
        self.backend_dir = Path(__file__).resolve().parents[1]
        self.dataset_dir = self.backend_dir / "dataset_prep"
        self.embeddings_dir = self.dataset_dir / "embeddings"
        self.bm25_dir = self.dataset_dir / "bm25"

        self.model_name = model_name
        self.query_prefix = query_prefix
        self.rrf_k = rrf_k
        self.bm25_candidates = bm25_candidates
        self.vector_candidates = vector_candidates
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight

        print(f"[Zenith] Cargando modelo: {model_name}")
        self.model = SentenceTransformer(model_name, device=device)

        print("[Zenith] Cargando FAISS...")
        self.faiss_index = self._load_faiss_index()

        print("[Zenith] Cargando chunks...")
        self.chunks = self._load_chunks()

        print("[Zenith] Cargando BM25...")
        self.bm25 = self._load_bm25()

        self._validate_alignment()

        print("[Zenith] Motor híbrido listo")

    def _load_faiss_index(self):
        candidates = [
            self.embeddings_dir / "faiss.index",
            self.embeddings_dir / "faiss.faiss",
        ]
        for path in candidates:
            if path.exists():
                return faiss.read_index(str(path))
        raise FileNotFoundError(
            "No se encontró el índice FAISS. Rutas probadas:\n"
            + "\n".join(f"- {p}" for p in candidates)
        )

    def _load_chunks(self) -> List[Dict[str, Any]]:
        candidates = [
            self.embeddings_dir / "chunks.jsonl",
            self.dataset_dir / "chunks" / "chunks.jsonl",
            self.dataset_dir / "chunks.jsonl",
        ]

        path = None
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

        if path is None:
            raise FileNotFoundError(
                "No se encontró chunks.jsonl. Rutas probadas:\n"
                + "\n".join(f"- {p}" for p in candidates)
            )

        chunks: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)

                chunk_id = obj.get("chunk_id") or obj.get("id") or f"chunk_{idx}"
                doc_id = obj.get("doc_id") or obj.get("document_id") or obj.get("source_id")
                source_file = obj.get("source_file") or obj.get("file_name") or obj.get("filename")
                text = obj.get("text") or obj.get("content") or ""

                chunks.append(
                    {
                        "chunk_id": str(chunk_id),
                        "doc_id": str(doc_id) if doc_id is not None else None,
                        "source_file": str(source_file) if source_file is not None else None,
                        "text": str(text),
                    }
                )

        if not chunks:
            raise ValueError("El archivo de chunks está vacío.")

        return chunks

    def _load_bm25(self):
        candidates = [
            self.bm25_dir / "bm25.pkl",
            self.bm25_dir / "bm25_index.pkl",
        ]
        for path in candidates:
            if path.exists():
                with path.open("rb") as f:
                    return pickle.load(f)

        raise FileNotFoundError(
            "No se encontró bm25.pkl. Rutas probadas:\n"
            + "\n".join(f"- {p}" for p in candidates)
        )

    def _validate_alignment(self) -> None:
        faiss_count = int(self.faiss_index.ntotal)
        chunk_count = len(self.chunks)
        bm25_count = int(getattr(self.bm25, "corpus_size", -1))

        if faiss_count != chunk_count:
            raise ValueError(
                f"Desalineación FAISS/chunks: FAISS={faiss_count}, chunks={chunk_count}"
            )

        if bm25_count != chunk_count:
            raise ValueError(
                f"Desalineación BM25/chunks: BM25={bm25_count}, chunks={chunk_count}"
            )

    def _embed_query(self, query: str) -> np.ndarray:
        # IMPORTANTE:
        # Si tus embeddings se generaron sin prefijo "query: ", debes quitarlo aquí
        # y mantener exactamente el mismo criterio en el script de embeddings.
        vec = self.model.encode(
            [self.query_prefix + query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vec, dtype=np.float32)

    def _search_vector(self, query: str, k: int) -> List[Dict[str, Any]]:
        k = min(k, self.faiss_index.ntotal)
        query_vec = self._embed_query(query)

        scores, indices = self.faiss_index.search(query_vec, k)

        results: List[Dict[str, Any]] = []
        for rank, (idx, score) in enumerate(zip(indices[0], scores[0]), start=1):
            if idx < 0:
                continue
            results.append(
                {
                    "chunk_idx": int(idx),
                    "vector_rank": rank,
                    "vector_score": float(score),
                }
            )
        return results

    def _search_bm25(self, query: str, k: int) -> List[Dict[str, Any]]:
        tokens = tokenize(query)
        if not tokens:
            return []

        scores = np.asarray(self.bm25.get_scores(tokens), dtype=np.float32)
        k = min(k, len(scores))

        top_indices = np.argsort(scores)[::-1][:k]
        results: List[Dict[str, Any]] = []

        for rank, idx in enumerate(top_indices, start=1):
            results.append(
                {
                    "chunk_idx": int(idx),
                    "bm25_rank": rank,
                    "bm25_score": float(scores[idx]),
                }
            )

        return results

    def _fuse(self, vector_hits: List[Dict[str, Any]], bm25_hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        fused: Dict[int, Dict[str, Any]] = {}

        for hit in vector_hits:
            idx = hit["chunk_idx"]
            chunk = self.chunks[idx]

            rec = fused.setdefault(
                idx,
                {
                    "chunk_idx": idx,
                    "chunk_id": chunk["chunk_id"],
                    "doc_id": chunk["doc_id"],
                    "source_file": chunk["source_file"],
                    "text": chunk["text"],
                    "vector_score": 0.0,
                    "bm25_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "final_score": 0.0,
                },
            )
            rec["vector_score"] = hit["vector_score"]
            rec["vector_rank"] = hit["vector_rank"]

        for hit in bm25_hits:
            idx = hit["chunk_idx"]
            chunk = self.chunks[idx]

            rec = fused.setdefault(
                idx,
                {
                    "chunk_idx": idx,
                    "chunk_id": chunk["chunk_id"],
                    "doc_id": chunk["doc_id"],
                    "source_file": chunk["source_file"],
                    "text": chunk["text"],
                    "vector_score": 0.0,
                    "bm25_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "final_score": 0.0,
                },
            )
            rec["bm25_score"] = hit["bm25_score"]
            rec["bm25_rank"] = hit["bm25_rank"]

        for rec in fused.values():
            score = 0.0
            if rec["vector_rank"] is not None:
                score += self.vector_weight / (self.rrf_k + rec["vector_rank"])
            if rec["bm25_rank"] is not None:
                score += self.bm25_weight / (self.rrf_k + rec["bm25_rank"])
            rec["final_score"] = float(score)

        ranked = sorted(
            fused.values(),
            key=lambda x: (x["final_score"], x["vector_score"], x["bm25_score"]),
            reverse=True,
        )

        for i, rec in enumerate(ranked, start=1):
            rec["rank"] = i

        return ranked

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        vector_hits = self._search_vector(query, self.vector_candidates)
        bm25_hits = self._search_bm25(query, self.bm25_candidates)
        fused = self._fuse(vector_hits, bm25_hits)

        return fused[:top_k]

    def info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "documents": len(self.chunks),
            "faiss_total": int(self.faiss_index.ntotal),
            "bm25_total": int(getattr(self.bm25, "corpus_size", -1)),
            "rrf_k": self.rrf_k,
            "bm25_candidates": self.bm25_candidates,
            "vector_candidates": self.vector_candidates,
        }