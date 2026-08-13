# Content Settings audit

> **Superseded 2026-08-13 — historical record only.** `/settings/content`
> still resolves, but it no longer renders the page audited below:
> [`frontend/app/settings/content/page.tsx`](../../frontend/app/settings/content/page.tsx)
> now renders `LegacySettingsRoute`, which `router.replace()`s into the
> unified `/settings`
> ([`frontend/features/settings/settings-route.tsx`](../../frontend/features/settings/settings-route.tsx)).
> There is no "Advanced > System" navigation any more — Settings is a
> single sidebar entry
> ([`newsroom-sidebar.tsx`](../../frontend/components/newsroom/newsroom-sidebar.tsx)).
> The 21-control inventory and the workflow walkthrough therefore describe
> a page that is no longer rendered; individual findings may still apply to
> the corresponding sections of unified Settings but must be re-verified
> there before being acted on.

Audit date: 2026-07-22
Scope: Session 6A, `/settings/content` only
Code changes: none

## 1. Plain-language purpose

Content Settings is an operator-facing configuration hub for four different runtime concerns:

1. Editorial brand profiles used to shape language, tone, attribution, hashtags, and platform preferences.
2. Immutable prompt templates and active prompt versions for canonical story generation, content-pack generation, and Telegram automation rewrites.
3. AI provider profiles that bind a provider type and model to a write-only credential reference or local Codex runtime.
4. Telegram publishing destinations, including target, bot-token reference, health, and permission to participate in automatic publishing.

The page does not store credential values. It stores environment/file reference names, while capability-scoped workers resolve actual values. It is not one coherent “content” concern: it mixes editorial defaults, prompt governance, model infrastructure, worker capability state, and publishing integration setup.

Route: `/settings/content` (`frontend/app/settings/content/page.tsx`). It appears in the Advanced > System navigation as **Content Settings**.

## 2. Current user workflow

1. Opening the route starts four parallel reads: brands, prompt templates, provider profiles, and Telegram destinations. Prompt-version history loads separately for each available purpose.
2. Any one of the four primary read failures replaces the entire page with one error and **Retry settings**. Individual prompt-history failures stay inside their cards.
3. Operators create a brand with a name only. The client silently supplies Persian, neutral tone, empty rules, empty hashtags, empty platform preferences, and `is_default=false`.
4. Existing brands expose only name and tone. Every brand has its own **Save brand** action.
5. Canonical-story and Telegram-pack prompt cards expose immutable history, raw system/user template entry, a confirmation checkbox, and activation. Their templates must already exist; these cards cannot initialize missing purposes.
6. Telegram automation rewrite has a separate, more elaborate prompt editor. It can initialize its template, validates seven required placeholders in the browser, creates immutable versions, shows raw templates, and activates a confirmed version.
7. AI provider creation always creates an enabled OpenRouter profile. Operators enter a profile name, model, and credential-reference name. Existing profiles expose model replacement and, except for Codex, credential-reference replacement.
8. Telegram destination creation stores a name, target, bot-token reference, and auto-publish permission. Creation returns `202`, enqueues a destination health-check job, and immediately refreshes destination/options queries.
9. Saves are independent. There is no page-level save, reset, undo, dirty indicator, or navigation guard. Unsaved local values disappear on route change or reload.

### Live read-only snapshot

Verified against the running local stack on 2026-07-22. No values were changed.

- Route returned HTTP 200.
- 1 brand, 6 prompt purposes, 4 provider profiles, and 2 Telegram destinations existed.
- Canonical story, Telegram pack, and Telegram rewrite each had one active version.
- Deterministic Fake was the only research-capable provider. One custom OpenRouter profile supported generation but not research because pricing and research budgets were absent. Seeded Codex and OpenRouter profiles were disabled.
- Both Telegram destinations were unhealthy and lacked a current publishing credential capability. Two records referred to the same apparent channel using URL and `@handle` formats; their auto-publish permissions conflicted.
- Safe GET responses omitted every provider and destination `secret_ref`.

## 3. Complete field and control inventory

There are 18 distinct value-entry field types. Three additional checkboxes are transient prompt-activation confirmations, giving 21 interactive value controls before dynamic action buttons and history/status controls are counted. Actual rendered count grows with persisted brands, providers, destinations, and prompt versions.

### Brands

