# CSDC7023 syllabus mapping

| Syllabus area | Project evidence | Demonstration |
|---|---|---|
| Introduction to IR | Live-provider candidate set followed by a local retrieval and ranking stage | Compare provider result records with the final ranked list |
| Retrieval process | Query processing → candidates → index → ranking → result explanation | Follow the pipeline on About IR |
| Query processing | Unicode normalization, tokenization, punctuation handling, stop-word handling, quoted phrases | Search variants with capitalization/punctuation and use quoted text |
| Query structures | Free text and explicit `AND`, `OR`, `NOT` | Advanced Search |
| Pattern matching | Prefix postings for incomplete terms of three or more characters | Try a truncated title token |
| Inverted files | Live term postings and per-zone postings | See index document and term counts |
| Boolean retrieval | Posting intersections, unions and differences | Use `Taylor AND Love`, `artist OR artist`, `pop NOT remix` |
| Term weighting | Log TF and smoothed IDF | Expand the result explanation |
| Vector-space model | Query/document vectors and cosine similarity | Compare Vector mode ranking |
| Zone / field weighting | Configurable title, artist, album and genre weights | Use field selection and explanation zone signals |
| Phrase / exact matching | Quote parsing, phrase and exact-title boosts | Search a phrase with and without quotes |
| Relevance feedback | Rocchio query update from persisted positive/negative judgments | Rate results and observe reordering |
| Evaluation | Precision@K, Recall@K, F1 and MRR from actual labels | Label across two searches and open Evaluation |
| Multimedia IR | Track and album metadata, album artwork, provider-issued audio previews | Open a track, artist, album, or play an available preview |
| Distributed/provider architecture | Metadata/playback provider contracts and outbound iTunes API calls | Inspect provider limits and capability boundary on About IR |

Lyrics search is not claimed as implemented because the selected metadata API does not expose lyric text. Full-track playback is not claimed; the player streams a returned preview only when one is provided.
