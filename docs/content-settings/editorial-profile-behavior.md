# Editorial profile behavior

Editorial profiles are reusable generation policy. They contain:

- Output language and editorial tone
- Editorial and attribution rules
- Default hashtags
- Per-platform preferences

## Default selection

At most one profile can be marked default. PostgreSQL enforces this with the
partial unique index `uq_brand_profiles_one_default`.

Content-pack requests may omit `brand_profile_id`. The API then resolves the
current default and writes that profile ID into the durable job payload. If no
default exists, the request fails with `editorial_profile_unavailable`.

Automation routes always store an explicit profile ID. Changing the default
does not rewrite existing routes.

## Timing and immutability

Default selection happens when a content-pack job is requested. The selected
profile ID is fixed in the queued job payload.

Profile fields are read by the worker when the queued job executes. Editing a
profile can therefore affect a queued job that has not started, even though its
profile ID is already fixed.

Generated revisions are immutable snapshots. Profile edits and default changes
never rewrite existing revisions. Regeneration creates a new revision using the
profile selected by that workflow.

## Client state

Profile writes invalidate Content Settings, Telegram Automation options, and
editorial profile option caches. Provider writes also invalidate editorial
provider options. Prompt activation already invalidates editorial prompt
options.
