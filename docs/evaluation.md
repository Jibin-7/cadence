# Evaluation

CadenceIR collects judgments for a particular search result set, not global judgments. A relevance label is attached to `(search_id, song_id)` and can be withdrawn. Judgments persist across app restarts in SQLite.

For each search with at least one judgment:

* **Precision@K** = relevant judged items among the first K returned items / number of judged items in that top-K slice.
* **Recall@K** = relevant judged items among the first K / all items marked relevant for that judged search.
* **F1** = harmonic mean of Precision@K and Recall@K.
* **MRR** = reciprocal rank of the first result labeled relevant; zero if no judged relevant item appears.

The displayed metrics are macro-averaged across searches that have at least one label. Unlabeled tracks remain unknown, not negative. Consequently Recall@K is recall over collected relevance judgments and can change as a user labels more results. CadenceIR waits for at least five labels spread across two searches before displaying values, avoiding a misleading aggregate from one or two clicks.

## Known evaluation scope

There is no independent gold-standard test collection. The UI metrics describe the feedback gathered during use and are useful for a viva demonstration, but they are not a benchmark claim. Precision and recall can be misleading with few judgments; label several results across multiple queries before interpreting the aggregate.
