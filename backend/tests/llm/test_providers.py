from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

import backend.config
from backend.config import MissingConfigError
from backend.llm.providers import (
    AllProvidersFailedError,
    ProviderChain,
    chat_chain,
    parse_chain_spec,
)


class _FailingChatModel(FakeListChatModel):
    """A chat model whose every call fails, like a provider that is down or rate limited."""

    def _call(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("429 rate limited")


def _answering(text: str) -> FakeListChatModel:
    return FakeListChatModel(responses=[text])


def test_the_first_answering_provider_wins() -> None:
    chain = ProviderChain([("gemini", _answering("pong")), ("groq", _answering("never"))])

    provider, message = chain.ask("ping")

    assert provider == "gemini"
    assert message.text() == "pong"


def test_a_failing_provider_falls_through_to_the_next() -> None:
    chain = ProviderChain(
        [("gemini", _FailingChatModel(responses=[])), ("groq", _answering("pong"))]
    )

    provider, message = chain.ask("ping")

    assert provider == "groq"
    assert message.text() == "pong"


def test_invoke_returns_the_message_like_any_runnable() -> None:
    chain = ProviderChain([("gemini", _answering("pong"))])

    assert chain.invoke("ping").text() == "pong"


def test_when_every_provider_fails_the_error_names_them_all() -> None:
    chain = ProviderChain(
        [("gemini", _FailingChatModel(responses=[])), ("groq", _FailingChatModel(responses=[]))]
    )

    with pytest.raises(AllProvidersFailedError, match=r"gemini.*groq") as caught:
        chain.ask("ping")

    assert [provider for provider, _ in caught.value.failures] == ["gemini", "groq"]


def test_an_empty_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ProviderChain([])


def test_chain_specs_keep_colons_inside_model_ids() -> None:
    spec = "gemini:gemini-2.5-flash, openrouter:deepseek/deepseek-chat-v3-0324:free"

    assert parse_chain_spec(spec) == [
        ("gemini", "gemini-2.5-flash"),
        ("openrouter", "deepseek/deepseek-chat-v3-0324:free"),
    ]


def test_an_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="openai:gpt-6"):
        parse_chain_spec("openai:gpt-6")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    def skip_loading(path: Path) -> bool:
        return False

    monkeypatch.setattr(backend.config, "load_dotenv", skip_loading)
    for name in ("LLM_PROVIDER_CHAIN", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


def test_providers_without_keys_are_skipped(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GROQ_API_KEY", "gsk-test")

    chain = chat_chain()

    assert [provider for provider, _ in chain.models] == ["groq"]
    assert chain.skipped == ["gemini", "openrouter"]


def test_without_any_key_the_chain_is_a_clear_error(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(MissingConfigError, match="API key"):
        chat_chain()
