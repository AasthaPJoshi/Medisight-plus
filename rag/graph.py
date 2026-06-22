"""
FILE: rag/graph.py
==================
LangGraph 5-node agentic RAG pipeline with multi-model routing.

Nodes:
    N1 query_analyser  — GPT-4o-mini classifies query type
    N2 query_expander  — GPT-4o-mini adds medical synonyms
    N3 hybrid_retriever — BM25 + Pinecone + RRF fusion
    N4 sufficiency_judge — GPT-4o-mini checks context quality
    N5 generator        — GPT-4o primary, Claude Sonnet fallback

All LLM calls go through rag/llm_router.py which:
    - Tries OpenAI first (cheaper, faster)
    - Falls back to Claude if OpenAI fails or quota is hit
    - Tracks token usage and USD cost per query
"""

import os
import sys
import pickle
import asyncio
from pathlib import Path
from typing import TypedDict, List, Optional

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX_NAME", "medisight-kb")
EMBED_MODEL      = "all-MiniLM-L6-v2"
BM25_PATH        = Path(__file__).parent.parent / "data" / "bm25_index.pkl"

TOP_K_RETRIEVE = 20
TOP_K_RERANK   = 5
MAX_RETRIES    = 2
MIN_CONFIDENCE = 0.4


# ── GRAPH STATE ───────────────────────────────────────────────────────────────

class RAGState(TypedDict):
    original_query:     str
    query_type:         str
    expanded_query:     str
    retrieved_chunks:   List[dict]
    context_confidence: float
    retry_count:        int
    answer:             str
    sources:            List[dict]
    insufficient_context: bool


# ── LAZY LOADERS ──────────────────────────────────────────────────────────────

_embed_model    = None
_pinecone_index = None
_bm25_data      = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        print("Loading embedding model (one-time)...")
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(PINECONE_INDEX)
    return _pinecone_index


def get_bm25_data():
    global _bm25_data
    if _bm25_data is None:
        if not BM25_PATH.exists():
            print(f"⚠️  BM25 index not found. Run: python3 rag/ingest.py")
            return None, None
        with open(BM25_PATH, "rb") as f:
            data = pickle.load(f)
        _bm25_data = (data["bm25"], data["chunks"])
    return _bm25_data


# ── NODE 1: QUERY ANALYSER ────────────────────────────────────────────────────

async def query_analyser(state: RAGState) -> RAGState:
    """
    N1: Classify query type using cheapest model (GPT-4o-mini → Claude Haiku fallback).
    Cost: ~$0.000015 per query.
    """
    from rag.llm_router import classify

    prompt = f"""Classify this medical query into exactly one category.
Categories: symptom, drug, procedure, general

Query: {state['original_query']}

Respond with ONLY the category name, nothing else."""

    try:
        query_type = await classify(prompt, max_tokens=10)
        query_type = query_type.strip().lower()
        if query_type not in ["symptom", "drug", "procedure", "general"]:
            query_type = "general"
    except Exception:
        query_type = "general"

    print(f"   [N1] Query type: {query_type}")
    return {**state, "query_type": query_type}


# ── NODE 2: QUERY EXPANDER ────────────────────────────────────────────────────

async def query_expander(state: RAGState) -> RAGState:
    """
    N2: Expand query with medical synonyms.
    Uses cheap model — simple expansion task.
    Cost: ~$0.000030 per query.
    """
    from rag.llm_router import expand

    retry = state.get("retry_count", 0)

    if retry > 0:
        prompt = f"""Expand this medical query with BROADER synonyms for a second retrieval attempt.
The first attempt did not find sufficient context.

Original query: {state['original_query']}
Query type: {state.get('query_type', 'general')}

Return ONLY expanded search terms separated by spaces. No punctuation or explanation.
Include more alternative terminology, ICD codes, and clinical abbreviations."""
    else:
        prompt = f"""Expand this medical query with synonyms and related medical terms.

Query: {state['original_query']}
Type: {state.get('query_type', 'general')}

Return ONLY expanded search terms separated by spaces. No punctuation or explanation.
Include: formal medical terms, common synonyms, related conditions, abbreviations."""

    try:
        expansion = await expand(prompt, max_tokens=150)
        expanded = f"{state['original_query']} {expansion}"
    except Exception:
        expanded = state["original_query"]

    print(f"   [N2] Expanded query (retry={retry}): {expanded[:80]}...")
    return {
        **state,
        "expanded_query": expanded,
        "retry_count": retry + 1,
    }


