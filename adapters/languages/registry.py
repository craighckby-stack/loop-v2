"""Language adapter registry. Adding a language = add module + one line here."""

from __future__ import annotations

from adapters.base import LanguageAdapter
from adapters.languages.python_adapter.adapter import PythonAdapter
from adapters.languages.go_adapter.adapter import GoAdapter

_ADAPTERS: dict[str, type[LanguageAdapter]] = {
    PythonAdapter.name: PythonAdapter,
    GoAdapter.name: GoAdapter,
}


def get_adapter(language: str) -> LanguageAdapter:
    try:
        return _ADAPTERS[language.lower()]()
    except KeyError:
        raise KeyError(
            f"no adapter for language {language!r}; known: {sorted(_ADAPTERS)}"
        ) from None


def known_languages() -> list[str]:
    return sorted(_ADAPTERS)
