# Articles and Collections wireframe

Status: Historical (2026-08-13) — superseded by the shipped article surface. The
Phase 1 UX contract no longer awaits implementation: the surface shipped as
`/feed` (`frontend/app/feed/page.tsx` renders `ArticlesPage` from
`@/features/articles/articles-page`), and the Collections model this wireframe
deferred to is implemented (`backend/app/api/article_collections.py`, registered
in `backend/app/api/routes.py`; see [`mark-decision.md`](mark-decision.md)).

> Session 4A supersession: named Collections replace ArticleMark and the standalone
> Marked concept. This historical wireframe describes Marked interactions that were
> translated into collection save, remove, and collection-filter interactions.

## UX principles

- Content first. Article identity and summary dominate; technical ingestion fields recede.
- Dense desktop browsing, readable mobile cards.
- Same article component powers Articles and collection-filtered views.
- Filters are server-backed and URL-backed.
- Save-to-Collection state is visible and reversible without opening detail.
- Research/Generate appear only when active Story context is unambiguous; otherwise explain grouping requirement.
- Mixed Persian/English content uses isolated direction boundaries, not whole-page direction flips.
- Every mobile target is at least 44×44 px with at least 8 px between adjacent actions.

## Desktop: Articles

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Articles                                         [Add article] [Group pending]│
│ Browse collected RSS and Telegram content.                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ [Search title, summary, body…                            ] [Search]           │
│ Source [All⌄]  Date [Any⌄]  Score [Any⌄]  Type [All⌄]  Topic [All⌄]         │
│ Language [All⌄]  Coverage [All⌄]  Image [Any⌄]  Sort [Newest⌄] [Clear]      │
│ 3,142 results                                      Active filter chips…      │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────┐  Introducing Mobile Layout for Amazon Quick dashboards   [Save]│
│ │ reserved │  AWS Machine Learning Blog · Jul 17 · Published                 │
│ │  image   │  Teams that rely on dashboards for daily decisions…            │
│ │  space   │  [65] [Tutorial] [AI] [English] [Coverage incomplete]           │
│ └──────────┘  [Open article] [Research] [Generate]                           │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────┐  عنوان فارسی مقاله                                  [Saved to 2]│
│ │ fallback │  ISNA · Jul 20 · Published                                      │
│ │          │  خلاصه فارسی با مرز جهت مستقل…                                  │
│ └──────────┘  [42] [News] [Economy] [فارسی] [Coverage complete]              │
│               [Open article] [Open editorial studio]                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                           [Load more]                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

Desktop row behavior:

- Image column keeps fixed aspect-ratio box to prevent layout shift.
- Title is link; whole row is not clickable because row contains independent actions.
- Source/date line distinguishes `Published` from `Collected` fallback.
- Summary clamps to two or three lines; full body stays in detail.
- Score and primary classifications precede coverage. Raw readiness fields stay hidden unless blocking an action.
- Save button uses icon plus visible label/state; state never relies on color alone.
- More technical filters move into a compact `More filters` popover if first row cannot fit without wrapping badly.
- Cursor pagination uses `Load more` first; preserve scroll and focus after append.

## Mobile: Articles

```text
┌──────────────────────────────┐
│ Articles             [Filter]│
│ [Search…                  ]  │
│ 3,142 results  Newest [⌄]    │
│ [Source: ISNA ×] [Fa ×]      │
├──────────────────────────────┤
│ ┌──────────────────────────┐ │
│ │ reserved image / fallback│ │
│ └──────────────────────────┘ │
│ عنوان فارسی مقاله            │
│ ISNA · Jul 20 · Published    │
│ خلاصه فارسی…                 │
│ [42] [News] [Incomplete]     │
│ [Save]       [Open article]  │
├──────────────────────────────┤
│ [Load more]                  │
└──────────────────────────────┘
```

Mobile filter sheet:

```text
┌──────────────────────────────┐
│ Filters              [Close] │
│ Source                       │
│ [All sources              ⌄] │
│ Date range                   │
│ [From]               [To]    │
│ Score                        │
│ [Minimum]         [Maximum]  │
│ Content type / Topic / Domain│
│ Language / Coverage / Image  │
│                              │
│ [Clear all]   [Show results] │
└──────────────────────────────┘
```

Filter sheet requirements:

