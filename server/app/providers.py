# app/providers.py
"""Model-provider selection: lets each chat session pick Mistral (default,
free tier) or OpenAI/GPT-4.1, with an optional per-session personal API key
when the shared quota runs out. See cahier_de_labo.md 2026-09-15 for the
rationale (local demonstrator for trainers, not a public production service)."""

from __future__ import annotations

import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, List, Optional

from agents import AsyncOpenAI, FileSearchTool, ModelSettings, OpenAIResponsesModel

from app.local_search import build_local_search_tool

PROVIDER_MISTRAL = "mistral"
PROVIDER_OPENAI = "openai"
DEFAULT_PROVIDER = PROVIDER_MISTRAL
KNOWN_PROVIDERS = (PROVIDER_MISTRAL, PROVIDER_OPENAI)

VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "vs_6a116b3869e08191aa26f247b322a8c1")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral/mistral-large-latest")
MISTRAL_VISION_MODEL = os.getenv("MISTRAL_VISION_MODEL", "mistral/pixtral-large-latest")


@dataclass
class ProviderChoice:
    provider: str = DEFAULT_PROVIDER
    api_key: Optional[str] = None  # user-supplied override; never logged, never persisted to disk


current_provider: ContextVar[ProviderChoice] = ContextVar("current_provider", default=ProviderChoice())


def uses_shared_openai_key(choice: ProviderChoice) -> bool:
    """True only for the default OpenAI path with no personal key: the only
    case where the shared, org-private vector store (FileSearchTool) is
    reachable. A trainer's own key (OpenAI or Mistral) has no access to it."""
    return choice.provider == PROVIDER_OPENAI and not choice.api_key


def build_model(choice: ProviderChoice, *, openai_model: str = "gpt-4.1", vision: bool = False) -> Any:
    if choice.provider == PROVIDER_OPENAI:
        if choice.api_key:
            client = AsyncOpenAI(api_key=choice.api_key)
            return OpenAIResponsesModel(model=openai_model, openai_client=client)
        # Bare model name -> SDK default client, i.e. the shared OPENAI_API_KEY
        # env secret. Unchanged from the pre-multi-provider behaviour.
        return openai_model
    model_name = MISTRAL_VISION_MODEL if vision else MISTRAL_MODEL
    key = choice.api_key or MISTRAL_API_KEY
    from agents.extensions.models.litellm_model import LitellmModel
    return LitellmModel(model=model_name, api_key=key)


def build_tools(choice: ProviderChoice, *, max_results: int = 8) -> List[Any]:
    if uses_shared_openai_key(choice):
        return [FileSearchTool(max_num_results=max_results, vector_store_ids=[VECTOR_STORE_ID])]
    return [build_local_search_tool(max_results=max_results)]


def build_model_settings(choice: ProviderChoice) -> ModelSettings:
    if choice.provider == PROVIDER_OPENAI:
        return ModelSettings(store=True)
    return ModelSettings()


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def strip_code_fence(text: str) -> str:
    """Every prompt in this file says "Return ONLY JSON" / "no markdown code
    fences", but Mistral (unlike GPT-4.1 with the same instructions, both
    tested live 2026-09-15) still sometimes wraps its answer in a ```json
    ... ``` block, which breaks every json.loads() call site outright
    (JSONDecodeError: Expecting value at char 0). Strip it defensively rather
    than trusting the instruction."""
    match = _CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


async def run_agent_text(agent: Any, prompt: Any, ctx: Any, *, retries: int = 1) -> str:
    """Runner.run wrapper: strips an accidental markdown code fence from the
    output (see strip_code_fence) and retries once on a genuinely blank
    final_output, reproduced live on the free Mistral tier after a
    tool-calling turn. Bounded on purpose: a mitigation for an observed
    flake, not a general-purpose resilience loop."""
    from agents import Runner

    raw = ""
    for _ in range(retries + 1):
        res = await Runner.run(agent, prompt, context=ctx)
        raw = strip_code_fence((res.final_output or "").strip())
        if raw:
            return raw
    return raw


_QUOTA_ERROR_HINTS = ("rate limit", "quota", "429", "insufficient_quota", "capacity")
_AUTH_ERROR_HINTS = ("401", "unauthorized", "invalid api key", "authentication")


def friendly_llm_error(exc: Exception) -> str:
    """Turns a raw provider exception into a message a trainer can act on,
    instead of a bare stack-trace fragment. Never includes the api_key
    (the SDK's own exception messages don't echo it back)."""
    text = str(exc).lower()
    choice = current_provider.get()
    provider_label = "Mistral" if choice.provider == PROVIDER_MISTRAL else "OpenAI/GPT-4.1"
    if any(hint in text for hint in _QUOTA_ERROR_HINTS):
        return (
            f"⚠️ Quota {provider_label} dépassé pour le moment. "
            "Ouvre les réglages (icône engrenage) pour ajouter ta propre clé API, "
            "ou réessaie plus tard."
        )
    if any(hint in text for hint in _AUTH_ERROR_HINTS):
        return (
            f"⚠️ Clé API {provider_label} refusée. "
            "Vérifie la clé collée dans les réglages, ou retire-la pour revenir à la clé partagée."
        )
    return f"⚠️ Erreur interne ({provider_label}) : {exc}"
