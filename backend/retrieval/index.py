"""In-memory inverted index constructed only from live provider responses."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log
from math import sqrt

FIELDS = ("title", "artist", "album", "genre")
ZONE_WEIGHTS = {"title": 3.0, "artist": 2.4, "album": 1.5, "genre": 1.0}


@dataclass
class IndexedSong:
    song: dict
    fields: dict[str, Counter]


class InvertedIndex:
    def __init__(self, documents: list[dict], tokenizer):
        self.docs: dict[str, IndexedSong] = {}
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.field_postings: dict[str, dict[str, set[str]]] = {f: defaultdict(set) for f in FIELDS}
        self.tokenizer = tokenizer
        for song in documents:
            doc_id = str(song["id"])
            counts = {f: Counter(tokenizer(song.get(f, ""))) for f in FIELDS}
            self.docs[doc_id] = IndexedSong(song, counts)
            for field, terms in counts.items():
                for term in terms:
                    self.postings[term].add(doc_id)
                    self.field_postings[field][term].add(doc_id)

    def lookup(self, term: str) -> set[str]:
        """Prefix-aware lookup supports short partial title/artist terms."""
        found = set(self.postings.get(term, set()))
        if len(term) >= 3:
            for indexed in self.postings:
                if indexed.startswith(term):
                    found.update(self.postings[indexed])
        return found

    def boolean_candidates(self, terms: list[str], operators: tuple[str, ...]) -> set[str]:
        if not terms:
            return set()
        sets = [self.lookup(t) for t in terms]
        value = sets[0]
        op_idx = 0
        for next_set in sets[1:]:
            op = operators[op_idx] if op_idx < len(operators) else "AND"
            op_idx += 1
            if op == "OR":
                value = value | next_set
            elif op == "NOT":
                value = value - next_set
            else:
                value = value & next_set
        return value

    def document_frequency(self, term: str) -> int:
        return len(self.lookup(term))


def tfidf_score(index: InvertedIndex, doc_id: str, terms: list[str], phrases=()) -> tuple[float, dict]:
    """Weighted zone TF-IDF cosine-like query-document score and explanation."""
    n_docs = max(1, len(index.docs))
    item = index.docs[doc_id]
    contributions: dict[str, float] = {}
    zone_hits: dict[str, float] = {}
    query_vector: dict[str, float] = {}
    for term in set(terms):
        df = index.document_frequency(term)
        if not df:
            continue
        idf = log(1 + n_docs / df)
        for vector_term in index.postings:
            if vector_term == term or (len(term) >= 3 and vector_term.startswith(term)):
                query_vector[vector_term] = idf
        term_score = 0.0
        for field, counts in item.fields.items():
            tf = counts.get(term, 0)
            if not tf:
                # Prefix match is a genuine partial term match; keep its signal lower.
                tf = sum(v for k, v in counts.items() if len(term) >= 3 and k.startswith(term)) * 0.65
            if tf:
                value = (1 + log(tf)) * idf * ZONE_WEIGHTS[field]
                term_score += value
                zone_hits[field] = max(zone_hits.get(field, 0), min(1.0, value / (1 + idf * ZONE_WEIGHTS[field])))
        if term_score:
            contributions[term] = term_score
    raw = _cosine(query_vector, _document_vector(index, doc_id))
    score = raw
    song_text = " ".join(str(item.song.get(f, "")) for f in FIELDS).casefold()
    phrase_boost = sum(0.06 for p in phrases if p and " ".join(p) in " ".join(index.tokenizer(song_text)))
    exact_boost = 0.06 if terms and " ".join(terms) in " ".join(index.tokenizer(item.song.get("title", ""))) else 0.0
    score = min(1.0, score + phrase_boost + exact_boost)
    return score, {"terms": contributions, "zones": zone_hits, "phraseBoost": phrase_boost, "exactBoost": exact_boost, "tfidf": raw}


def _document_vector(index: InvertedIndex, doc_id: str) -> dict[str, float]:
    vector: dict[str, float] = defaultdict(float)
    n_docs = max(1, len(index.docs))
    for field, counts in index.docs[doc_id].fields.items():
        for term, tf in counts.items():
            idf = log(1 + n_docs / max(1, index.document_frequency(term)))
            vector[term] += (1 + log(tf)) * idf * ZONE_WEIGHTS[field]
    return vector


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(term, 0.0) for term, value in left.items())
    norm_left = sqrt(sum(v * v for v in left.values()))
    norm_right = sqrt(sum(v * v for v in right.values()))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def rocchio_query(index: InvertedIndex, terms: list[str], feedback: dict[str, int], alpha=1.0, beta=0.75, gamma=0.15) -> dict[str, float]:
    """Q' = αQ + β centroid(relevant) − γ centroid(non-relevant)."""
    n_docs = max(1, len(index.docs))
    query_vector: dict[str, float] = defaultdict(float)
    for term in terms:
        weight = log(1 + n_docs / max(1, index.document_frequency(term)))
        for vector_term in index.postings:
            if vector_term == term or (len(term) >= 3 and vector_term.startswith(term)):
                query_vector[vector_term] += weight
    rel = [_document_vector(index, d) for d, label in feedback.items() if label == 1 and d in index.docs]
    nonrel = [_document_vector(index, d) for d, label in feedback.items() if label == -1 and d in index.docs]
    result = defaultdict(float)
    for term, value in query_vector.items():
        result[term] += alpha * value
    for docs, scale in ((rel, beta), (nonrel, -gamma)):
        if docs:
            for vector in docs:
                for term, value in vector.items():
                    result[term] += scale * value / len(docs)
    return {term: max(0.0, value) for term, value in result.items() if value > 0}


def rank_documents(index: InvertedIndex, query, mode="hybrid", feedback: dict[str, int] | None = None) -> list[dict]:
    terms = list(query.terms)
    vector_terms = terms + [term for phrase in query.phrases for term in phrase if term not in terms]
    if query.boolean_mode or mode == "boolean":
        candidates = index.boolean_candidates(terms, query.operators)
        if not query.boolean_mode and mode == "boolean" and terms:
            candidates = set.intersection(*(index.lookup(t) for t in terms)) if terms else set()
    elif mode == "vector":
        candidates = set(index.docs)
    else:
        candidates = set().union(*(index.lookup(t) for t in terms)) if terms else set(index.docs)
    if feedback:
        # Feedback can introduce terms outside the original query, so rerank the
        # complete current provider corpus rather than freezing the old candidate set.
        candidates = set(index.docs)
    # Include phrase candidates even when token overlap is absent due to provider normalization.
    if query.phrases:
        candidates |= set(index.docs)
    results = []
    refined_vector = rocchio_query(index, vector_terms, feedback or {}) if feedback else None
    for doc_id in candidates:
        base, explain = tfidf_score(index, doc_id, vector_terms, query.phrases if mode != "vector" else ())
        if mode == "vector":
            base = explain["tfidf"]
            explain["phraseBoost"] = explain["exactBoost"] = 0.0
        if mode == "boolean":
            base = 1.0 if doc_id in candidates else 0.0
        if refined_vector is not None:
            base = max(0.0, min(1.0, _cosine(refined_vector, _document_vector(index, doc_id))))
            explain["feedback"] = "Rocchio query vector"
        results.append({"song": index.docs[doc_id].song, "score": round(base, 5), "explanation": explain})
    return sorted(results, key=lambda r: (-r["score"], r["song"].get("title", "").casefold()))