| Display label | Internal field | Type, validation, default | Storage | Read/write and save behavior | Runtime effect and invalid/empty behavior | Status | Classification |
|---|---|---|---|---|---|---|---|
| New brand name | `brandName` -> `name` | Required text. Browser only checks non-empty; backend length 1-120. Default empty. | `brand_profiles.name` | Read `GET /brand-profiles`; create `POST /brand-profiles`. Submit creates immediately, clears name, refetches brands and automation options, and shows notice. | Duplicate name with different data is 409. Empty is blocked by form/button. New profile also stores fixed hidden values: `output_language=fa`, `tone=neutral`, empty rules/hashtags/preferences, `is_default=false`. | Functional, but creation hides consequential defaults. | Keep in primary Content Settings |
| Name | local `name` -> `name` | Text. No browser `required`, min/max, trim, or inline error. Backend 1-120 and non-null. Initial value is stored name. | `brand_profiles.name` | `PATCH /brand-profiles/{id}` with name and tone. Per-row save; refetches brands/options and shows notice. | Empty/too long returns 422. Duplicate rename is enforced by DB unique constraint but is not translated to a friendly API conflict. Used as operator label and option label, not prompt content. | Connected; weak validation/error text. | Keep in primary Content Settings |
| Tone | local `tone` -> `tone` | Free text. No browser validation or vocabulary. Backend 1-120 and non-null. Initial value is stored tone. | `brand_profiles.tone` | Same brand PATCH/save. | Serialized into `brand_profile_json` for every content-pack platform. Empty/too long returns 422. Existing generated revisions do not change. | Functional; semantics undefined. | Rename or clarify |

Hidden brand fields matter despite having no controls. `output_language`, `editorial_rules`, `attribution_rules`, `default_hashtags`, and `platform_preferences` are serialized into platform-generation input; output language and Telegram direction are also read by automation generation. `is_default` is returned as option metadata but no current backend selection logic consumes it. The page describes reusable “voice and language” profiles while language and most voice/policy data cannot be edited.

Brand updates are read at worker execution, not copied when a job is requested. A queued job can therefore observe a brand edit made after enqueue. Existing immutable drafts/revisions remain unchanged.

### Canonical story and Telegram pack prompts

Both cards use the same `PromptPurposeHistory` control with purpose keys `canonical_story` and `telegram_pack`.

| Display label | Internal field | Type, validation, default | Storage | Read/write and save behavior | Runtime effect and invalid/empty behavior | Status | Classification |
|---|---|---|---|---|---|---|---|
| `canonical_story system template` | `systemTemplate` -> `system_template` | Multiline string; default empty. Frontend create disabled when trimmed empty. Backend minimum length 1; no maximum. | New row in `prompt_template_versions.system_template` | History: `GET /prompt-templates/{templateId}/versions`; create: `POST` same path. Creates an inactive immutable version and clears both inputs. | Used as system message for canonical-story generation after activation. Arbitrarily large content is accepted. No required safety language is enforced. | Connected; raw high-impact control. | Keep but move under Advanced |
| `canonical_story user template` | `userTemplateValue` -> `user_template` | Multiline string; default empty. Frontend only requires non-empty. Backend permits exactly `{story_title}` and `{evidence_json}`, requires both, and rejects escaped, unknown, dotted, indexed, formatted, or converted fields. No maximum. | New immutable version row | Same create endpoint. Errors render inside create disclosure. | Used as canonical user message. Invalid placeholders return 422; generic client error handling may reduce structured Pydantic errors to “Unprocessable Entity.” | Connected; validation guidance missing. | Keep but move under Advanced |
| `telegram_pack system template` | `systemTemplate` -> `system_template` | Same behavior as canonical system template. | New `prompt_template_versions` row | Same endpoint family for Telegram Pack template. | Used as system message for generated Telegram content-pack variants and regeneration. | Connected; raw high-impact control. | Keep but move under Advanced |
| `telegram_pack user template` | `userTemplateValue` -> `user_template` | Backend permits and requires `{canonical_story_json}`, `{brand_profile_json}`, `{direction}`, `{instruction}`. Frontend gives no placeholder list. | New immutable version row | Same endpoint family. | Used for Telegram pack generation/regeneration. Invalid fields return 422. | Connected; validation guidance missing. | Keep but move under Advanced |
| Confirm `canonical_story` activation | `confirmActivation` | Transient boolean, default false; not persisted. | None | Enables activation button. Reset only after successful activation. | No runtime effect by itself. | Functional safeguard; technical label. | Keep but move under Advanced |
| Confirm `telegram_pack` activation | separate `confirmActivation` | Same. | None | Same. | Same. | Functional safeguard. | Keep but move under Advanced |

Activation calls `POST /prompt-template-versions/{versionId}/activate`, marks exactly one sibling active in the API transaction, and affects future content-pack requests and future regeneration requests immediately. Requests persist exact version IDs and checksums; queued/in-flight jobs and existing drafts keep their selected immutable versions.