# ── NODE 3: HYBRID RETRIEVER ──────────────────────────────────────────────────

def hybrid_retriever(state: RAGState) -> RAGState:
    """
    N3: BM25 keyword search + Pinecone semantic search → RRF fusion.
    No LLM call here — pure retrieval. Free.
    """
    query = state.get("expanded_query", state["original_query"])

    # BM25 retrieval
    bm25_results = []
    bm25_data = get_bm25_data()
    if bm25_data[0] is not None:
        bm25, chunks = bm25_data
        tokenized = query.lower().split()
        scores = bm25.get_scores(tokenized)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:TOP_K_RETRIEVE]
        bm25_results = [(chunks[i], scores[i]) for i in top_indices if scores[i] > 0]

    # Pinecone semantic retrieval
    pinecone_results = []
    try:
        model = get_embed_model()
        embedding = model.encode(query).tolist()
        index = get_pinecone_index()
        results = index.query(vector=embedding, top_k=TOP_K_RETRIEVE, include_metadata=True)
        pinecone_results = [
            (match["metadata"], match["score"])
            for match in results.get("matches", [])
        ]
    except Exception as e:
        print(f"   [N3] Pinecone error: {e}")

    # RRF fusion
    k = 60
    rrf_scores = {}

    for rank, (chunk, _) in enumerate(bm25_results):
        cid = chunk.get("id", str(rank))
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank + 1)

    for rank, (metadata, _) in enumerate(pinecone_results):
        cid = metadata.get("pmid", str(rank))
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank + 1)

    all_results = {}
    for chunk, score in bm25_results:
        cid = chunk.get("id", "")
        if cid not in all_results:
            all_results[cid] = {"text": chunk.get("text", ""), "metadata": chunk.get("metadata", {}), "rrf": rrf_scores.get(cid, 0)}

    for metadata, score in pinecone_results:
        cid = metadata.get("pmid", "")
        if cid not in all_results:
            all_results[cid] = {"text": f"{metadata.get('title', '')}.", "metadata": metadata, "rrf": rrf_scores.get(cid, 0)}

    sorted_results = sorted(all_results.values(), key=lambda x: x["rrf"], reverse=True)
    top_chunks = sorted_results[:TOP_K_RERANK]

    print(f"   [N3] Retrieved {len(top_chunks)} chunks (BM25: {len(bm25_results)}, Pinecone: {len(pinecone_results)})")
    return {**state, "retrieved_chunks": top_chunks}


# ── NODE 4: SUFFICIENCY JUDGE ─────────────────────────────────────────────────

async def sufficiency_judge(state: RAGState) -> RAGState:
    """
    N4: Hallucination guardrail. Checks if retrieved context is relevant.
    Uses cheap model — simple scoring task.
    Cost: ~$0.000020 per query.
    """
    from rag.llm_router import judge

    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        print("   [N4] No chunks — confidence: 0.0")
        return {**state, "context_confidence": 0.0}

    context_preview = "\n\n".join([
        f"Chunk {i+1}: {chunk.get('text', '')[:300]}..."
        for i, chunk in enumerate(chunks[:3])
    ])

    prompt = f"""Rate how relevant this retrieved medical literature is to the query.

Query: {state['original_query']}

Retrieved context (top 3 chunks):
{context_preview}

Rate relevance from 0.0 to 1.0:
- 1.0: Directly addresses query with specific clinical information
- 0.7: Related and useful but not perfectly matched
- 0.4: Tangentially related
- 0.0: Completely irrelevant

Respond with ONLY a decimal number between 0.0 and 1.0, nothing else."""

    try:
        raw = await judge(prompt, max_tokens=10)
        confidence = float(raw.strip())
        confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = 0.5

    print(f"   [N4] Context confidence: {confidence:.2f} (threshold: {MIN_CONFIDENCE})")
    return {**state, "context_confidence": confidence}


def route_after_judge(state: RAGState) -> str:
    confidence  = state.get("context_confidence", 0.5)
    retry_count = state.get("retry_count", 0)

    if confidence < MIN_CONFIDENCE and retry_count < MAX_RETRIES:
        print(f"   [ROUTE] Low confidence ({confidence:.2f}), retrying (attempt {retry_count})")
        return "query_expander"
    else:
        if confidence < MIN_CONFIDENCE:
            print(f"   [ROUTE] Low confidence after {retry_count} retries — flagging insufficient context")
        else:
            print(f"   [ROUTE] Sufficient context — proceeding to generation")
        return "generator"


