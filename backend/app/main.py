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
_CORRECTION_VOCAB: set[str] = set()
_CORRECTION_VOCAB_LIST: list[str] = []   # sorted once at startup, reused on every search


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


# ── Spell-correction engine ────────────────────────────────────────────────
#
# Why OSA instead of difflib.SequenceMatcher?
#   • SequenceMatcher measures longest common subsequences — great for diffs,
#     poor for single-word typos.  Its ratio() doesn't map cleanly to "number
#     of keystrokes wrong", so a fixed cutoff misbehaves for short words.
#   • Optimal String Alignment (restricted Damerau–Levenshtein) counts
#     insertions, deletions, substitutions AND adjacent transpositions as
#     exactly 1 edit each.  That makes "netwrok" → 1 edit from "network",
#     "retreval" → 1 edit from "retrieval", etc.
# ──────────────────────────────────────────────────────────────────────────


def _osa_distance(s1: str, s2: str) -> int:
    """
    Optimal String Alignment distance.
    Like Levenshtein but also counts swapping two adjacent characters as 1 op.
    O(len(s1) * len(s2)) time — fast enough for word-level corrections.
    """
    len1, len2 = len(s1), len(s2)
    if s1 == s2:
        return 0
    if len1 == 0:
        return len2
    if len2 == 0:
        return len1

    # Two-row DP with transposition look-back
    prev2 = list(range(len2 + 1))   # d[i-2]
    prev1 = list(range(len2 + 1))   # d[i-1]  — initialised below
    curr  = [0] * (len2 + 1)

    prev1 = list(range(len2 + 1))

    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev1[j] + 1,           # deletion
                curr[j - 1] + 1,        # insertion
                prev1[j - 1] + cost,    # substitution
            )
            # Adjacent transposition (only valid from i≥2, j≥2)
            if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                curr[j] = min(curr[j], prev2[j - 2] + 1)

        prev2, prev1, curr = prev1, curr, prev2  # rotate rows in-place

    return prev1[len2]


def _max_edit_distance(word_len: int) -> int:
    """
    Dynamic tolerance that scales with word length.

    |word|   max edits   rationale
    ──────   ─────────   ────────────────────────────────────────
    3        0           3-char words: 1 edit = 33 % change → too risky
    4        1           "lern" → "learn" OK; "lern" → "fern" blocked
    5–7      1           comfortable for most short domain terms
    8–11     2           "embeding" → "embedding", "retreval" → "retrieval"
    12+      2           keep at 2; 3 edits on long words → false positives
    """
    if word_len <= 3:
        return 0
    if word_len <= 7:
        return 1
    return 2


def _correct_word(token: str, vocab: set[str], vocab_list: list[str]) -> str:
    """
    Return the closest vocabulary match for *token*, or *token* unchanged.

    Search strategy
    ───────────────
    1. Exact hit → done immediately.
    2. Word too short (≤3 chars) → skip (max_dist=0 means no correction).
    3. Pre-filter candidates by |len_candidate − len_token| ≤ max_dist.
       This alone eliminates ~60–80 % of the vocabulary before any OSA call.
    4. Pass 1 — same first character:
         Covers the vast majority of real typos (dropped/doubled letters,
         substitutions, transpositions in the middle).
    5. Pass 2 — all length-filtered candidates (fallback):
         Catches first-character substitutions, e.g. "cachine" → "machine".
         Only runs when Pass 1 finds nothing.
    6. Tiebreaker (lexicographic tuple, lower = better):
         (distance, len_diff, first_char_differs)
         Prefers the closest word; on ties, prefers same length;
         on further ties, prefers same first character.
    """
    if token in vocab:
        return token

    n = len(token)
    max_dist = _max_edit_distance(n)
    if max_dist == 0:
        return token

    # ── Pre-filter by length ────────────────────────────────────────────
    candidates = [w for w in vocab_list if abs(len(w) - n) <= max_dist]
    if not candidates:
        return token

    best_word = token
    # score tuple: (distance, length_diff, first_char_differs)  — lower = better
    best_score: tuple = (max_dist + 1, 2, 2)

    def _score(w: str, dist: int) -> tuple:
        return (dist, abs(len(w) - n), 0 if w[0] == token[0] else 1)

    # ── Pass 1: same first character ────────────────────────────────────
    same_first = [w for w in candidates if w[0] == token[0]]
    for w in same_first:
        d = _osa_distance(token, w)
        if d <= max_dist:
            sc = _score(w, d)
            if sc < best_score:
                best_score = sc
                best_word = w

    # ── Pass 2: different first character (only if Pass 1 failed) ───────
    if best_word is token:
        for w in candidates:
            if w[0] == token[0]:
                continue  # already checked
            d = _osa_distance(token, w)
            if d <= max_dist:
                sc = _score(w, d)
                if sc < best_score:
                    best_score = sc
                    best_word = w

    return best_word


def _suggest_query(query: str, vocab: set[str]) -> str | None:
    """
    Return a corrected version of *query* if any word was changed, else None.
    Uses the pre-sorted global _CORRECTION_VOCAB_LIST to avoid re-sorting
    on every request.
    """
    raw = str(query or "").strip()
    if not raw or not vocab:
        return None

    # Use the globally cached sorted list; fall back to sorting inline
    # (the fallback only happens before startup completes, never in production).
    vocab_list = _CORRECTION_VOCAB_LIST or sorted(vocab)

    parts = re.split(r"(\W+)", raw)
    corrected_parts: list[str] = []
    changed = False

    for part in parts:
        if re.fullmatch(r"[A-Za-zÀ-ÿ]{3,}", part):
            token = part.lower()
            corrected = _correct_word(token, vocab, vocab_list)
            if corrected != token:
                changed = True
            corrected_parts.append(corrected)
        else:
            corrected_parts.append(part)

    suggestion = re.sub(r"\s+", " ", "".join(corrected_parts)).strip()
    if not changed or not suggestion or suggestion.lower() == raw.lower():
        return None

    return suggestion[:1].upper() + suggestion[1:]


@app.on_event("startup")
def startup_event():
    global search_engine, _CORRECTION_VOCAB, _CORRECTION_VOCAB_LIST
    search_engine = HybridSearchEngine()
    _CORRECTION_VOCAB = _build_correction_vocab(search_engine)
    # Sort once here; _suggest_query reuses this list on every request
    _CORRECTION_VOCAB_LIST = sorted(_CORRECTION_VOCAB)


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