Critical defect: API startup runs `seed_default_editorial_prompts()`. If the active canonical, Telegram-pack, Instagram, X, or blog version differs from code defaults, startup deactivates it and creates a new active default version. Tests explicitly assert this replacement behavior. Operator activation for these purposes is therefore not durable across API restart. Activation works only until restart unless the selected content exactly matches the code default.

### Telegram automation rewrite prompt

This is a different pipeline and purpose key (`telegram_rewrite`) from Telegram content packs (`telegram_pack`).

| Display label | Internal field | Type, validation, default | Storage | Read/write and save behavior | Runtime effect and invalid/empty behavior | Status | Classification |
|---|---|---|---|---|---|---|---|
| Custom instructions | `instructions` -> `system_template` | Multiline string. Frontend default: “Rewrite faithfully using only verified evidence.” No frontend non-empty check. Backend minimum length 1; no maximum or safety-policy validation. | New immutable `prompt_template_versions` row | `POST /prompt-templates/{telegramRewriteId}/versions`; creates inactive version, retains entered values, refetches history/options, shows success/error notice. | Existing automation routes are pinned to their original version ID and do not change. Only newly configured routes can select newly active version. Empty returns 422. | Connected, but label understates that this replaces full system prompt. | Rename or clarify |
| User template | `userTemplate` -> `user_template` | Multiline string. Frontend defaults to seven labeled placeholders. Browser checks presence of `{source_text}`, `{source_url}`, `{source_channel}`, `{language}`, `{direction}`, `{attribution_policy}`, `{custom_footer}`. Backend requires exactly those names and rejects unsupported/complex fields. No maximum. | Same immutable version row | Same create endpoint. Missing placeholders disable create and display list. Backend remains authoritative. | Worker formats values, stores a redacted prompt snapshot, and sends system/user messages plus fixed output schema to provider. Invalid syntax returns 422. | Functional; default does not load current active version. | Keep but move under Advanced |
| Confirm prompt activation | `activationConfirmed` | Transient boolean; default false. | None | Enables all inactive version buttons, resets on activation success. | No effect alone. | Functional safeguard. | Keep but move under Advanced |

Conditional **Initialize Telegram prompt** calls `POST /prompt-templates` with fixed purpose/name/description. Startup normally seeds this template, so the control is mostly recovery behavior. **Create prompt version**, **Inspect immutable templates**, version/checksum/status display, and per-version **Activate** are functional.

Telegram rewrite activation persists across normal restart when the seeded default checksum already exists, but it does not update any existing `automation_routes.prompt_template_version_id`. The current success notice, “New jobs will use the selected exact version,” is misleading for existing routes.

### AI providers

| Display label | Internal field | Type, validation, default | Storage | Read/write and save behavior | Runtime effect and invalid/empty behavior | Status | Classification |
|---|---|---|---|---|---|---|---|
| Provider profile name | `providerName` -> `name` | Required text; backend 1-120. Default empty. | `ai_provider_profiles.name` | `POST /ai-provider-profiles`; fixed `provider_type=openrouter`, `settings={}`, `enabled=true`. Name is not cleared after success. | Duplicate differing profile returns 409. Used as option label only. | Functional. | Keep but move under Advanced |
| Default model | `providerModel` -> `default_model` | Text, default `openai/gpt-5-mini`. Not required in browser. Backend OpenRouter requires 1-200 characters and non-null. | `ai_provider_profiles.default_model` | Included in provider POST. | Blank becomes `null` and returns 422. Generation resolver uses this unless a route model override exists. Research uses it too. | Connected; browser wrongly permits invalid empty submit. | Keep but move under Advanced |
| Provider environment variable name | `providerEnv` -> `secret_ref` | Required write-only text; pattern `[A-Z][A-Z0-9_]{2,127}`; autocomplete off; default empty. | `ai_provider_profiles.secret_ref` | Included in POST, omitted from all API outputs, cleared after success. | Worker resolves same name from restrictive `/run/secrets` file in production; development/local/test may fall back to process environment. Missing value leaves capability unavailable. Actual credential values normally fail the name pattern but must never be entered. | Functional secret boundary; terminology is deployment-specific. | Rename or clarify |
| Provider model | local `model` -> `default_model` | Text initialized from stored model. No inline length validation. | Same model column | `PATCH /ai-provider-profiles/{id}`. Save sends model and optional replacement reference, refetches providers/options, and shows notice. | Blank is valid for fake (runtime falls back to `fake-v1`) but rejected for OpenRouter/Codex. Disabled profiles cannot be saved at all. | Partly functional. | Keep but move under Advanced |
| Replacement environment variable name | `environmentName` -> `secret_ref` | Optional write-only text; same strict pattern; default empty. Hidden for Codex. | Same secret-reference column | Included in PATCH only when non-empty, then cleared. Blank means “leave unchanged,” not clear. | Invalid value blocks save with inline error. Missing referenced secret changes worker capability to unavailable after observation. | Functional; cannot inspect, clear, or distinguish current reference. | Rename or clarify |

