from pathlib import Path
import difflib
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
_CORRECTION_VOCAB: set[str] = set()


def _normalize_pdf_name(name: str) -> str:
    name = unquote(str(name))
    name = Path(name).name.replace("\\", "/").strip()

    name = re.sub(r"\.pdf_chunk_\d+\.txt$", ".pdf", name, flags=re.IGNORECASE)
    name = re.sub(r"_chunk_\d+\.txt$", ".pdf", name, flags=re.IGNORECASE)
    name = re.sub(r"\.txt$", ".pdf", name, flags=re.IGNORECASE)

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

    base = target[:-4]
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


def _extract_terms_from_text(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z]{3,}", str(text))
        if len(token) >= 3
    }


def _extract_terms_from_object(obj, depth: int = 0) -> set[str]:
    if obj is None or depth > 2:
        return set()

    terms: set[str] = set()

    if isinstance(obj, str):
        return _extract_terms_from_text(obj)

    if isinstance(obj, dict):
        for value in obj.values():
            terms |= _extract_terms_from_object(value, depth + 1)
        return terms

    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            terms |= _extract_terms_from_object(item, depth + 1)
        return terms

    for attr in ("text", "title", "file_name", "source_file", "relative_path", "name", "content"):
        if hasattr(obj, attr):
            value = getattr(obj, attr)
            if value:
                terms |= _extract_terms_from_object(value, depth + 1)

    return terms


def _extract_terms_from_vectorizer(vec) -> set[str]:
    terms: set[str] = set()
    if vec is None:
        return terms

    try:
        if hasattr(vec, "get_feature_names_out"):
            terms.update(str(t).lower() for t in vec.get_feature_names_out())
        elif hasattr(vec, "vocabulary_"):
            terms.update(str(t).lower() for t in vec.vocabulary_.keys())
    except Exception:
        pass

    return {t for t in terms if re.fullmatch(r"[a-z]{3,}", t)}


COMMON_CORRECTION_WORDS = {
    "machine", "learning", "deep", "neural", "network", "networks", "artificial",
    "intelligence", "information", "retrieval", "search", "ranking", "vector",
    "vectors", "embedding", "embeddings", "document", "documents", "query",
    "queries", "classification", "regression", "optimization", "analysis",
    "algorithm", "algorithms", "model", "models", "data", "dataset", "datasets",
    "semantic", "natural", "language", "processing", "probability", "statistics",
    "text", "research", "survey", "paper", "papers", "similarity", "training",
    "validation", "testing", "system", "systems",
}


def _build_correction_vocab(engine: HybridSearchEngine | None) -> set[str]:
    vocab: set[str] = set(COMMON_CORRECTION_WORDS)
    vocab |= _extract_terms_from_object(PDF_FILES)

    if engine is not None:
        for attr in ("vectorizer", "tfidf_vectorizer", "count_vectorizer"):
            vocab |= _extract_terms_from_vectorizer(getattr(engine, attr, None))

        for attr in ("documents", "docs", "chunks", "corpus", "indexed_docs", "tokenized_corpus", "records"):
            vocab |= _extract_terms_from_object(getattr(engine, attr, None))

    return {
        word.lower()
        for word in vocab
        if re.fullmatch(r"[a-z]{3,}", word.lower())
    }


def _suggest_query(query: str, vocab: set[str]) -> str | None:
    raw = str(query or "").strip()
    if not raw or not vocab:
        return None

    parts = re.split(r"(\W+)", raw)
    corrected_parts: list[str] = []
    changed = False
    vocab_list = sorted(vocab)

    for part in parts:
        if re.fullmatch(r"[A-Za-zÀ-ÿ]{3,}", part):
            token = part.lower()
            candidate = token

            if token not in vocab:
                candidates = [w for w in vocab_list if w and w[0] == token[0]]
                search_space = candidates if candidates else vocab_list

                matches = difflib.get_close_matches(token, search_space, n=1, cutoff=0.84)
                if not matches:
                    matches = difflib.get_close_matches(token, search_space, n=1, cutoff=0.78)

                if matches:
                    candidate = matches[0]

            if candidate != token:
                changed = True

            corrected_parts.append(candidate)
        else:
            corrected_parts.append(part)

    suggestion = re.sub(r"\s+", " ", "".join(corrected_parts)).strip()
    if not changed or not suggestion or suggestion.lower() == raw.lower():
        return None

    return suggestion[:1].upper() + suggestion[1:]


@app.on_event("startup")
def startup_event():
    global search_engine, _CORRECTION_VOCAB
    search_engine = HybridSearchEngine()
    _CORRECTION_VOCAB = _build_correction_vocab(search_engine)


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

    page = max(1, request.page)
    page_size = max(1, min(request.page_size, 20))

    # Pedimos un poco más de lo necesario para saber si existe "siguiente"
    limit = page * page_size + 1
    results = search_engine.search(request.query, limit)
    suggestion = _suggest_query(request.query, _CORRECTION_VOCAB)

    start = (page - 1) * page_size
    end = start + page_size
    has_more = len(results) > end

    page_results_raw = results[start:end] if start < len(results) else []

    formatted_results = []
    for r in page_results_raw:
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
        page=page,
        page_size=page_size,
        results=formatted_results,
        did_you_mean=suggestion,
        has_more=has_more,
        next_page=page + 1 if has_more else None,
        prev_page=page - 1 if page > 1 else None,
    )