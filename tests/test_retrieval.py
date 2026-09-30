from backend.retrieval.index import InvertedIndex, rank_documents, rocchio_query
from backend.retrieval.text import process_query, tokenize


def corpus():
    return [
        {"id": "1", "title": "amber night", "artist": "quiet river", "album": "north", "genre": "folk"},
        {"id": "2", "title": "amber road", "artist": "loud valley", "album": "south", "genre": "rock"},
        {"id": "3", "title": "silver line", "artist": "quiet river", "album": "east", "genre": "rock"},
    ]


def test_normalization_and_tokenization():
    assert tokenize("Beyoncé — LOVE's echo!") == ["beyonce", "loves", "echo"]
    parsed = process_query('"amber night" AND folk')
    assert parsed.terms == ("folk",)
    assert parsed.phrases == (("amber", "night"),)
    assert parsed.operators == ("AND",)


def test_inverted_index_and_prefix_lookup():
    index = InvertedIndex(corpus(), tokenize)
    assert index.postings["quiet"] == {"1", "3"}
    assert index.lookup("amb") == {"1", "2"}
    assert index.field_postings["genre"]["rock"] == {"2", "3"}


def test_boolean_intersection_union_and_difference():
    index = InvertedIndex(corpus(), tokenize)
    assert index.boolean_candidates(["amber", "rock"], ("AND",)) == {"2"}
    assert index.boolean_candidates(["quiet", "loud"], ("OR",)) == {"1", "2", "3"}
    assert index.boolean_candidates(["amber", "rock"], ("NOT",)) == {"1"}


def test_tfidf_explanations_and_rocchio_change_order():
    index = InvertedIndex(corpus(), tokenize)
    query = process_query("amber")
    base = rank_documents(index, query, "vector")
    assert base[0]["song"]["id"] in {"1", "2"}
    assert all(0 <= row["score"] <= 1 for row in base)
    assert all("tfidf" in row["explanation"] and "zones" in row["explanation"] for row in base)
    q2 = rocchio_query(index, ["amber"], {"3": 1})
    assert q2["quiet"] > 0
    refined = rank_documents(index, query, "vector", {"3": 1})
    assert refined[0]["song"]["id"] == "3"


def test_phrase_boost_is_computed():
    index = InvertedIndex(corpus(), tokenize)
    result = rank_documents(index, process_query('"amber night"'), "hybrid")
    by_id = {r["song"]["id"]: r for r in result}
    assert by_id["1"]["explanation"]["phraseBoost"] > 0