Provider status controls show generation/research capability, unavailability codes, and worker-observed state. This state is time-bounded by `capability_observation_ttl_seconds` (120 seconds default), so `unknown` and `stale` are valid states.

Provider configuration gaps:

- A page-created OpenRouter profile stores validated defaults but no pricing or research budgets. It can support generation, never research. The page has no way to add pricing/budgets, although research workflows require both.
- The API/schema supports `fake`, `openrouter`, and `codex`, provider enable/disable, base URL, timeout, attribution headers, pricing, standard/deep research budgets, and Codex limits. Most are not editable here.
- Disabled profiles cannot be edited because **Save provider** is disabled, while no enable control exists. Current seeded OpenRouter and Codex profiles are therefore dead ends in the UI.
- API startup rewrites the `Codex CLI` profile to model `gpt-5.4`, canonical settings, no secret, and `enabled=CODEX_ENABLED`. Any model change made here is lost on API restart.
- OpenRouter `OPENROUTER_BASE_URL` and `OPENROUTER_DEFAULT_MODEL` are seed/runtime fallbacks. Stored profile settings win over runtime base URL, and the default model is only used when the seeded OpenRouter row is first created. Changing them does not rewrite existing profiles.
- `CODEX_ENABLED` and `CODEX_EXECUTABLE` require runtime restart/reconfiguration. Codex executable/authentication is not stored here.

### Telegram destinations

| Display label | Internal field | Type, validation, default | Storage | Read/write and save behavior | Runtime effect and invalid/empty behavior | Status | Classification |
|---|---|---|---|---|---|---|---|
| Destination name | `destinationName` -> `name` | Required text; backend 1-120. Default empty. | `destinations.name` | Read `GET /telegram/destinations`; create `POST /telegram/destinations` (`202`). Name is not cleared after success. No update endpoint/control. | Display/option label. Empty blocked. Same target with different configuration returns 409. | Create works; lifecycle incomplete. | Merge with another setting |
| Telegram channel reference | `targetRef` -> `target_ref` | Required text; backend only checks length 1-255. Placeholder suggests `@channel`; default empty. | `destinations.target_ref`, unique with platform | Included in destination POST. No normalization, edit, or delete. | Used by health worker `getChat` and publishing Bot API calls. URL, `@handle`, numeric IDs, and invalid strings are not distinguished. Current live data demonstrates URL/handle duplicates. | Connected but unsafe validation. | Rename or clarify |
| Destination environment variable name | `destinationEnv` -> `secret_ref` | Required write-only text; strict 3-128 uppercase pattern; autocomplete off; default empty. | `destinations.secret_ref` | Included in POST, omitted from output, cleared after acceptance. | Publishing worker resolves token from its scoped secret mount/environment. Missing value produces unavailable capability and failed health check. No replacement path exists. | Functional on create; cannot rotate through UI. | Merge with another setting |
| Allow automatic publishing | `allowAutoPublish` -> `settings.allow_auto_publish` | Boolean; default false. | `destinations.settings` JSONB | Included only during create; no update control. | This is a permission gate, not a direct publish switch. Auto-publish still requires route policy, explicit route confirmation, healthy/enabled destination, available worker capability, passing validation/evidence/media gates, and no global/route pause or dry run. | Functional but dangerous and poorly explained. | Rename or clarify |

Destination creation enqueues `telegram.destination.check`. The page refetches immediately but does not poll the queued job, refetch after completion, expose job ID, or provide **Recheck**. Health may remain `Unknown` until focus/reload. Destination creation is duplicated in the Automation route builder, which also makes the route depend on successful destination creation/check behavior.

### Remaining visible controls and displays

