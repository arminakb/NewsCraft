# NewsCraft

NewsCraft turns collected source material into operator-reviewed, source-grounded publishing workflows.

## Feed classification

**Raw classification**:
The content type, topic, and language values stored by ingestion and classification. These values are immutable historical evidence and may contain generic or overlapping labels.
_Avoid_: Display metadata, canonical classification

**Canonical article classification**:
The deterministic, operator-facing content type, topic, and language derived from a raw classification for the Feed and Articles API.
_Avoid_: Raw classification, inferred category

**Content type**:
The kind or format of an article, such as `news`, `research`, or `tutorial`.
_Avoid_: Topic, category

**Topic**:
The subject an article covers, such as `AI`, `Tech`, or `Economy`.
_Avoid_: Content type, format
