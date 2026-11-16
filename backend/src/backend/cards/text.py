"""Deterministic cleanup of Riftbound card text (raw text -> cleaned text)."""

import re

_ICON = re.compile(r":rb_[a-z0-9_]+:")
_ICON_RUN = re.compile(rf"(?:{_ICON.pattern})+")
_ENERGY = re.compile(r":rb_energy_(\d+):")
_RUNE = re.compile(r":rb_rune_([a-z]+):")
_STATIC_ICON_WORDS = {":rb_might:": "Might", ":rb_exhaust:": "Exhaust"}

# Rifthunt writes the arrows that separate a cost from its effect as `[>]` and `[>>]`.
# The meaning of `[>>]` is unverified; it is kept visually distinct from `[>]`.
_SYMBOLS = {"[>>]": " \u21d2 ", "[>]": " \u2192 "}
_NO_TEXT_MARKER = "[NO TEXT]"
_KEYWORD_BRACKETS = re.compile(r"\[([^\]]+)\]")
_SPACES = re.compile(r"[ \t]+")


def _icon_to_words(shortcode: str) -> str:
    if energy := _ENERGY.fullmatch(shortcode):
        return f"{energy.group(1)} Energy"
    if rune := _RUNE.fullmatch(shortcode):
        return f"{rune.group(1).title()} Rune"
    return _STATIC_ICON_WORDS.get(shortcode, shortcode)


def _icon_run_to_words(run: re.Match[str]) -> str:
    return " ".join(_icon_to_words(icon) for icon in _ICON.findall(run.group(0)))


def _tidy_lines(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def clean_card_text(raw: str | None) -> str:
    text = (raw or "").replace(_NO_TEXT_MARKER, "")
    for symbol, replacement in _SYMBOLS.items():
        text = text.replace(symbol, replacement)
    text = _ICON_RUN.sub(_icon_run_to_words, text)
    return _tidy_lines(_KEYWORD_BRACKETS.sub(r"\1", text))


def leftover_shortcodes(cleaned: str) -> list[str]:
    """Icon shortcodes still present after cleaning: the ones `clean_card_text` doesn't know."""
    return _ICON.findall(cleaned)