| Control/display | Behavior | Assessment | Classification |
|---|---|---|---|
| Loading content settings | Replaces page while any primary query is pending. | Clear, but one slow query blocks unrelated sections. | Keep in primary Content Settings |
| Retry settings | Refetches all four primary queries. | Functional. No per-section retry for primary cards. | Keep in primary Content Settings |
| Create brand / Save brand | Independent mutations with success/error notices. | Functional; no dirty state. | Keep in primary Content Settings |
| Immutable prompt history | Shows versions; Telegram rewrite exposes templates and short checksum, canonical/pack expose full checksum but not templates. | Inconsistent evidence/detail model. | Keep but move under Advanced |
| Create prompt disclosures/buttons | Creates inactive versions. Canonical/pack show inline create errors but no success feedback; Telegram rewrite uses notices. | Divergent behavior for same domain object. | Merge with another setting |
| Activate prompt buttons | Require transient confirmation. Telegram rewrite has notices; canonical/pack activation has neither error nor success UI. | High-impact action with incomplete feedback and restart defect. | Broken or not connected |
| Provider capability/unavailability display | Maps available/unavailable/stale/unknown and safe failure codes. | Useful operational truth; observation timestamps/expiry/owner are discarded by UI. | Keep but move under Advanced |
| Save provider | Updates model/reference only; disabled when profile is disabled. | Connected but traps disabled profiles. | Broken or not connected |
| Destination health, auto-publish, worker capability display | Read-only safe summary. | Useful, but no timestamp, reason, recheck, edit, or job progress. | Keep but move under Advanced |
| Create destination | Creates and queues health check. | Functional, duplicated with route builder, no completion tracking. | Merge with another setting |

## 4. Frontend, API, storage, and consumer dependency map

| Configuration | Frontend/API chain | PostgreSQL storage | Direct consumers | Downstream workflow impact |
|---|---|---|---|---|
| Brand profile | `ContentSettingsPage` -> `telegram-api.ts` -> `/brand-profiles` | `brand_profiles`; referenced by `automation_routes` and `content_packs` | Telegram automation handler; content-pack generation handler; route-builder options; brand option client | Automation rewrite language; all platform prompt brand JSON; Telegram direction; Drafts/Review receive generated immutable revisions but do not reread brand afterward. |
| Canonical prompt version | Purpose card -> prompt-version/activation endpoints | `prompt_templates`, `prompt_template_versions`; ID/checksum copied to job payload and `generation_runs` | `EditorialService.request_content_pack`; canonical generation handler | Research continuation into content generation; canonical story; all downstream platform variants; exact prompt snapshot/provenance in generation attempts. |
| Telegram-pack prompt version | Purpose card -> same endpoints | Same tables; exact ID/checksum in content-pack/regeneration job | Content-pack generation and regeneration handlers; Review variant editor prompt options | Telegram content-pack drafts and regenerated child revisions. Existing Drafts/Review content remains immutable. |
| Telegram-rewrite prompt version | Telegram editor -> same version/activation endpoints | Same tables; exact version ID pinned in `automation_routes` and recorded in generation runs/attempts | Automation route builder/options; Telegram processing worker | Source capture -> optional research -> automation rewrite -> Telegram draft -> Review or auto-publish. Activation does not repoint existing routes. |
| Provider profile model/type/settings/reference | Provider editor -> `/ai-provider-profiles` | `ai_provider_profiles`; referenced by research runs, generation runs, and automation routes | Source/generation worker capability observer; `ProviderProfileResolver`; ResearchService; Codex/OpenRouter/fake adapters; scheduler and route activation capability gates | Manual/automatic research, canonical generation, all platform generation, Review regeneration, automation generation. Credential values are resolved only inside scoped workers. |
| Destination target/reference/policy | Destination form -> `/telegram/destinations` | `destinations`; referenced by automation routes, publish jobs, and publications | Publishing-worker capability observer; destination-check handler; route creation; auto-publish policy gate; Telegram publish service; Automation builder/detail/Review | Route activation and scheduling, destination health, review-required vs eligible automatic publication, final Bot API target/token. |

### Research

- Research selects an exact `AIProviderProfile` UUID.
- Fake and Codex can use server-defined effective research budgets. OpenRouter research requires both pricing and standard/deep budgets in profile settings.
- The page can show research capability but cannot create a research-capable OpenRouter profile.
- Automation routes can pin a separate research provider inside `content_filters`; the scheduler and activation path require a fresh research capability observation.
- Research prompts in `backend/app/research/prompts.py` are code-defined and are not controlled by Content Settings.

### Content generation and platform output

- Canonical generation requires one active `canonical_story` version.
- Each requested platform requires one active purpose: `telegram_pack`, `instagram_pack`, `x_pack`, or `blog_pack`.
- Only canonical and Telegram-pack purposes appear here. Instagram, X, and blog prompt versions are seeded, consumed, returned by the shared API client, and selectable in option reads, but have no Content Settings controls.
- Brand profile data is serialized into generation inputs. Platform preferences affect direction and limits/context.
- Provider model, provider settings, credential availability, and exact prompt checksums are revalidated at execution boundaries.

### Drafts, Review, automation, and workers

