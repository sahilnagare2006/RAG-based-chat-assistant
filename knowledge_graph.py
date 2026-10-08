"""
knowledge_graph.py
Document Knowledge Graph Engine.
Extracts entities, concepts, and co-occurrence relationships from document chunks,
producing a JSON graph for interactive visualization.
"""
from __future__ import annotations

import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Tuple


# Common stopwords to filter out from entity extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through", "this",
    "that", "these", "those", "it", "its", "we", "our", "your", "their",
    "which", "who", "what", "when", "where", "how", "all", "each", "both",
    "few", "more", "most", "other", "some", "such", "than", "also", "just",
    "not", "no", "if", "then", "so", "about", "up", "out", "over", "any",
    "see", "use", "used", "using", "figure", "table", "section", "chapter"
}

# Common technical domains for node categorization
TECH_CATEGORIES = {
    "algorithm": ["algorithm", "search", "sort", "retrieval", "embedding", "cosine", "similarity", "vector"],
    "architecture": ["architecture", "pipeline", "system", "layer", "module", "component", "server", "service"],
    "tool": ["python", "fastapi", "numpy", "pytorch", "tensorflow", "llm", "api", "openrouter", "model"],
    "concept": ["learning", "training", "inference", "context", "chunk", "token", "prompt", "knowledge"],
    "process": ["index", "extract", "retrieve", "embed", "chunk", "query", "response", "generate"],
}


def _categorize_node(label: str) -> str:
    label_lower = label.lower()
    for cat, keywords in TECH_CATEGORIES.items():
        if any(kw in label_lower for kw in keywords):
            return cat
    return "general"


def _extract_entities(text: str) -> List[str]:
    """Extracts meaningful phrases and capitalized entities from text."""
    entities = set()

    # Capitalized multi-word phrases (e.g. "Vector RAG", "OpenRouter API")
    caps_phrases = re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b", text)
    for p in caps_phrases:
        if len(p) >= 3 and p.lower() not in STOPWORDS:
            entities.add(p)

    # Technical terms: camelCase or snake_case identifiers (e.g. cosine_similarity, DenseVectorEngine)
    tech_terms = re.findall(r"\b([a-z][a-z_]+(?:_[a-z]+)+|[A-Z][a-z]+[A-Z][a-zA-Z]+)\b", text)
    for t in tech_terms:
        if len(t) >= 5 and t.lower() not in STOPWORDS:
            entities.add(t.replace("_", " "))

    # Quoted terms (e.g. "vector embedding", "knowledge graph")
    quoted = re.findall(r"[\"'`]([a-zA-Z\s\-]+)[\"'`]", text)
    for q in quoted:
        q = q.strip()
        if 3 <= len(q) <= 50 and q.lower() not in STOPWORDS:
            entities.add(q)

    return list(entities)


def build_knowledge_graph(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds a knowledge graph from document chunks.
    Returns { nodes: [...], links: [...] }
    """
    # Entity frequency tracking per chunk
    entity_freq: Dict[str, int] = defaultdict(int)
    entity_pages: Dict[str, List[int]] = defaultdict(list)
    chunk_entities: List[List[str]] = []

    for chunk in chunks:
        text = chunk.get("text", "")
        page = chunk.get("page", 1)
        entities = _extract_entities(text)

        for e in entities:
            entity_freq[e] += 1
            if page not in entity_pages[e]:
                entity_pages[e].append(page)

        chunk_entities.append(entities)

    # Filter: keep only entities that appear 2+ times or are clearly significant
    significant_entities = {
        e for e, freq in entity_freq.items()
        if freq >= 2 or (freq == 1 and len(e) >= 10)
    }

    if not significant_entities:
        # Fallback: keep top-30 most frequent
        sorted_ents = sorted(entity_freq.items(), key=lambda x: -x[1])[:30]
        significant_entities = {e for e, _ in sorted_ents}

    # Cap at 60 nodes to keep the graph readable
    top_entities = sorted(
        [(e, entity_freq[e]) for e in significant_entities],
        key=lambda x: -x[1]
    )[:60]

    nodes = []
    node_ids = {}
    for idx, (entity, freq) in enumerate(top_entities):
        node_id = f"n{idx}"
        node_ids[entity] = node_id
        nodes.append({
            "id": node_id,
            "label": entity,
            "category": _categorize_node(entity),
            "frequency": freq,
            "pages": entity_pages[entity][:5],
            "size": min(8 + freq * 2, 28)
        })

    # Build co-occurrence links
    link_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for chunk_ents in chunk_entities:
        relevant = [e for e in chunk_ents if e in node_ids]
        for i in range(len(relevant)):
            for j in range(i + 1, len(relevant)):
                a, b = sorted([relevant[i], relevant[j]])
                link_counts[(a, b)] += 1

    links = []
    for (src, tgt), count in link_counts.items():
        if count >= 1 and src in node_ids and tgt in node_ids:
            links.append({
                "source": node_ids[src],
                "target": node_ids[tgt],
                "weight": count,
                "relation": "co-occurs with"
            })

    # Sort and cap links
    links = sorted(links, key=lambda x: -x["weight"])[:120]

    return {
        "nodes": nodes,
        "links": links,
        "entity_count": len(nodes),
        "link_count": len(links)
    }


def generate_and_save_graph(workspace: Path, doc_id: str) -> Dict[str, Any]:
    """Loads indexed chunks and saves a knowledge graph JSON."""
    chunks_file = workspace / f"{doc_id}_chunks.json"
    if not chunks_file.exists():
        return {"error": f"Chunks file not found for doc {doc_id}"}

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    graph = build_knowledge_graph(chunks)
    graph_file = workspace / f"{doc_id}_graph.json"

    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    return graph


def load_graph(workspace: Path, doc_id: str) -> Dict[str, Any]:
    """Loads the pre-generated knowledge graph JSON for a document."""
    graph_file = workspace / f"{doc_id}_graph.json"
    if not graph_file.exists():
        return {"nodes": [], "links": [], "entity_count": 0, "link_count": 0}

    with open(graph_file, "r", encoding="utf-8") as f:
        return json.load(f)
