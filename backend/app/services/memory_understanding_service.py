from __future__ import annotations

import re
from dataclasses import dataclass


TECH_TOPICS: dict[str, list[str]] = {
    "RAG": ["rag", "retrieval augmented generation", "hybrid retrieval", "rerank", "context packing"],
    "Agent": ["agent", "ai agent", "\u667a\u80fd\u4f53", "copilot"],
    "LangGraph": ["langgraph", "state graph", "conditional edge"],
    "Workflow": ["workflow", "\u5de5\u4f5c\u6d41", "tool calling", "planner", "trace", "tracing"],
    "pgvector": ["pgvector", "vector", "embedding"],
    "RoomOS": ["roomos"],
    "Memory Graph": ["memory graph", "\u8bb0\u5fc6\u56fe\u8c31", "\u5173\u7cfb\u56fe"],
    "Long-term Memory": ["long-term memory", "\u957f\u671f\u8bb0\u5fc6"],
}

CATEGORY_TAGS: dict[str, list[str]] = {
    "learning": ["learning", "knowledge"],
    "project": ["project", "progress"],
    "idea": ["idea", "inspiration"],
    "memo": ["memo", "record"],
}

DOMAIN_MARKERS: dict[str, list[str]] = {
    "expense": ["\u82b1\u4e86", "\u6d88\u8d39", "\u5f00\u9500", "\u652f\u51fa", "\u82b1\u8d39", "\u5143"],
    "mood": ["\u60c5\u7eea", "\u5fc3\u60c5", "\u7761\u5f97", "\u7761\u7720", "\u538b\u529b", "\u7126\u8651"],
    "plan": ["\u8ba1\u5212", "\u5f85\u529e", "\u63d0\u9192", "\u8bb0\u5f97", "\u4e0b\u4e2a\u6708", "\u660e\u5929"],
    "learning": ["\u7814\u7a76", "\u5b66\u4e60", "\u6280\u672f", "\u67b6\u6784", "\u8bba\u6587"],
    "startup": ["\u521b\u4e1a", "\u4ea7\u54c1", "\u673a\u4f1a", "saas"],
}

IMPORTANT_PHRASE_PATTERNS = [
    re.compile(r"\b[A-Z][A-Za-z0-9]{2,}(?:[A-Z][A-Za-z0-9]+)*\b"),
    re.compile(r"\b(?:AI|RAG|LLM|MCP|API|QA|UI|UX|SaaS)\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class MemoryUnderstanding:
    tags: list[str]
    keywords: list[str]
    entities: list[str]
    topics: list[str]


def _unique(values: list[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


def extract_topics(text: str) -> list[str]:
    lowered = text.lower()
    topics: list[str] = []
    for topic, aliases in TECH_TOPICS.items():
        if topic.lower() in lowered or any(alias.lower() in lowered for alias in aliases):
            topics.append(topic)
    return _unique(topics)


def extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for pattern in IMPORTANT_PHRASE_PATTERNS:
        entities.extend(match.group(0) for match in pattern.finditer(text))
    entities.extend(extract_topics(text))
    return _unique(entities, limit=16)


def extract_domain_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    for tag, markers in DOMAIN_MARKERS.items():
        if any(marker.lower() in lowered for marker in markers):
            tags.append(tag)
    return _unique(tags)


class MemoryUnderstandingService:
    def understand(self, content: str, category: str) -> MemoryUnderstanding:
        text = content.strip()
        topics = extract_topics(text)
        entities = extract_entities(text)
        domain_tags = extract_domain_tags(text)
        category_tags = CATEGORY_TAGS.get(category, ["record"])
        tags = _unique([*category_tags, *domain_tags, *topics], limit=18)
        keywords = _unique([*topics, *domain_tags, *entities, *category_tags], limit=18)
        return MemoryUnderstanding(tags=tags, keywords=keywords, entities=entities, topics=topics)


memory_understanding_service = MemoryUnderstandingService()