- Content Settings does not mutate existing revisions. Drafts and Review operate on immutable generated revisions and evidence maps.
- Review regeneration selects provider and active platform prompt options, then creates a new child revision.
- Telegram automation routes pin brand, provider, destination, and `telegram_rewrite` version IDs. Workers resolve those rows at execution.
- Destination auto-publish permission combines with route policy and safety gates. It never bypasses Review by itself.
- Capability observations come from source/generation and publishing workers, not from API-process environment inspection.

### Environment and startup fallbacks

- Browser API calls use `NEXT_PUBLIC_API_BASE_URL` when set, otherwise `/api/backend` (it should normally stay unset so browser traffic keeps flowing through the proxy). The Next proxy resolves its upstream from `API_INTERNAL_BASE_URL`, then `http://localhost:8000`, and deliberately ignores `NEXT_PUBLIC_API_BASE_URL`; Compose supplies `http://api:8000`.
- Backend settings load from process environment and `.env`. `OPENROUTER_BASE_URL` defaults to `https://openrouter.ai/api/v1`; `OPENROUTER_DEFAULT_MODEL` defaults to `openai/gpt-5-mini`.
- Provider-profile `settings.base_url` overrides the runtime OpenRouter base URL. Since create/seed normally persists a base URL, later environment changes usually do not affect existing profiles.
- `CODEX_ENABLED=false`, `CODEX_EXECUTABLE=codex`, and the hardcoded seeded model `gpt-5.4` govern Codex. Executable/auth changes require worker runtime reload; API restart also rewrites the persisted Codex profile.
- `WORKER_SECRET_ROOT` defaults to `/run/secrets`. Production resolves references only from mounted files. Development/local/test may use environment values after file lookup fails.
- Prompt and default-brand fallbacks are code seeds executed during every API lifespan startup, not database defaults or frontend resets.

## 5. Functional and broken behavior

### Working

- Route and safe read APIs load in the running stack.
- Brand create and name/tone patch are wired through frontend, API, and database.
- Prompt versions are immutable, checksummed, schema-bound, and activatable through exact IDs.
- Telegram rewrite browser placeholder checks and backend strict formatting checks work together.
- Provider and destination credential values are not returned to browser/API clients.
- Provider model/reference patch works for enabled profiles.
- Destination create stores policy, enqueues a health check, and exposes safe worker capability state.
- Focused frontend suites passed: 12/12 tests with `NODE_ENV=test` (`content-settings-page.test.tsx`, `telegram-api.test.ts`).

### Broken, incomplete, or misleading

1. Canonical and platform prompt activation is reverted by startup seeding when content differs from code defaults.
2. Codex model/settings/enabled edits are reverted by API startup seeding.
3. Existing Telegram automation routes ignore later `telegram_rewrite` activation because routes pin old version IDs.
4. Page-created OpenRouter profiles cannot support research, and the UI cannot add required pricing/budget settings.
5. Disabled provider profiles cannot be edited or enabled from the page.
6. Canonical/Telegram-pack activation has no visible success or error handling.
7. Structured backend validation errors often collapse to generic HTTP status text in `getApiErrorMessage`.
8. Destination health-check completion is not tracked or polled.
9. Destinations cannot be updated, rotated, disabled, rechecked, or removed here.
10. Target references are not normalized or meaningfully validated; duplicate channel identities can be created.
11. Brand creation/editing hides fields that materially affect generation, while claiming to manage language profiles.
12. Canonical/pack cards cannot initialize missing templates; Telegram rewrite can.
13. Instagram, X, and blog prompt purposes are active runtime settings but absent from the page.
14. Hardcoded prompt editor defaults do not load current active prompt content, making “edit” effectively “start a new prompt from frontend defaults.”
15. No dirty-state warning, reset, or default restoration exists.
16. Brand and provider mutations invalidate their Content Settings and Telegram-option query keys, but not the separate editorial brand/provider option keys. Previously cached workflow selectors can remain stale; prompt activation correctly invalidates its editorial option key.

Backend unit tests were inspected but could not be executed in this session: host Python lacks pytest, and the running API image does not contain repository tests. Existing tests cover schema validation, immutable activation, credential-reference safety, worker observations, seed behavior, and destination job enqueue. No live write was attempted.

## 6. Security and secret handling

### Good boundaries

- Browser accepts only strict uppercase reference names for provider and destination credentials.
- API schemas apply the same full-match rule.
- `secret_ref` is stored in PostgreSQL but excluded from provider/destination response models.
- Production workers resolve only restrictive regular files from worker-scoped `/run/secrets` roots; symlinks, broad permissions, oversized files, invalid UTF-8, and empty values fail closed.
- Production does not fall back to process environment. Environment fallback is limited to development/local/test.
- Capability observations expose safe status/failure codes, never credential values or executable paths.
- Provider settings forbid unknown fields such as `api_key`; Codex forbids secret references.

