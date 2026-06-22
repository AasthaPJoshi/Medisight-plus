"""
FILE: rag/observability.py
==========================
WHAT THIS FILE IS:
    Langfuse tracing for every RAG query and billing AI call.
    Langfuse is an open-source LLMOps platform that records:
    - Input query and final output
    - Latency per node (N1 through N5)
    - Token count and estimated cost
    - Confidence scores and source count
    - Whether the hallucination guard triggered

CONCEPT — Why LLMOps tracing matters:
    Without tracing, you cannot answer:
    - Why did this query return insufficient context?
    - Which queries are slowest?
    - What is our average faithfulness score over time?
    - How much does each clinical query cost in tokens?
    Langfuse makes all of this visible in a dashboard.

HOW TO SETUP:
    1. Go to https://cloud.langfuse.com (free account)
    2. Create project 'medisight'
    3. Get API keys from Settings
    4. Add to .env:
       LANGFUSE_PUBLIC_KEY=pk-lf-...
       LANGFUSE_SECRET_KEY=sk-lf-...
       LANGFUSE_HOST=https://cloud.langfuse.com

HOW TO USE:
    from rag.observability import trace_rag_query, trace_billing_analysis

    # Wrap any RAG call
    with trace_rag_query(query) as tracer:
        result = await run_rag_query(query)
        tracer.finish(result)

VIEW TRACES:
    Go to https://cloud.langfuse.com → your project → Traces
"""

import os
import time
from typing import Optional, Any
from dotenv import load_dotenv

load_dotenv()

LANGFUSE_ENABLED = bool(
    os.getenv("LANGFUSE_PUBLIC_KEY") and
    os.getenv("LANGFUSE_SECRET_KEY")
)

_langfuse = None


def get_langfuse():
    """Lazy-load Langfuse client. Returns None if not configured."""
    global _langfuse
    if not LANGFUSE_ENABLED:
        return None
    if _langfuse is None:
        try:
            from langfuse import Langfuse
            _langfuse = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            print("✅ Langfuse tracing enabled")
        except ImportError:
            print("⚠️  Langfuse not installed. Run: pip install langfuse")
        except Exception as e:
            print(f"⚠️  Langfuse init failed: {e}")
    return _langfuse


class RAGTracer:
    """
    Context manager for tracing a single RAG query through Langfuse.

    Usage:
        with RAGTracer(query="chest pain differential") as t:
            result = await run_rag_query(query)
            t.finish(result)
    """

    def __init__(self, query: str, user_id: Optional[str] = None):
        self.query     = query
        self.user_id   = user_id
        self.trace     = None
        self.start_time = time.time()
        self._spans: dict = {}

    def __enter__(self):
        lf = get_langfuse()
        if lf:
            try:
                self.trace = lf.trace(
                    name="rag_query",
                    input={"query": self.query},
                    user_id=self.user_id,
                    tags=["medisight", "rag"],
                )
            except Exception:
                pass
        return self

    def span(self, name: str, input_data: Any = None):
        """Start a span for a pipeline node (N1-N5)."""
        if self.trace:
            try:
                span = self.trace.span(name=name, input=input_data)
                self._spans[name] = {"span": span, "start": time.time()}
            except Exception:
                pass

    def end_span(self, name: str, output: Any = None, metadata: dict = None):
        """End a pipeline node span."""
        if name in self._spans:
            try:
                entry = self._spans[name]
                entry["span"].end(
                    output=output,
                    metadata={
                        "latency_ms": round((time.time() - entry["start"]) * 1000),
                        **(metadata or {}),
                    }
                )
            except Exception:
                pass

    def finish(self, result: dict):
        """
        Finalize the trace with the full result.
        Records: answer length, source count, confidence, pipeline outcome.
        """
        latency_ms = round((time.time() - self.start_time) * 1000)
        if self.trace:
            try:
                self.trace.update(
                    output={
                        "answer_length": len(result.get("answer", "")),
                        "sources_count": len(result.get("sources", [])),
                        "query_type": result.get("query_type", "unknown"),
                        "insufficient_context": result.get("insufficient_context", False),
                    },
                    metadata={
                        "confidence": result.get("confidence", 0),
                        "latency_ms": latency_ms,
                        "pipeline": "langgraph_5node",
                        "kb_vectors": 450,
                    }
                )
                # Score the trace for the Ragas dashboard
                if not result.get("insufficient_context"):
                    self.trace.score(
                        name="confidence",
                        value=result.get("confidence", 0),
                        comment="Sufficiency judge confidence score",
                    )
                    self.trace.score(
                        name="sources_retrieved",
                        value=min(len(result.get("sources", [])) / 5, 1.0),
                        comment="Fraction of max sources retrieved",
                    )
            except Exception:
                pass

    def __exit__(self, *args):
        # Flush is async in Langfuse; traces are sent on program exit or flush()
        pass


class BillingTracer:
    """Trace a billing AI analysis call."""

    def __init__(self, note_id: int):
        self.note_id    = note_id
        self.trace      = None
        self.start_time = time.time()

    def __enter__(self):
        lf = get_langfuse()
        if lf:
            try:
                self.trace = lf.trace(
                    name="billing_analysis",
                    input={"note_id": self.note_id},
                    tags=["medisight", "billing"],
                )
            except Exception:
                pass
        return self

    def finish(self, codes_count: int, denial_flags: int, patient_summary_ok: bool):
        latency_ms = round((time.time() - self.start_time) * 1000)
        if self.trace:
            try:
                self.trace.update(
                    output={
                        "billing_codes_suggested": codes_count,
                        "denial_flags": denial_flags,
                        "patient_summary_generated": patient_summary_ok,
                    },
                    metadata={"latency_ms": latency_ms}
                )
                self.trace.score(
                    name="codes_suggested",
                    value=min(codes_count / 3, 1.0),
                    comment="Billing codes suggested (target: 3)",
                )
            except Exception:
                pass

    def __exit__(self, *args):
        pass


def flush_traces():
    """Call this on app shutdown to ensure all traces are sent."""
    lf = get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:
            pass
