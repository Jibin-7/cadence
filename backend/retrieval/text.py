"""Text normalization and lightweight query parsing for music metadata."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

STOP_WORDS = {"a", "an", "the", "of", "to", "by", "from", "for", "and", "or", "in", "on", "with", "is", "i", "you", "me", "it", "im", "i'm"}
TOKEN_RE = re.compile(r"[\w]+(?:'[\w]+)?", re.UNICODE)


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return folded.casefold().replace("'", "")


def tokenize(text: str, *, remove_stop_words: bool = False) -> list[str]:
    words = TOKEN_RE.findall(normalize(text))
    return [word for word in words if word not in STOP_WORDS] if remove_stop_words else words


@dataclass(frozen=True)
class ParsedQuery:
    raw: str
    terms: tuple[str, ...]
    phrases: tuple[tuple[str, ...], ...]
    operators: tuple[str, ...]
    boolean_mode: bool


def process_query(query: str) -> ParsedQuery:
    phrases = tuple(tuple(tokenize(m.group(1))) for m in re.finditer(r'"([^\"]+)"', query))
    stripped = re.sub(r'"[^\"]+"', " ", query)
    ops = tuple(m.group(0).upper() for m in re.finditer(r"\b(?:AND|OR|NOT)\b", stripped, re.I))
    raw_terms = tokenize(re.sub(r"\b(?:AND|OR|NOT)\b", " ", stripped, flags=re.I))
    content_terms = [term for term in raw_terms if term not in STOP_WORDS]
    terms = tuple(content_terms or raw_terms)
    return ParsedQuery(query, terms, phrases, ops, bool(ops))
