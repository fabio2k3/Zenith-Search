from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import SearchRequest, SearchResponse, SearchResult
from app.hybrid_search_engine import HybridSearchEngine

BASE_DIR = Path(__file__).resolve().parent.parent
EMBEDDINGS_DIR = BASE_DIR / "dataset_prep" / "embeddings"
BM25_DIR = BASE_DIR / "dataset_prep" / "bm25"

app = FastAPI(title="Zenith Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

search_engine: HybridSearchEngine | None = None


@app.on_event("startup")
def startup_event():
    global search_engine
    search_engine = HybridSearchEngine()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "zenith-search-api"
    }


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    global search_engine

    if search_engine is None:
        raise HTTPException(status_code=500, detail="Search engine no inicializado")

    results = search_engine.search(request.query, request.top_k)

    formatted_results = []
    for r in results:
        formatted_results.append(
            SearchResult(
                score=r.get("score", r.get("final_score", 0.0)),
                file_name=r.get("file_name", r.get("source_file", "")),
                relative_path=r.get("relative_path", r.get("source_file", "")),
                text=r.get("text", ""),
                chunk_id=r.get("chunk_id"),
                doc_id=r.get("doc_id"),
                bm25_score=r.get("bm25_score", 0.0),
                vector_score=r.get("vector_score", 0.0),
                bm25_rank=r.get("bm25_rank"),
                vector_rank=r.get("vector_rank"),
            )
        )

    return SearchResponse(
        query=request.query,
        top_k=request.top_k,
        results=formatted_results
    )