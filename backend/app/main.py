from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import SearchRequest, SearchResponse, SearchResult
from app.search_engine import SearchEngine

BASE_DIR = Path(__file__).resolve().parent.parent
EMBEDDINGS_DIR = BASE_DIR / "dataset_prep" / "embeddings"

app = FastAPI(title="Zenith Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

search_engine: SearchEngine | None = None


@app.on_event("startup")
def startup_event():
    global search_engine
    search_engine = SearchEngine(EMBEDDINGS_DIR)


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

    return SearchResponse(
        query=request.query,
        top_k=request.top_k,
        results=[SearchResult(**r) for r in results]
    )