# Multi-platform manual publishing operations

Release 4 can generate one evidence-bound content package with current revisions for
Telegram, Instagram, X, and blog. Copy, export, approval, scheduling, and completion
records remain bound to immutable revision IDs and content hashes; none of those records is
proof of live platform state by itself.

> **Publishing boundary:** Instagram, X, and blog are manual-only. NewsCraft does not log in
> to, upload to, or automatically post on those platforms. Their previews are approximations,
> not pixel parity or live platform state. Telegram uses the separate reviewed Telegram
> scheduling/publishing boundary described below.

## Before generating

1. In **Inbox**, open the intended story and inspect its captured evidence. Complete the
   research flow when the story is incomplete, then use the exact successful research result.
2. In **Content Settings**, confirm that one active immutable prompt version exists for the canonical
   story and for each platform pack. The backend resolves those active versions; operators do
   not send prompt text or version choices in a Release 4 request.
3. Select the intended brand profile and an enabled generation profile. The fake profile is the
   safe credential-free choice for local acceptance. Live OpenRouter or Codex execution remains
   an explicit operator opt-in as documented in
   [Research and generation operations](research-and-generation.md).

## Generate all four platforms

The **Generate Telegram pack** Inbox action is the Telegram-only compatibility path. To create
one complete four-platform package, submit one request to the backend with all four platform
names:

```bash
STORY_ID="<story UUID>"
BRAND_PROFILE_ID="<brand profile UUID>"
GENERATION_PROFILE_ID="<generation profile UUID>"
RESEARCH_RUN_ID="<successful research run UUID>"

curl -X POST "http://localhost:8000/stories/${STORY_ID}/content-packs" \
  -H 'content-type: application/json' \
  --data-binary @- <<JSON
{
  "brand_profile_id": "${BRAND_PROFILE_ID}",
  "platforms": ["telegram", "instagram", "x", "blog"],
  "generation_provider_profile_id": "${GENERATION_PROFILE_ID}",
  "research_mode": "off",
  "research_run_id": "${RESEARCH_RUN_ID}"
}
JSON
```

Use UUIDs from the selected story, brand, generation profile, and successful research run. If
the request is not bound to a research run, omit `research_run_id`; do not send it as `null` when
copying the command by hand. The API returns a durable job ID. Follow it in the job timeline or
inspect `GET /content-pack-requests`. When the request is ready, open **Drafts** and then
**Open editorial studio** for the returned package.

Generation creates one platform-specific revision per requested platform. A provider or schema
failure remains visible as `failed` or `needs_review`; it does not silently approve or publish
content.

## Review, edit, and approve exact revisions

Repeat this flow for the **Telegram**, **Instagram**, **X**, and **Blog** tabs in the
multi-platform editorial studio:

1. Read the platform preview, validation results, and exact content/evidence map. Open every
   citation that has a source URL and compare the factual copy with the captured excerpt.
   Operator-provided evidence may intentionally have no external URL.
2. Inspect the media plan in order. Verify each assigned asset, role, alt text, and any manual
   brief or replacement warning. Resolve missing or unsuitable media outside NewsCraft before
   publication.
3. Treat the preview only as a readable projection of the stored payload. Recheck current
   character limits, cropping, link behavior, accessibility fields, and formatting on the real
   destination before posting.
4. If copy or media order changes, enter an edit note and choose **Save new revision**. The save
   creates an immutable pending-review child; it never overwrites the loaded revision. Re-open
   the newest revision after a stale-revision conflict.
5. Recheck the displayed revision ID and content hash, then choose **Approve revision**. Approval
   applies only to that exact revision. A later edit creates another pending-review revision and
   must be reviewed and approved again.

## Copy or export

Use **Copy and export** only after reviewing the exact revision relationship:

- Copy actions use the revision currently open in the selected platform tab. Telegram copies
  the formatted message; Instagram copies caption and hashtags; X can copy the full ordered
  thread or one post; blog can copy Markdown or the sanitized HTML rendering. If browser
  clipboard access fails, NewsCraft selects the exact text in a manual-copy field.
- A package export is different: it always binds to the one current revision of every package
  variant. Every current revision must exist and be approved. Choose JSON, Markdown, HTML,
  and/or ZIP, optionally include media, choose **Export package**, wait for **Export ready**, and
  download the artifacts through the displayed API links.
- The export manifest records the exact content package and revision set with checksums. An
  export is a deterministic handoff artifact, not a publication action.

## Plan and record Instagram, X, or blog publication

1. From an approved Instagram, X, or blog revision, choose **Preview, schedule, or publish
   approved revision**.
2. In **Manual publication handoff**, enter a future **Scheduled time (UTC)**, select the display
   timezone, and choose **Create manual publication plan**. The plan stays bound to that exact
   approved revision and appears on **Calendar**.
3. At the scheduled time, open the real destination yourself. Use the exact copy/export output
   and media plan, then perform the post or CMS operation outside NewsCraft.
4. Return to the plan and complete every persisted, platform-specific checklist item. These
   checks cover copy/citations, media and alt text, and destination-specific requirements such
   as thread order or SEO fields.
5. Optionally enter the public HTTP(S) publication URL and an operator note, then choose **Mark
   as published**. NewsCraft records the completion time, URL, and note. It does not contact the
   destination to verify that operator declaration.

Do not mark a plan published before the external operation succeeds. A manual plan is scheduling
and audit evidence; it is not an automatic post queue.

## Telegram boundary

Telegram does not use the Instagram/X/blog manual-plan checklist. An approved exact Telegram
revision opens the existing Telegram review workspace, where **Publish exact revision** remains
blocked by global pause or dry-run, route/destination health, revision dry-run, unresolved
research, and manual-media requirements. A real send requires an enabled healthy destination
and the publishing worker's explicitly configured Telegram credential.

The backend can also schedule an approved Telegram revision through
`POST /telegram/drafts/{revision_id}/schedule` using the exact `content_hash`, a configured
`destination_id`, and a strictly future UTC `scheduled_for` value. Both immediate and scheduled
Telegram work enters the durable Telegram publishing boundary; scheduled jobs appear beside
manual plans on **Calendar**. Neither the fake-provider flow nor the default dry-run state sends
a Telegram message.

## Offline, no-credentials acceptance

The deterministic backend and browser acceptance suites run with fake providers and without
Instagram, X, CMS, Telegram, OpenRouter, or Codex credentials. They can prove that:

- all four typed revisions are generated and kept separate;
- edits create immutable children and approvals bind to exact hashes;
- copy/export requests and manifests bind to the intended revision set;
- manual plans persist their checklist and optional completion evidence; and
- desktop/mobile previews, Calendar, and Library expose the stored state.

Those suites cannot prove live-platform rendering, account access, permissions, current external
limits, rate-limit behavior, Telegram delivery, or that an operator-provided publication URL is
the intended post. Final destination review and the actual Instagram/X/blog publication remain
manual. Do not add live credentials to acceptance-test environments.
