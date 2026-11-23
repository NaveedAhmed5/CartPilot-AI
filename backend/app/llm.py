"""Chat model factory.

Production uses Claude Haiku 5.5 through langchain-anthropic (official Anthropic SDK
underneath). Groq is supported only so the team can develop and test for free; the
deployed agent must run with LLM_PROVIDER=anthropic.
"""

from typing import Any, Dict, Optional, Sequence

from langchain_core.language_models import BaseChatModel

from .config import settings

_model_override: Optional[BaseChatModel] = None


def set_model_override(model: Optional[BaseChatModel]) -> None:
    """Inject a model (used by the offline test-suite)."""
    global _model_override
    _model_override = model


def provider() -> str:
    if _model_override is not None:
        return "test"
    return settings.llm_provider


def supports_prompt_caching() -> bool:
    return provider() == "anthropic"


def _anthropic(effort: Optional[str] = "low") -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    # Thinking is disabled (allowed at effort <= high on Haiku 5.5) to keep the
    # agent fast and cheap; effort "low" suits a short-reply chat agent. No
    # sampling parameters are sent (Haiku 5.5 rejects non-default values).
    extra: Dict[str, Any] = {"output_config": {"effort": effort}} if effort else {}
    return ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.max_output_tokens,
        thinking={"type": "disabled"},
        default_request_timeout=settings.llm_timeout_s,
        max_retries=2,
        **extra,
    )


def _groq(api_key: str) -> BaseChatModel:
    from langchain_groq import ChatGroq

    # No SDK retries: on a 429 we move straight to the next key instead of waiting.
    return ChatGroq(
        model=settings.groq_model,
        api_key=api_key,
        max_tokens=settings.max_output_tokens * 2,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )


def get_chat_model(tools: Sequence[Any]) -> Any:
    """Return a runnable chat model with `tools` bound."""
    if _model_override is not None:
        return _model_override.bind_tools(list(tools))
    if settings.llm_provider == "anthropic":
        primary = _anthropic("low").bind_tools(list(tools))
        # Safety net: if the API ever rejects the effort setting (400), retry once
        # with the model defaults instead of failing every chat. Retryable errors
        # (429/5xx/timeouts) are already retried inside the SDK client.
        import anthropic

        backup = _anthropic(None).bind_tools(list(tools))
        return primary.with_fallbacks([backup], exceptions_to_handle=(anthropic.BadRequestError,))
    if settings.llm_provider == "groq":
        keys = settings.groq_api_keys
        if not keys:
            raise RuntimeError("GROQ_API_KEYS is not set")
        bound = [_groq(k).bind_tools(list(tools)) for k in keys]
        if len(bound) == 1:
            return bound[0]
        # Rotate the starting key per call so free-tier rate limits are spread out.
        from itertools import count

        from langchain_core.runnables import RunnableLambda

        chains = [bound[i].with_fallbacks(bound[i + 1:] + bound[:i]) for i in range(len(bound))]
        counter = count()
        return RunnableLambda(lambda msgs: chains[next(counter) % len(chains)].invoke(msgs))
    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
