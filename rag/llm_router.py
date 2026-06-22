"""
FILE: rag/llm_router.py
========================
WHAT THIS FILE IS:
    Multi-model LLM router with:
    - OpenAI GPT-4o as primary (faster, cheaper for classification tasks)
    - Claude Sonnet as fallback (better reasoning, used when OpenAI fails)
    - Token cost tracking per query
    - Automatic retry with fallback on rate limit or API error

CONCEPT — Why multi-model routing matters:
    Production AI systems never depend on a single provider.
    This router gives you:
    1. Cost optimization: use cheaper model (Haiku/GPT-4o-mini) for simple tasks
    2. Reliability: if OpenAI quota is hit, Claude picks up automatically
    3. Cost tracking: log every token used and its USD cost
    4. Auditability: every LLM call is logged with model, tokens, cost

TOKEN COST (June 2026 approximate pricing):
    GPT-4o:        $2.50/1M input,  $10.00/1M output
    GPT-4o-mini:   $0.15/1M input,  $0.60/1M output
    Claude Sonnet: $3.00/1M input,  $15.00/1M output
    Claude Haiku:  $0.25/1M input,  $1.25/1M output

USAGE:
    from rag.llm_router import router_llm, get_cost_summary

    response = await router_llm(
        messages=[{"role": "user", "content": "chest pain differential"}],
        task="generation",     # "classification" | "expansion" | "generation" | "judgment"
        max_tokens=1500,
    )
    print(response.content)
    print(get_cost_summary())  # {"total_queries": 5, "total_cost_usd": 0.0034, ...}
"""

import os
import time
import asyncio
from typing import Literal, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ── TOKEN COST TABLE (per 1M tokens) ─────────────────────────────────────────

COST_TABLE = {
    # OpenAI
    "gpt-4o":              {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":         {"input": 0.15,  "output": 0.60},
    # Anthropic
    "claude-haiku-4-5":    {"input": 0.25,  "output": 1.25},
    "claude-sonnet-4-6":   {"input": 3.00,  "output": 15.00},
}

# ── TASK → MODEL MAPPING ──────────────────────────────────────────────────────

# For each task type, we try models in order until one succeeds
TASK_MODEL_PRIORITY = {
    # Fast classification — use cheap models first
    "classification": ["gpt-4o-mini", "claude-haiku-4-5"],
    # Query expansion — cheap models work well
    "expansion":      ["gpt-4o-mini", "claude-haiku-4-5"],
    # Sufficiency judgment — needs reasoning, still use cheaper models
    "judgment":       ["gpt-4o-mini", "claude-haiku-4-5"],
    # Final answer generation — use best models
    "generation":     ["gpt-4o", "claude-sonnet-4-6"],
}

# ── COST TRACKER ──────────────────────────────────────────────────────────────

@dataclass
class CostTracker:
    total_queries:    int   = 0
    total_input_tokens:  int   = 0
    total_output_tokens: int   = 0
    total_cost_usd:   float = 0.0
    by_model:         dict  = field(default_factory=lambda: defaultdict(lambda: {"queries": 0, "cost": 0.0, "tokens": 0}))
    fallbacks:        int   = 0
    errors:           int   = 0

_tracker = CostTracker()


def track_usage(model: str, input_tokens: int, output_tokens: int, was_fallback: bool = False):
    """Record token usage and cost for one LLM call."""
    costs = COST_TABLE.get(model, {"input": 0, "output": 0})
    cost = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    _tracker.total_queries       += 1
    _tracker.total_input_tokens  += input_tokens
    _tracker.total_output_tokens += output_tokens
    _tracker.total_cost_usd      += cost
    _tracker.by_model[model]["queries"] += 1
    _tracker.by_model[model]["cost"]    += cost
    _tracker.by_model[model]["tokens"]  += input_tokens + output_tokens
    if was_fallback:
        _tracker.fallbacks += 1


def get_cost_summary() -> dict:
    """Get full cost breakdown for dashboard display."""
    return {
        "total_queries":       _tracker.total_queries,
        "total_tokens":        _tracker.total_input_tokens + _tracker.total_output_tokens,
        "total_input_tokens":  _tracker.total_input_tokens,
        "total_output_tokens": _tracker.total_output_tokens,
        "total_cost_usd":      round(_tracker.total_cost_usd, 6),
        "avg_cost_per_query":  round(_tracker.total_cost_usd / max(_tracker.total_queries, 1), 6),
        "fallback_count":      _tracker.fallbacks,
        "fallback_rate":       round(_tracker.fallbacks / max(_tracker.total_queries, 1), 3),
        "by_model": {
            model: {
                "queries": data["queries"],
                "cost_usd": round(data["cost"], 6),
                "total_tokens": data["tokens"],
            }
            for model, data in _tracker.by_model.items()
        },
    }


# ── LLM RESPONSE WRAPPER ──────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    content:       str
    model_used:    str
    input_tokens:  int
    output_tokens: int
    cost_usd:      float
    was_fallback:  bool
    latency_ms:    int


# ── OPENAI CALL ───────────────────────────────────────────────────────────────

async def call_openai(
    messages: list,
    model: str,
    max_tokens: int,
    temperature: float,
) -> Optional[LLMResponse]:
    """
    Call OpenAI API. Returns None if OPENAI_API_KEY not set or call fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)

        start = time.time()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_ms = round((time.time() - start) * 1000)

        content       = response.choices[0].message.content or ""
        input_tokens  = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost          = (input_tokens * COST_TABLE.get(model, {"input": 0})["input"] +
                        output_tokens * COST_TABLE.get(model, {"output": 0})["output"]) / 1_000_000

        return LLMResponse(
            content=content,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            was_fallback=False,
            latency_ms=latency_ms,
        )

    except Exception as e:
        print(f"   [LLM Router] OpenAI {model} failed: {type(e).__name__}: {str(e)[:60]}")
        return None


# ── ANTHROPIC CALL ────────────────────────────────────────────────────────────

async def call_anthropic(
    messages: list,
    model: str,
    max_tokens: int,
    temperature: float,
    system: Optional[str] = None,
    was_fallback: bool = False,
) -> Optional[LLMResponse]:
    """
    Call Anthropic Claude API. Returns None if call fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)

        # Convert OpenAI-style messages to Anthropic format
        anthropic_messages = []
        anthropic_system   = system

        for msg in messages:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                anthropic_system = content  # Anthropic uses separate system param
            else:
                anthropic_messages.append({"role": role, "content": content})

        kwargs = {
            "model":      model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages":   anthropic_messages,
        }
        if anthropic_system:
            kwargs["system"] = anthropic_system

        start = time.time()
        response = await client.messages.create(**kwargs)
        latency_ms = round((time.time() - start) * 1000)

        content       = response.content[0].text if response.content else ""
        input_tokens  = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost          = (input_tokens * COST_TABLE.get(model, {"input": 0})["input"] +
                        output_tokens * COST_TABLE.get(model, {"output": 0})["output"]) / 1_000_000

        return LLMResponse(
            content=content,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            was_fallback=was_fallback,
            latency_ms=latency_ms,
        )

    except Exception as e:
        print(f"   [LLM Router] Anthropic {model} failed: {type(e).__name__}: {str(e)[:60]}")
        return None


