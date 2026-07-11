"""Pure alias-normalization helpers for model entity resolution."""

from __future__ import annotations

import re
import unicodedata

# Canonical organization ids used for matching only. Raw source strings remain in
# model_alias rows; these values help compare provider slugs across sources.
ORG_SYNONYMS: dict[str, str] = {
    "anthropic-ai": "anthropic",
    "azure-openai": "openai",
    "deepseek-ai": "deepseek",
    "google-ai": "google",
    "google-ai-studio": "google",
    "google-deepmind": "google",
    "meta-ai": "meta",
    "meta-llama": "meta",
    "mistralai": "mistral",
    "mistral-ai": "mistral",
    "open-ai": "openai",
    "openai": "openai",
    "qwenlm": "qwen",
    "qwen-team": "qwen",
    "x-ai": "xai",
    "xai": "xai",
}

_DATE_RE = re.compile(r"(?<!\d)(\d{4})(?:-?(\d{2})-?(\d{2}))(?!\d)")
_DIGIT_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_SEPARATOR_RE = re.compile(r"[\s_\-/]+")
_MODIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("free", re.compile(r"(?i)(?::free|(?:^|[-_./\s])free(?:$|[-_./\s]))")),
    ("fp8", re.compile(r"(?i)(?:^|[-_./\s])fp8(?:$|[-_./\s])")),
    ("gguf", re.compile(r"(?i)(?:^|[-_./\s])gguf(?:$|[-_./\s])")),
    ("q4_k_m", re.compile(r"(?i)(?:^|[-_./\s])q4[-_]?k[-_]?m(?:$|[-_./\s])")),
    ("awq", re.compile(r"(?i)(?:^|[-_./\s])awq(?:$|[-_./\s])")),
    ("turbo", re.compile(r"(?i)(?:^|[-_./\s])turbo(?:$|[-_./\s])")),
    ("latest", re.compile(r"(?i)(?:^|[-_./\s])latest(?:$|[-_./\s])")),
    ("preview", re.compile(r"(?i)(?:^|[-_./\s])preview(?:$|[-_./\s])")),
    ("thinking", re.compile(r"(?i)(?:^|[-_./\s])thinking(?:$|[-_./\s])")),
    ("high", re.compile(r"(?i)(?:^|[-_./\s])high(?:$|[-_./\s])")),
    ("medium", re.compile(r"(?i)(?:^|[-_./\s])medium(?:$|[-_./\s])")),
    ("low", re.compile(r"(?i)(?:^|[-_./\s])low(?:$|[-_./\s])")),
)
_SURFACE_PREFIX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bedrock", re.compile(r"(?i)^bedrock(?:[:/_-]|\.)")),
    ("vertex_ai", re.compile(r"(?i)^(?:vertex[_-]?ai|vertex)(?:[:/_-]|\.)")),
    ("azure_ai", re.compile(r"(?i)^(?:azure[_-]?ai|azure)(?:[:/_-]|\.)")),
    ("groq", re.compile(r"(?i)^groq(?:[:/_-]|\.)")),
    ("together_ai", re.compile(r"(?i)^(?:together[_-]?ai|together)(?:[:/_-]|\.)")),
    ("us", re.compile(r"(?i)^us\.")),
    ("eu", re.compile(r"(?i)^eu\.")),
    ("global", re.compile(r"(?i)^global\.")),
)


def normalize_alias(s: str) -> str:
    """Return a matching-only normalized alias string.

    The result is not a display value and must not replace raw source strings.
    It NFKC-normalizes, strips, lowercases, and collapses common route/model
    separators to one hyphen so version forms like ``3.5`` and ``3-5`` compare.
    """

    normalized = unicodedata.normalize("NFKC", s).strip().lower()
    normalized = _DIGIT_DOT_RE.sub("-", normalized)
    normalized = _SEPARATOR_RE.sub("-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")


def extract_date_tokens(s: str) -> list[str]:
    """Extract YYYYMMDD and YYYY-MM-DD tokens as canonical YYYY-MM-DD values."""

    tokens: list[str] = []
    for match in _DATE_RE.finditer(s):
        token = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        if token not in tokens:
            tokens.append(token)
    return tokens


def extract_surface_prefix(s: str) -> str | None:
    """Return a recognized provider/region prefix, if the alias starts with one."""

    candidate = unicodedata.normalize("NFKC", s).strip().lower()
    for prefix, pattern in _SURFACE_PREFIX_PATTERNS:
        if pattern.search(candidate):
            return prefix
    return None


def extract_modifiers(s: str) -> list[str]:
    """Detect known alias modifiers such as price tiers, quantizations, and effort."""

    modifiers: list[str] = []
    for modifier, pattern in _MODIFIER_PATTERNS:
        if pattern.search(s) and modifier not in modifiers:
            modifiers.append(modifier)
    return modifiers


def canonical_org(s: str) -> str:
    """Normalize an organization/provider slug for cross-source comparison."""

    normalized = normalize_alias(s)
    return ORG_SYNONYMS.get(normalized, normalized)
