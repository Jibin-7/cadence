# Information Retrieval in CadenceIR

## Problem statement

Traditional catalog search often assumes that a listener knows the exact title or spelling. In real discovery, people may remember only an artist, album, genre, era, part of a title, or a phrase they associate with a track. A metadata provider search can find candidate records, but using its order directly would make this project an API wrapper rather than an Information Retrieval system.

CadenceIR adds a transparent local retrieval stage over the live provider response. It normalizes terms, builds postings, applies Boolean filters or weighted vector ranking, explains the result, and uses relevance labels to reformulate a query. The candidate set and all displayed metadata still come from the current provider response.

## Retrieval path

```text
User expression
   ↓
Query normalization and parsing
   ↓
Live Apple iTunes candidate response
   ↓
Inverted index built from those records
   ↓
Boolean candidate selection / TF-IDF vector scoring
   ↓
Title, artist, album and genre zone weights
   ↓
Optional Rocchio feedback
   ↓
Ranked results + explanation + saved judgments
```

## Concepts demonstrated

### 1. Query processing and tokenization

**Definition.** Query processing turns a user's text into normalized searchable terms and query structure.

**Implementation.** `backend/retrieval/text.py` compatibility-normalizes Unicode, removes diacritics, case-folds, tokenizes punctuation-aware text, extracts quoted phrases, and recognizes `AND`, `OR`, and `NOT`. Common function words are removed from a query only when at least one non-stopword remains, so a query consisting only of a short proper name is not erased.

**Where to demonstrate.** Try mixed capitalization, punctuation, a quoted title phrase, or an explicit Boolean expression in Advanced Search.

**Why it helps.** Small spelling and punctuation differences do not create separate terms, while phrases and operators retain meaning beyond a flat keyword list.

### 2. Inverted index and partial matching

**Definition.** An inverted file maps each term to the documents containing it, which avoids scanning every field for every query term.

**Implementation.** `backend/retrieval/index.py` builds `term → provider track IDs` and per-field postings from the live API response. It stores term counts per title, artist, album, and genre. Prefix lookup is available for tokens of at least three characters. Identical provider result corpora reuse a bounded in-memory index cache; new catalog responses get newly built indexes.

**Where to demonstrate.** Search a partial title token and inspect the query's indexed-document and index-term counts.

**Why it helps.** Posting lookup narrows candidate sets quickly and gives Boolean retrieval real document sets to combine. Prefix lookup supports incomplete words without inventing catalog entries.

### 3. Boolean retrieval

**Definition.** Boolean retrieval treats a term as a posting set and combines sets with logical operations.

**Implementation.** `InvertedIndex.boolean_candidates` intersects sets for `AND`, unions them for `OR`, and subtracts later postings for `NOT`. A Boolean search with no explicit operators uses conjunction. Explicit operators select Boolean candidate retrieval even when a different ranking option was selected.

**Where to demonstrate.** Enter expressions such as `Taylor AND Love`, `artist OR artist`, or `pop NOT remix` in Advanced Search.

**Why it helps.** Users can express inclusion and exclusion constraints directly; the engine operates on the live response's actual posting lists.

### 4. TF-IDF and the vector-space model

**Definition.** TF-IDF gives a term more weight when it is frequent in one document but uncommon across the current corpus. The vector-space model compares query and document term vectors with cosine similarity.

**Implementation.** `tfidf_score`, `_document_vector`, and `_cosine` in `backend/retrieval/index.py` compute logarithmic term frequency, smoothed inverse document frequency, weighted document vectors, and cosine normalization. Vector mode scores every document in the current provider response. Hybrid mode first narrows candidates using postings, then ranks them with the vector score and additional exact/phrase signals.

**Where to demonstrate.** Compare Vector and Hybrid results and expand “Why this result?” to see the calculated cosine value and matching term contributions.

**Why it helps.** Rare matches contribute more than common terms, and cosine normalization compares documents fairly when their metadata has different lengths.

### 5. Field / zone weighting

**Definition.** Zone weighting gives distinct importance to searchable fields such as title, artist, album, or genre.

**Implementation.** `ZONE_WEIGHTS` in `backend/retrieval/index.py` sets title=3.0, artist=2.4, album=1.5, and genre=1.0. These weights reflect how directly those fields identify a known recording; title and performer are stronger evidence than broad genre metadata. Weighted terms contribute to document vectors and the result explanation lists field matches.

**Where to demonstrate.** Open a result explanation to see which zones matched; use the field selector to restrict an Advanced Search.

**Why it helps.** A title or artist match can outrank a result that shares only a broad genre term, while genre remains searchable.

### 6. Exact and phrase signals

**Definition.** Exact matching and phrase matching preserve ordering and whole-title signals beyond independent token matches.

**Implementation.** Quoted phrases are extracted during query processing. Ranking checks phrase presence in the normalized searchable metadata and applies a small, visible phrase boost; a complete query phrase in the normalized title receives a separate exact-title boost. Vector mode reports cosine without those hybrid boosts.

**Where to demonstrate.** Search a title normally and with quotes, then compare the expanded result explanations.

**Why it helps.** A phrase match is stronger evidence than the same words scattered across independent fields.

### 7. Relevance feedback (Rocchio)

**Definition.** Rocchio updates a query vector toward relevant document centroids and away from non-relevant document centroids: `Q′ = αQ + β·Rel − γ·NonRel`.

**Implementation.** `rocchio_query` in `backend/retrieval/index.py` uses α=1.0, β=0.75 and γ=0.15. Feedback labels are stored per search in SQLite. After each label, CadenceIR rebuilds the feedback vector from that search's indexed provider corpus, scores the full corpus against it, and returns the updated order. The latest ranking is stored for evaluation.

**Where to demonstrate.** Mark a result relevant and another not relevant. The result order changes and the interface reports that feedback refined the ranking.

**Why it helps.** The search learns from this user's explicit judgments without claiming generic or fabricated recommendations.

### 8. Evaluation

**Definition.** Precision measures the quality of returned items, recall measures how many known relevant items appear, F1 balances the two, and MRR rewards an early first relevant result.

**Implementation.** `backend/database.py` derives Precision@K, Recall@K, F1 and MRR from persisted labels and the current saved result order. Precision@K uses only judged items in the top K; unknown items remain unknown. Metrics require five labels across at least two searches; otherwise the app reports how much feedback is still needed.

**Where to demonstrate.** Make judgments across two searches, then open Evaluation.

**Why it helps.** The student can discuss measured retrieval quality while avoiding misleading metrics based on a single click or assumed labels.

## Scope of the collection

Apple iTunes Search supplies current metadata but not lyrics. Each query indexes a bounded response (up to 100 records through the API, normally 50 in the UI), not the entire music world. Lyrics fragments cannot be expected to match when their text does not appear in provider metadata. This boundary is shown in the app and keeps all search results genuine.
