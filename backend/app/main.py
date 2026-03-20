from pathlib import Path
import re
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.schemas import SearchRequest, SearchResponse, SearchResult
from app.hybrid_search_engine import HybridSearchEngine

BASE_DIR = Path(__file__).resolve().parent.parent
PDFS_DIR = BASE_DIR / "dataset_prep" / "pdfs"
BACKEND_URL = "http://127.0.0.1:8000"

app = FastAPI(title="Zenith Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if PDFS_DIR.exists():
    app.mount("/pdfs", StaticFiles(directory=str(PDFS_DIR)), name="pdfs")

search_engine: HybridSearchEngine | None = None


def _normalize_pdf_name(name: str) -> str:
    name = unquote(str(name))
    name = Path(name).name.replace("\\", "/").strip()

    # chunk -> pdf
    name = re.sub(r"\.pdf_chunk_\d+\.txt$", ".pdf", name, flags=re.IGNORECASE)
    name = re.sub(r"_chunk_\d+\.txt$", ".pdf", name, flags=re.IGNORECASE)
    name = re.sub(r"\.txt$", ".pdf", name, flags=re.IGNORECASE)

    # normaliza espacios
    name = re.sub(r"\s+", " ", name).strip()
    return name.lower()


def _load_pdf_catalog() -> list[str]:
    if not PDFS_DIR.exists():
        return []
    return [p.name for p in PDFS_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]


PDF_FILES = _load_pdf_catalog()


def _resolve_pdf_filename(candidate: str) -> str | None:
    target = _normalize_pdf_name(candidate)
    if not target.endswith(".pdf"):
        target += ".pdf"

    exact_map = {_normalize_pdf_name(p): p for p in PDF_FILES}
    if target in exact_map:
        return exact_map[target]

    base = target[:-4]  # sin .pdf
    for p in PDF_FILES:
        normalized = _normalize_pdf_name(p)
        normalized_base = normalized[:-4] if normalized.endswith(".pdf") else normalized

        if (
            normalized == target
            or normalized_base == base
            or normalized.startswith(base)
            or base.startswith(normalized_base)
        ):
            return p

    return None


def make_pdf_url(file_name: str | None, relative_path: str | None) -> str | None:
    candidate = (relative_path or file_name or "").strip()
    if not candidate:
        return None

    resolved = _resolve_pdf_filename(candidate)
    if not resolved:
        return None

    return f"{BACKEND_URL}/pdfs/{quote(resolved)}"


@app.on_event("startup")
def startup_event():
    global search_engine
    search_engine = HybridSearchEngine()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "zenith-search-api",
    }


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest):
    global search_engine

    if search_engine is None:
        raise HTTPException(status_code=500, detail="Search engine no inicializado")

    results = search_engine.search(request.query, request.top_k)

    formatted_results = []
    for r in results:
        file_name = r.get("file_name", r.get("source_file", ""))
        relative_path = r.get("relative_path", r.get("source_file", ""))
        pdf_url = make_pdf_url(file_name, relative_path)

        formatted_results.append(
            SearchResult(
                score=r.get("score", r.get("final_score", 0.0)),
                file_name=file_name,
                relative_path=relative_path,
                text=r.get("text", ""),
                pdf_url=pdf_url,
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
        results=formatted_results,
    )