# ── NODE 5: GENERATOR ─────────────────────────────────────────────────────────

async def generator(state: RAGState) -> RAGState:
    """
    N5: Generate cited clinical response.
    Uses GPT-4o primary → Claude Sonnet fallback.
    This is the most expensive node: ~$0.003-0.008 per query.
    """
    from rag.llm_router import generate

    confidence = state.get("context_confidence", 0.5)
    chunks     = state.get("retrieved_chunks", [])

    if confidence < MIN_CONFIDENCE or not chunks:
        return {
            **state,
            "answer": (
                "I don't have sufficient information in the medical knowledge base "
                "to provide a reliable answer to this query. Please consult clinical "
                "guidelines directly or use UpToDate/PubMed for this specific question."
            ),
            "sources": [],
            "insufficient_context": True,
        }

    # Build context with citations
    context_parts = []
    sources = []
    for i, chunk in enumerate(chunks):
        metadata = chunk.get("metadata", {})
        pmid  = metadata.get("pmid", f"chunk_{i}")
        title = metadata.get("title", "Unknown source")
        url   = metadata.get("url", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        text  = chunk.get("text", "")
        context_parts.append(f"[Source: PMID:{pmid}]\n{text}")
        sources.append({"pmid": pmid, "title": title, "url": url})

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = """You are a clinical decision support AI for physicians.

STRICT RULES:
1. ONLY use information from the provided medical literature context.
2. Do NOT use your training knowledge — only what is in the context.
3. Cite every clinical claim using [Source: PMID:XXXXXXXX] format.
4. If the context doesn't contain enough information, say so explicitly.
5. Be specific, evidence-based, and concise.
6. Structure your response with clear sections when appropriate.
7. Always recommend physician judgment and clinical guidelines."""

    user_prompt = f"""Clinical query: {state['original_query']}

Medical literature context:
{context}

Provide a clinical response based ONLY on the above context.
Cite sources using [Source: PMID:XXXXXXXX] format after each claim."""

    try:
        answer = await generate(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            max_tokens=1500,
        )
    except Exception as e:
        answer = f"Error generating response: {str(e)}"

    print(f"   [N5] Generated response ({len(answer)} chars, {len(sources)} sources)")
    return {
        **state,
        "answer": answer,
        "sources": sources,
        "insufficient_context": False,
    }


# ── BUILD PIPELINE ────────────────────────────────────────────────────────────

def build_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("query_analyser",   query_analyser)
    graph.add_node("query_expander",   query_expander)
    graph.add_node("hybrid_retriever", hybrid_retriever)
    graph.add_node("sufficiency_judge",sufficiency_judge)
    graph.add_node("generator",        generator)

    graph.set_entry_point("query_analyser")
    graph.add_edge("query_analyser",   "query_expander")
    graph.add_edge("query_expander",   "hybrid_retriever")
    graph.add_edge("hybrid_retriever", "sufficiency_judge")

    graph.add_conditional_edges(
        "sufficiency_judge",
        route_after_judge,
        {"query_expander": "query_expander", "generator": "generator"}
    )

    graph.add_edge("generator", END)
    return graph.compile()


rag_pipeline = build_rag_graph()


# ── PUBLIC API ────────────────────────────────────────────────────────────────

async def run_rag_query(query: str, user_id: str = None) -> dict:
    """
    Run the full 5-node RAG pipeline. Includes Langfuse tracing and cost tracking.
    """
    from rag.observability import RAGTracer
    print(f"\n🔍 RAG Query: {query[:80]}...")

    initial_state: RAGState = {
        "original_query":     query,
        "query_type":         "general",
        "expanded_query":     query,
        "retrieved_chunks":   [],
        "context_confidence": 0.0,
        "retry_count":        0,
        "answer":             "",
        "sources":            [],
        "insufficient_context": False,
    }

    with RAGTracer(query=query, user_id=user_id) as tracer:
        final_state = await rag_pipeline.ainvoke(initial_state)
        result = {
            "answer":               final_state.get("answer", ""),
            "sources":              final_state.get("sources", []),
            "confidence":           final_state.get("context_confidence", 0.0),
            "insufficient_context": final_state.get("insufficient_context", False),
            "query_type":           final_state.get("query_type", "general"),
        }
        tracer.finish(result)

    # Log cost summary
    from rag.llm_router import get_cost_summary
    cost = get_cost_summary()
    print(f"   💰 Session cost so far: ${cost['total_cost_usd']:.5f} across {cost['total_queries']} queries")

    return result