# ── MAIN ROUTER ───────────────────────────────────────────────────────────────

async def router_llm(
    messages: list,
    task: Literal["classification", "expansion", "judgment", "generation"] = "generation",
    max_tokens: int = 500,
    temperature: float = 0.1,
    system: Optional[str] = None,
) -> LLMResponse:
    """
    Route an LLM call through models in priority order.

    For generation tasks: tries GPT-4o first, falls back to Claude Sonnet.
    For classification tasks: tries GPT-4o-mini first, falls back to Claude Haiku.

    Always tracks token usage and cost.

    INPUT:
        messages: list of {"role": "user"/"system", "content": "..."} dicts
        task: one of "classification" | "expansion" | "judgment" | "generation"
        max_tokens: max response tokens
        temperature: sampling temperature
        system: optional system prompt string

    OUTPUT: LLMResponse with content, model_used, cost_usd, etc.

    RAISES: RuntimeError if all models fail
    """
    model_list = TASK_MODEL_PRIORITY.get(task, ["gpt-4o", "claude-sonnet-4-6"])
    is_fallback = False
    last_error  = None

    for model in model_list:
        try:
            if model.startswith("gpt-"):
                # Add system message to messages list for OpenAI
                openai_messages = messages
                if system:
                    openai_messages = [{"role": "system", "content": system}] + messages
                result = await call_openai(openai_messages, model, max_tokens, temperature)
            else:
                result = await call_anthropic(messages, model, max_tokens, temperature, system, is_fallback)

            if result is not None:
                # Track usage
                track_usage(model, result.input_tokens, result.output_tokens, is_fallback)
                model_icon = "🤖" if model.startswith("gpt-") else "🧠"
                fallback_tag = " [FALLBACK]" if is_fallback else ""
                print(f"   [LLM Router] {model_icon} {model}{fallback_tag} | {result.input_tokens}in/{result.output_tokens}out | ${result.cost_usd:.5f} | {result.latency_ms}ms")
                return result

        except Exception as e:
            last_error = e
            _tracker.errors += 1

        # Next model is a fallback
        is_fallback = True
        print(f"   [LLM Router] Trying fallback...")

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


# ── CONVENIENCE HELPERS ───────────────────────────────────────────────────────

async def classify(prompt: str, max_tokens: int = 50) -> str:
    """Quick classification call — uses cheapest model."""
    result = await router_llm(
        messages=[{"role": "user", "content": prompt}],
        task="classification",
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return result.content.strip()


async def expand(prompt: str, max_tokens: int = 200) -> str:
    """Query expansion — uses cheap model."""
    result = await router_llm(
        messages=[{"role": "user", "content": prompt}],
        task="expansion",
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return result.content.strip()


async def judge(prompt: str, max_tokens: int = 10) -> str:
    """Sufficiency judgment — uses cheap model."""
    result = await router_llm(
        messages=[{"role": "user", "content": prompt}],
        task="judgment",
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return result.content.strip()


async def generate(
    messages: list,
    system: Optional[str] = None,
    max_tokens: int = 1500,
) -> str:
    """Full generation — uses best model with fallback."""
    result = await router_llm(
        messages=messages,
        task="generation",
        max_tokens=max_tokens,
        temperature=0.1,
        system=system,
    )
    return result.content