### Risks

1. No application-level authentication, authorization, or role check was found on Content Settings read/write endpoints. If the app is reachable outside a trusted perimeter, any caller can change prompts, brands, provider references/models, and create auto-publish-permitted destinations. This is the highest security risk.
2. Raw system prompt activation can remove evidence/safety instructions. Backend validates fields and output schema, not semantic safety policy. There is no diff, policy lint, approver identity, audit reason, or two-person control.
3. Prompt sizes are unbounded, creating avoidable model-cost, payload, and storage risk.
4. **Allow automatic publishing** lacks an adjacent explanation of its downstream effect. Confirmation exists later in route creation, but this page grants destination-level permission permanently with no revoke control.
5. Credential reference names are write-only. This avoids leakage but makes rotation/debugging ambiguous; operators cannot tell whether they are replacing the intended reference.
6. Target validation accepts arbitrary text. Mistyped or URL-form targets create persistent unusable records and can conflict semantically without conflicting at the database key.
7. Prompt templates and brand text are operator-controlled model inputs. The generation prompts attempt to treat evidence/brand text as data, but changing system prompts can weaken that boundary.

## 7. UX problems

### Information hierarchy and terminology

- Six equal-weight cards mix daily editorial concepts with infrastructure and high-risk publishing controls.
- `canonical_story`, `telegram_pack`, environment variable, checksum, provider type, capability observation, and immutable version are exposed without operator-level explanation.
- “Telegram pack prompts” and “Telegram prompt versions” sound synonymous but control different pipelines.
- “Custom instructions” is really the complete automation system prompt.
- “Allow automatic publishing” sounds like a direct switch; it is one permission among several gates.

### Grouping and duplication

- Destination creation is duplicated in Automation builder.
- Prompt governance is implemented twice: generic purpose history and special Telegram rewrite editor. Validation, history detail, notices, and initialization differ.
- Provider/destination health is repeated across Content Settings, Automation builder, route list, and route detail without one canonical management location.
- Brand/profile/prompt selection in workflows is legitimate usage, but configuration and selection are not visually distinguished.

### Validation, feedback, and state

- Existing brand inputs and provider model inputs lack useful inline validation.
- Canonical/pack placeholder contracts are not shown before submit.
- Canonical/pack activation failures are silent.
- Destination asynchronous acceptance is presented as success without job progress or automatic final status.
- Page has no unsaved-change warning, reset, cancel, revert-to-stored, or restore-default action.
- Successful provider/destination creation clears only credential-reference inputs; other fields remain, enabling accidental duplicate resubmission and 409 errors.
- Status cards omit observation time, expiry, owner, and health-check time even though backend tracks them.

## 8. Recommended future information architecture

Keep `/settings/content` as an Advanced entry, but split it into explicit domains:

1. **Editorial profiles**
   - Primary: name, output language, tone, default profile.
   - Advanced disclosure: editorial rules, attribution rules, hashtags, platform preferences.
   - Explain when changes affect queued jobs versus existing revisions.

2. **Generation and research providers**
   - Profile list with enabled state, provider type, model, generation/research capability, and last observation.
   - Credential action labeled **Replace credential reference**, with configured/not-configured confirmation but no value exposure.
   - Advanced provider settings for validated base URL, timeouts, pricing, research budgets, and Codex limits, or explicitly declare them deployment-managed.
   - Separate persisted profile state from runtime/worker prerequisites.

3. **Prompt governance**
   - One consistent component for every purpose: canonical story, Telegram automation rewrite, Telegram/Instagram/X/blog packs.
   - Operator-friendly purpose names and pipeline descriptions.
   - Active-version summary, required variables, template diff, validation, immutable history, impact scope, and explicit activation warning.
   - Raw templates under Advanced. Startup defaults must never silently override operator activation.

4. **Publishing integrations**
   - Move Telegram destinations into Automation/Integrations, or make that area the sole destination manager and let route builder select/create through it.
   - Canonical target format, update/rotate/disable/recheck support, health job progress, last check, and clear auto-publish permission warning.

The primary Content Settings view should show only current editorial defaults and concise readiness summaries. Raw prompts, credential references, cost budgets, capability diagnostics, and publishing gates belong under Advanced subsections.

## 9. Proposed cleanup phases

### Phase 0: product and security decisions

- Decide trusted-access/authentication boundary and required roles for prompt/provider/destination mutation.
- Decide whether startup seed is migration-only, repair-only, or authoritative. Document which source wins.
- Decide whether `telegram_rewrite` remains a separate automation pipeline from `telegram_pack`.
- Choose one canonical Telegram target format and one destination-management location.

