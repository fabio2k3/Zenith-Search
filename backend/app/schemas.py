from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Consulta del usuario")
    top_k: int = Field(5, ge=1, le=20, description="Número de resultados a devolver")


class SearchResult(BaseModel):
    score: float
    file_name: str
    relative_path: str
    text: str


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[SearchResult]