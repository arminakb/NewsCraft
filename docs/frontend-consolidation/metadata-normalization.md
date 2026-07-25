# Feed metadata normalization

Session 4B.2 defines one deterministic boundary between persisted article classification and the operator-facing Feed. It does not rewrite historical rows or alter raw Content, Story, or Library responses.

## Observed raw values

The production-shaped local database was inspected with a read-only transaction on 2026-07-22. It contained 3,142 content items.

### Content type

| Raw value | Count |
| --- | ---: |
| `article` | 1,672 |
| `research` | 518 |
| `tutorial` | 279 |
| `tool_update` | 217 |
| `news` | 168 |
| `vendor_update` | 146 |
| `promo` | 126 |
| `longform` | 11 |
| `video` | 5 |

The classifier also supports `low_signal`, but no current row uses it. There were no null, blank, whitespace-padded, or inconsistent-case content types in the inspected data.

### Topic

| Raw value | Count |
| --- | ---: |
| `AI` | 2,177 |
| `Economy` | 498 |
| `Tech` | 222 |
| `News` | 221 |
| `General` | 24 |

There were no null, blank, whitespace-padded, or inconsistent-case topics in the inspected data. `General` is the classifier fallback rather than a useful operator-facing subject.

### Language

| Raw value | Count |
| --- | ---: |
| `en` | 2,828 |
| `fa` | 314 |

There were no null, blank, whitespace-padded, or inconsistent-case language values in the inspected data.

### Common content type and topic combinations

| Raw content type + topic | Count |
| --- | ---: |
| `article` + `AI` | 1,125 |
| `research` + `AI` | 472 |
| `article` + `Economy` | 274 |
| `tool_update` + `AI` | 195 |
| `tutorial` + `AI` | 164 |
| `article` + `News` | 146 |
| `vendor_update` + `AI` | 141 |
| `article` + `Tech` | 110 |
| `news` + `Economy` | 84 |
| `tutorial` + `Economy` | 81 |
| `news` + `News` | 62 |

The two material overlaps are 146 `article + News` rows and 62 `news + News` rows. Across all 33 combinations, 24 rows use the generic `General` topic.

## Canonical mapping

| Dimension | Raw input | Canonical output |
| --- | --- | --- |
| Content type | Known classifier values in any case | Lowercase identifier, for example `Research` → `research` |
| Topic | `ai`, `tech`, `economy`, or `news` in any case | `AI`, `Tech`, `Economy`, or `News` |
| Topic | `General` in any case | `null` in primary metadata |
| Language | Any nonblank code | Lowercase code, for example `FA` → `fa` |
| Any dimension | Unknown nonblank value | Trimmed, internal whitespace collapsed, and lowercased; no new category is inferred |
| Any dimension | Null or blank | `null` |
| Pair | `article` + `News` | Content type `news`; topic `null` |
| Pair | Any content type identical to its topic ignoring case | Keep the content type; topic `null` |

With current data, this yields 1,526 canonical `article` rows and 314 canonical `news` rows. The canonical `News` topic contains 13 rows after the 208 content-type overlaps are removed. `General` does not produce a facet.

## Consistency boundary

`app.content.article_metadata` owns both scalar normalization and equivalent PostgreSQL expressions. The Articles list and detail serialize scalar canonical values. Facets, counts, and filters use the SQL expressions, so selecting a facet reaches every row included in that facet count. Filter parameters are normalized before the cursor fingerprint is built, making case variants such as `NEWS` and `news` cursor-equivalent.

OR semantics within one filter group and AND semantics across groups are unchanged. A direct `topic=General` request is rejected because `General` is intentionally absent from the canonical topic vocabulary; it cannot silently become an unfiltered request.

## Values hidden from primary Feed cards

- The generic content type `article` is hidden when a specific topic is present; it remains visible when it is the only classification.
- The fallback topic `General` is canonicalized to null.
- A topic identical to the content type is canonicalized to null.
- The card metadata helper retains its three-badge maximum and case-insensitive duplicate protection.

## Raw-value preservation

Persisted rows are not modified. `GET /articles` and `GET /articles/facets` expose only canonical values. `GET /articles/{id}` exposes canonical primary fields and the original values under:

```json
{
  "advanced": {
    "raw_classification": {
      "content_type": " Article ",
      "topic": " news ",
      "language": " EN "
    }
  }
}
```

Raw classification is not added to Feed cards or list responses.

## Deterministic limitations

Normalization uses only persisted classification fields. It does not inspect a title or body, make AI or network calls, or attempt to decide whether an unknown label is semantically equivalent to a supported one. Unknown values therefore remain distinct after whitespace and case normalization. A future supported taxonomy change must be added explicitly to both the canonical mapping and its tests.

The approximately seven-second cold `/articles/facets` request is intentionally not optimized in Session 4B.2. Facet performance is deferred to the final Performance phase.