### Phase 1: correctness

- Preserve operator-selected active prompts across restart.
- Stop startup from overwriting editable Codex profile fields, or mark them deployment-managed/read-only.
- Make disabled profiles recoverable.
- Support research-capable OpenRouter configuration or state clearly that it is API/deployment-only.
- Normalize/validate targets and add destination rotation/recheck/update paths.
- Track destination health-check completion.

### Phase 2: safety and feedback

- Add authorization, semantic prompt warnings/diffs, size limits, and activation audit metadata.
- Render structured validation errors per field.
- Add explicit warnings for auto-publish permission and queued-job timing.
- Add consistent success/error feedback for every mutation.

### Phase 3: information architecture

- Split editorial profiles, providers, prompt governance, and publishing integrations.
- Merge duplicate destination setup and duplicate prompt-management components.
- Add missing platform prompt purposes and full brand fields only after product ownership is decided.

### Phase 4: state handling and coverage

- Add dirty tracking, cancel/reset/revert, and safe default restoration.
- Add tests for restart persistence, disabled-profile recovery, destination normalization/rotation, async check refresh, structured errors, every prompt purpose, and authorization.
- Add a live read-only smoke test for route/API status and a disposable-database write test; never use real credentials.

## 10. Risks and unknowns

- Authentication may exist at an external reverse proxy not represented in this repository. No application-layer enforcement was found.
- Product intent for startup seeding is unclear; current tests make override behavior explicit, but it conflicts with operator-managed activation.
- Product intent for two Telegram prompt pipelines is unclear. Both are active and consumed.
- `is_default` brand semantics are not implemented by backend selection logic. Future behavior needs a product decision.
- Current frontend imports editorial provider/prompt options for Review regeneration, while manual research/content-pack request clients exist without a visible caller in the inspected current frontend. Backend workflows remain active; frontend ownership may be mid-consolidation.
- Provider capability state can change after the snapshot. Live findings are point-in-time, not credential validation.
- No write-path live test was performed, by restriction. Backend unit execution was unavailable in the current host/container setup.
- Existing user worktree changes were present before this audit. Only this document was created.

## Evidence index

Primary frontend:

- `frontend/app/settings/content/page.tsx`
- `frontend/features/settings/content-settings-page.tsx`
- `frontend/features/automations/telegram-api.ts`
- `frontend/features/automations/telegram-types.ts`
- `frontend/lib/http.ts`
- `frontend/lib/editorial-api.ts`
- `frontend/features/automations/route-builder.tsx`
- `frontend/components/editorial/content-pack-workspace.tsx`
- `frontend/components/editorial/variant-editor.tsx`

Primary backend:

- `backend/app/api/generation_settings.py`
- `backend/app/api/generation_schemas.py`
- `backend/app/api/telegram_destinations.py`
- `backend/app/api/telegram_automations.py`
- `backend/app/api/telegram_schemas.py`
- `backend/app/generation/models.py`
- `backend/app/generation/default_prompts.py`
- `backend/app/generation/provider_settings.py`
- `backend/app/generation/providers/profiles.py`
- `backend/app/generation/editorial_service.py`
- `backend/app/generation/handlers.py`
- `backend/app/research/service.py`
- `backend/app/research/handlers.py`
- `backend/app/jobs/credential_capabilities.py`
- `backend/app/jobs/scheduler.py`
- `backend/app/core/config.py`
- `backend/app/core/secrets.py`
- `backend/app/automations/telegram/handlers.py`
- `backend/app/publishing/models.py`
- `backend/app/publishing/telegram/handlers.py`
- `backend/app/publishing/telegram/service.py`
- `backend/alembic/versions/0004_platform_spine.py`

Tests and documentation inspected:

- `frontend/tests/content-settings-page.test.tsx`
- `frontend/tests/telegram-api.test.ts`
- `frontend/tests/telegram-route-builder.test.tsx`
- `frontend/e2e/telegram-automation.spec.ts`
- `backend/tests/test_generation_settings_api.py`
- `backend/tests/test_default_prompts.py`
- `backend/tests/test_telegram_configuration_api.py`
- `backend/tests/test_credential_capabilities.py`
- `backend/tests/test_secret_resolver.py`
- `backend/tests/test_provider_profile_resolver.py`
- `backend/tests/research/`
- `backend/tests/generation/`
- `backend/tests/integration/test_editorial_research_generation_flow.py`
- `docs/operations/research-and-generation.md`
- `docs/implementation-reports/phase-06-credential-topology.md`
- `docs/frontend-audit/frontend-backend-matrix.md`