- Focus trapped; Escape/backdrop closes; trigger regains focus.
- Visible labels, inline validation, correct input modes for numeric score.
- Applying filters updates URL and resets pagination.
- Selected filters remain visible as removable chips after sheet closes.
- No horizontal filter-chip page overflow; chip row wraps or scrolls inside its own labeled region.

## Collections

Collection-filtered views reuse list layout and detail. Differences:

```text
Reading Queue
Articles saved to this collection.

[Search…] [Filters] [Sort: Newest article | Score | Relevance]
24 saved articles

...same article rows, with Remove from collection as reversible action...
```

- Empty state: `No articles in this collection yet.` plus link to Articles.
- Remove removes row after successful server confirmation; announce change through status region.
- Bulk selection may appear in Phase 5 only after atomic or explicitly per-item API semantics are approved.
- Research and Generate remain Story-scoped, same as Articles.

## Recommended article detail: dedicated route

Recommend `/articles/{contentItemId}` rather than drawer as canonical detail:

- Deep-linkable from Articles, Collections, Content, Library, and Story evidence.
- Browser Back behavior is predictable.
- Enough space for full body, evidence, media, research, and generated work.
- Better mobile and keyboard behavior than a deeply nested drawer.
- Desktop may later add route-intercepted overlay only if URL, focus, and Back behavior remain exact.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ← Back to results                                      [Save] [Original ↗]  │
│ Article title                                                               │
│ Source · publication date · language · score                                │
│ [Type] [Topic] [Domain] [Coverage]                                           │
├───────────────────────────────────────┬──────────────────────────────────────┤
│ Primary image / safe fallback         │ Editorial context                    │
│                                       │ Story: title / state / completeness   │
│ Summary                               │ [Research] [Generate] [Open studio]   │
│ Full readable body                    │                                      │
│                                       │ Related media/evidence                │
│                                       │ Research status                       │
├───────────────────────────────────────┴──────────────────────────────────────┤
│ ▸ Advanced: readiness, scoring, classification, IDs, hashes, media status   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Small screens stack editorial context after summary and before full body actions. Sticky action bars must not cover content or existing mobile newsroom navigation.

## Action states

| Context | Research/Generate behavior |
| --- | --- |
| One active Story | Use that Story ID; show completeness and durable job outcome. |
| No active Story | Disable action with `Group this article before research or generation`; offer durable grouping action when supported. |
| Several active Stories | Require explicit Story selection; never choose first row silently. |
| Story rejected/superseded | Explain state and link to current active Story when known. |
| Provider unavailable | Show server reason; keep configuration link contextual. |
| Existing draft/content pack | Prefer `Open editorial studio` over generating an accidental duplicate. |

## Loading, empty, error, and image states

- Initial loading: skeletons matching image/title/metadata geometry; no spinner-only blank page.
- Pagination loading: keep existing rows and show progress near `Load more`.
- Empty collection: explain no content collected and link to Sources/ingestion.
- No filter results: preserve filters, show `No articles match`, offer Clear filters.
- Error: concise message plus Retry; do not discard URL filters.
- Missing image: neutral reserved fallback, not broken-image icon.
- Failed remote image: replace with same fallback without shifting row.
- Collection mutation pending: disable repeated action, preserve label, roll back on failure.

## Accessibility and interaction gate

- One page `h1`; list uses semantic articles or rows with unique names.
- Keyboard order follows visible order: title, Save, detail, contextual actions.
- Visible focus ring on every interactive control.
- Save control exposes collection membership and an accessible name; state is not color-only.
- Dynamic result count, pagination, and mutation outcomes use polite status announcements.
- Images use persisted alt text when meaningful; decorative/fallback image uses empty alt.
- Metadata contrast meets WCAG AA; badges do not encode state by color alone.
- Desktop and mobile have no page-level horizontal overflow at 375, 768, 1024, and 1440 px.
- Respect reduced motion; no decorative list animation.

## Visual review questions

1. Is row density sufficient for fast scanning without becoming Content diagnostics again?
2. Should desktop use compact rows as shown, or larger cards?
3. Is dedicated detail route preferred over route-backed drawer?
4. Which three filters deserve permanent first-row placement?
5. Should coverage badge describe Story completeness, Article readiness, or both with distinct labels?
6. Should Add article and Group pending stay in Articles header or remain in Inbox during transition?
