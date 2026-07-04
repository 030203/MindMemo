from pydantic import BaseModel


class SimpleQARequest(BaseModel):
    question: str


class QARouteInfo(BaseModel):
    complexity: str = "fast"
    reason: str = ""
    decided_by: str = "rule"


class QASlowRouteInfo(BaseModel):
    path: str = "react"
    reason: str = ""
    decided_by: str = "llm"


class QASourceInfo(BaseModel):
    memory_id: str = ""
    title: str = ""


class SimpleQAResponse(BaseModel):
    answer: str
    route: QARouteInfo | None = None
    slow_route: QASlowRouteInfo | None = None
    sources: list[QASourceInfo] = []
    tool_calls_made: int = 0
