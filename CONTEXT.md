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

## Automation workflows

**Automation**:
A workflow definition with a draft version and, when activated, an active version.

**AutomationVersion**:
An immutable saved automation definition. Editing or restoring creates a new version.

**AutomationRun**:
One execution of an exact AutomationVersion and its immutable execution snapshots.

**AutomationNodeRun**:
One persisted node attempt within an AutomationRun, linked to the durable jobs and artifacts that implement it.

**Template**:
A reusable starting definition for creating an Automation; it is not itself an executable AutomationVersion.

**Node type**:
An allowlisted, server-owned workflow capability whose ports, safe configuration, validation, and runtime mapping are defined by the server registry.
