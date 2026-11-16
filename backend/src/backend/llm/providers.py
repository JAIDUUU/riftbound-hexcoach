"""One chat-model entry point backed by a configurable provider fallback chain.

The chain is configuration, not code: `LLM_PROVIDER_CHAIN` is a comma-separated list of
`provider:model` entries (the model id may itself contain colons, as OpenRouter's do).
Providers without an API key in the environment are skipped, so a developer with only one
key still gets a working chain. If every configured provider errors at request time,
`AllProvidersFailedError` carries each provider's failure (this later backs the
"demo quota reached" message).
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import SecretStr

from backend.config import MissingConfigError, optional_env

DEFAULT_PROVIDER_CHAIN = (
    "gemini:gemini-3.8-flash"
    ",groq:openai/gpt-oss-120b"
    ",openrouter:nvidia/nemotron-3-ultra-550b-a55b:free"
)


class AllProvidersFailedError(RuntimeError):
    """Every provider in the chain errored for one request."""

    def __init__(self, failures: Sequence[tuple[str, Exception]]):
        self.failures = list(failures)
        details = "; ".join(f"{provider}: {error}" for provider, error in failures)
        super().__init__(f"All chat providers failed ({details})")


class ProviderChain(Runnable[LanguageModelInput, BaseMessage]):
    """Tries each model in order; the first one that answers wins."""

    def __init__(
        self, models: Sequence[tuple[str, BaseChatModel]], skipped: Sequence[str] = ()
    ) -> None:
        if not models:
            raise ValueError("A provider chain needs at least one model.")
        self.models = list(models)
        self.skipped = list(skipped)

    def ask(
        self, input: LanguageModelInput, config: RunnableConfig | None = None
    ) -> tuple[str, BaseMessage]:
        """Like `invoke`, but also names the provider that answered."""
        failures: list[tuple[str, Exception]] = []
        for provider, model in self.models:
            try:
                return provider, model.invoke(input, config)
            except Exception as error:
                failures.append((provider, error))
        raise AllProvidersFailedError(failures)

    def invoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None, **kwargs: Any
    ) -> BaseMessage:
        return self.ask(input, config)[1]


# Retrying within a provider delays the failover that is this module's whole point, so
# each model gets one retry and a tight timeout; the chain itself is the retry strategy.
_MAX_RETRIES = 1
_TIMEOUT_SECONDS = 30


def _gemini(model: str, key: str) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model, api_key=SecretStr(key), max_retries=_MAX_RETRIES, timeout=_TIMEOUT_SECONDS
    )


def _groq(model: str, key: str) -> BaseChatModel:
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model,
        api_key=SecretStr(key),
        max_retries=_MAX_RETRIES,
        timeout=_TIMEOUT_SECONDS,
    )


def _openrouter(model: str, key: str) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=SecretStr(key),
        base_url="https://openrouter.ai/api/v1",
        max_retries=_MAX_RETRIES,
        timeout=_TIMEOUT_SECONDS,
    )


_PROVIDERS = {
    "gemini": ("GOOGLE_API_KEY", _gemini),
    "groq": ("GROQ_API_KEY", _groq),
    "openrouter": ("OPENROUTER_API_KEY", _openrouter),
}


def parse_chain_spec(spec: str) -> list[tuple[str, str]]:
    """`"gemini:gemini-2.5-flash, groq:llama-3.3-70b"` -> [(provider, model), ...]."""
    entries: list[tuple[str, str]] = []
    for raw_entry in spec.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        provider, _, model = entry.partition(":")
        if provider not in _PROVIDERS or not model:
            known = ", ".join(_PROVIDERS)
            raise ValueError(f"Bad chain entry {entry!r}; expected one of {known}, then :model")
        entries.append((provider, model))
    if not entries:
        raise ValueError("The provider chain is empty.")
    return entries


def chat_chain(spec: str | None = None) -> ProviderChain:
    """The configured chain, skipping providers whose API key is not set."""
    spec = spec or optional_env("LLM_PROVIDER_CHAIN") or DEFAULT_PROVIDER_CHAIN
    models: list[tuple[str, BaseChatModel]] = []
    skipped: list[str] = []
    for provider, model in parse_chain_spec(spec):
        key_name, build = _PROVIDERS[provider]
        key = optional_env(key_name)
        if key is None:
            skipped.append(provider)
        else:
            models.append((provider, build(model, key)))
    if not models:
        raise MissingConfigError(
            "No chat provider has an API key; set GOOGLE_API_KEY, GROQ_API_KEY or "
            "OPENROUTER_API_KEY (see backend/.env.example)."
        )
    return ProviderChain(models, skipped)
