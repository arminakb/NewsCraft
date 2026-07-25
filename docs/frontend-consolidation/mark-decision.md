# Collections persistence decision

Status: implemented in Session 4A
Date: 2026-07-21

## Supersession

Named Collections supersede the earlier `ArticleMark`/Marked proposal. Do not add
`article_marks`, mark/unmark endpoints, or a separate Marked article list.

Collections remain workspace-global while NewsCraft has no user/account model.
One `ContentItem` may belong to any number of collections.

## Persistence

```text
article_collections
  id              UUID PRIMARY KEY
  name            TEXT NOT NULL
  normalized_name TEXT NOT NULL UNIQUE
  created_at      timestamptz NOT NULL
  updated_at      timestamptz NOT NULL

article_collection_items
  collection_id  UUID REFERENCES article_collections(id) ON DELETE CASCADE
  content_item_id UUID REFERENCES content_items(id) ON DELETE RESTRICT
  saved_at        timestamptz NOT NULL
  PRIMARY KEY (collection_id, content_item_id)
```

Names are trimmed, contain 1–60 characters, and are unique after case-insensitive
normalization. Collection deletion cascades only to membership rows. Restrictive
article membership prevents a saved `ContentItem` from being silently deleted.

## API

```http
GET    /article-collections
POST   /article-collections
PATCH  /article-collections/{collection_id}
DELETE /article-collections/{collection_id}
PUT    /article-collections/{collection_id}/articles/{content_item_id}
DELETE /article-collections/{collection_id}/articles/{content_item_id}
GET    /articles?collection_id={collection_id}
```

Membership PUT and DELETE are idempotent. Article summary and detail responses
expose `saved` plus `saved_collection_ids`. No separate collection-article list
endpoint exists.

## Collections versus Shortlist

Collections organize collected `ContentItem` records. Story `shortlisted` remains
an editorial workflow state. Saving or removing membership never changes
ContentItem approval, Story status, research/generation state, or publishing state.

## Retention

Saved ContentItems and referenced primary media stay protected while any membership
exists. Removing membership only makes data eligible for later policy evaluation;
it never deletes article content immediately.
