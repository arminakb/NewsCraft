# Task: Fix LLM Provider Live Test, Health, Readiness, and Capability Detection

The LLM Provider credential issue is already fixed.

A new API key has been entered successfully.

However, the current provider Test/Enable flow is still incorrect.

Current behavior in:

`Settings → LLM Provider`

When clicking `Test`, the UI shows only:

```text
Connection tested

OPENROUTER diagnostics refreshed.
```

This does NOT clearly prove that NewsCraft successfully authenticated to OpenRouter or that a real LLM request succeeded.

Then clicking `Enable` fails with:

```text
Provider action failed

llm provider not ready
```

Additionally, both capabilities currently show:

```text
Generation — unavailable
Research — unavailable
```

This must be investigated and fixed end-to-end.

Use both `Caveman` and `ui-ux-pro-max`.

Report clearly if either is unavailable.

---

# 1. Do Not Treat “Diagnostics Refreshed” as a Successful Connection Test

The current Test action must be traced from UI to backend.

Identify exactly what currently happens:

```text
Test button
→ frontend request
→ backend test endpoint
→ credential decryption
→ provider adapter
→ network request, if any
→ diagnostics result
→ readiness calculation
→ capability calculation
→ persisted provider state
→ frontend rendering
```

Determine whether the current implementation:

* only fetches metadata
* only refreshes cached diagnostics
* only validates configuration locally
* makes an unauthenticated request
* performs a real authenticated request
* performs an actual model generation request

Do not assume.

Report the exact current behavior before modifying it.

---

# 2. Test Must Perform a Real Authenticated Provider Request

For OpenRouter, clicking `Test` must perform a real backend-side authenticated request using the stored credential.

A Test is successful only when NewsCraft proves that:

```text
stored credential
→ decrypt successfully
→ authenticate with provider
→ reach provider
→ use configured model
→ receive a valid provider response
```

Do NOT mark a Provider healthy merely because:

* DNS works
* TCP connection works
* provider metadata endpoint responds
* model list loads
* diagnostics were refreshed

Those are useful diagnostics, but they are not sufficient to prove the configured model can actually be used.

---

# 3. Perform a Minimal Real Generation Probe

Use the canonical OpenRouter/provider adapter already present in NewsCraft.

Do not create a one-off frontend request to OpenRouter.

The test should perform a minimal low-cost generation request using the configured Generation model.

Conceptually:

```text
Provider Test
→ backend decrypts credential
→ provider adapter
→ configured generation model
→ minimal request
→ valid model response
→ generation capability = healthy
```

Keep the probe extremely small.

For example:

* minimal prompt
* minimal output token count
* no unnecessary context
* no streaming unless required by the existing adapter

Do not return the generated probe content to the user unless useful for diagnostics.

The goal is to verify that the configured model is genuinely callable.

---

# 4. Research Capability Must Be Tested Separately

Do NOT infer:

```text
Generation works
→ Research automatically works
```

Trace how NewsCraft defines the `research` capability.

Determine:

* whether Research uses a separate model
* whether it requires provider-specific tools
* whether it uses the same OpenRouter provider with a different model
* whether it requires web/search/tool support
* whether it has another backend capability contract

Then perform the correct real readiness test for Research.

Expected state must be based on reality:

```text
Generation
Healthy / Unavailable / Misconfigured

Research
Healthy / Unavailable / Misconfigured
```

If Research genuinely requires functionality that the configured model/provider does not support, keep it unavailable and explain WHY.

Do not simply force both flags to `true`.

---

# 5. Find Why `Enable` Says `llm provider not ready`

Trace the exact readiness predicate used by the Enable action.

Locate the code producing:

```text
llm provider not ready
```

Determine which condition is currently false.

Examples:

```text
credential valid?
connection healthy?
generation capability available?
research capability available?
last test successful?
model configured?
provider status persisted?
diagnostics stale?
```

Report the actual condition.

Do NOT work around the check by removing readiness validation.

Fix the mismatch between:

```text
Test result
```

and:

```text
Enable readiness evaluation
```

There must be one authoritative readiness model.

---

# 6. Define a Clear Provider Health State

Introduce or reuse an explicit health/readiness model.

Prefer states equivalent to:

```text
Untested
Testing
Healthy
Degraded
Unavailable
Configuration error
Credential replacement required
```

Do not add unnecessary states if equivalent ones already exist.

A provider should become `Healthy` only when its required real test succeeds.

Persist useful safe diagnostics such as:

* health status
* last tested at
* last successful test at
* latency
* provider name
* configured model
* generation status
* research status
* sanitized failure code/message

Never persist or expose plaintext credentials.

---

# 7. Test Result UI Must Be Informative

Replace the current vague success message:

```text
Connection tested
OPENROUTER diagnostics refreshed.
```

with a useful result.

For a successful test, show something like:

```text
Connection healthy

OpenRouter authenticated successfully.
Generation model responded successfully.

Generation      Healthy
Research        Healthy / Unavailable
Latency         842 ms
Last tested     Just now
```

Use the existing NewsCraft visual system.

Do not necessarily use this exact wording if the current Settings design has a better pattern.

The important point is that the operator must immediately understand:

* Did authentication succeed?
* Did a real model request succeed?
* Which capabilities are usable?
* Is the provider ready to enable?
* If not, why not?

---

# 8. Failed Tests Must Explain the Actual Failure

Examples:

### Invalid credential

```text
Connection failed

OpenRouter rejected the API credential.
```

### Model unavailable

```text
Connection authenticated, but the configured Generation model could not be used.
```

### Provider/network issue

```text
OpenRouter could not be reached.
```

### Research unsupported

```text
Generation is healthy.
Research is unavailable because the configured Research model does not support the required capability.
```

Use sanitized errors.

Do not dump raw provider payloads or stack traces into the UI.

---

# 9. Enable Behavior

Expected flow:

```text
Create Provider
→ enter credential
→ Save
→ Test
→ real provider probe succeeds
→ Provider becomes ready
→ Enable
→ Provider enabled successfully
```

If the Provider is not ready, `Enable` should not just show:

```text
llm provider not ready
```

The UI should explain which readiness requirement is missing.

Example:

```text
Provider is not ready

Run a successful connection test before enabling this provider.
```

or:

```text
Provider is not ready

The configured Generation model is unavailable.
```

Use the actual failed condition.

---

# 10. Do Not Require Both Capabilities Unless the Product Actually Requires Both

Inspect the existing NewsCraft capability model.

Do not accidentally define:

```text
Provider ready =
Generation healthy AND Research healthy
```

unless NewsCraft genuinely requires every enabled Provider to provide both.

If Providers can legitimately support only one capability, readiness must reflect that architecture.

For example:

```text
Provider
Generation: Healthy
Research: Unavailable
Provider: Ready for Generation
```

could be valid if NewsCraft supports capability-specific providers.

Determine the intended existing behavior from the backend/domain contracts rather than inventing a new rule.

---

# 11. Real Provider Test Must Remain Backend-Only

The flow must stay:

```text
Frontend
→ NewsCraft backend
→ credential service
→ provider adapter
→ OpenRouter
```

Never:

```text
Frontend
→ receives API key
→ calls OpenRouter directly
```

The stored API key must never be exposed to the browser.

---

# 12. Avoid Wasting API Credits

The real test request should be minimal.

Do not repeatedly test automatically on every:

* Settings page render
* polling interval
* frontend rerender
* provider list refresh

A real model probe should run only when appropriate, such as:

* explicit `Test`
* controlled readiness validation where existing architecture requires it

Do not silently consume LLM credits in the background.

---

# 13. Stale Health

A previous successful test should not permanently prove availability forever.

Reuse existing diagnostics expiration rules if they exist.

If NewsCraft has no concept of freshness, add only a conservative mechanism appropriate to the current architecture.

Do not trigger constant live probes.

The UI can show:

```text
Last tested 18 minutes ago
```

so the operator understands how fresh the result is.

---

# 14. Acceptance Test — OpenRouter

Perform a real runtime test with the newly entered credential.

Capture sanitized evidence.

Expected:

```text
OpenRouter provider saved
→ Test clicked
→ stored credential decrypted
→ authenticated request sent
→ configured Generation model called
→ valid response received
→ Generation becomes Healthy
```

Then verify Research independently.

Capture:

* Provider ID
* provider type
* model tested
* HTTP/provider result
* sanitized provider response status
* latency
* Generation capability result
* Research capability result
* resulting readiness state

Never print the API key.

---

# 15. Enable Acceptance

After successful Test:

```text
Test
→ Healthy
→ Enable
```

must succeed if the Provider satisfies NewsCraft's real readiness rules.

Then:

* reload Settings
* confirm Provider remains enabled
* confirm health state remains visible
* confirm capability states remain correct

If Enable still fails, trace the backend condition rather than hiding the error.

---

# 16. Verify Real NewsCraft Usage

Do not stop at the Settings page.

After enabling the Provider, verify that the actual LLM provider resolution layer can select it for its supported capability.

For Generation:

```text
NewsCraft generation capability
→ selects enabled OpenRouter provider
→ uses configured model
```

For Research:

```text
NewsCraft research capability
→ selects enabled compatible provider
```

If Research remains unavailable, report exactly why.

Do NOT fake a successful workflow run solely for acceptance.

---

# 17. Tests

Add regression coverage for:

* successful authenticated provider Test
* failed authentication
* unreachable provider
* valid credential + invalid model
* Generation capability success
* Research capability success/failure
* readiness persistence
* Enable after successful Test
* Enable before Test
* stale/failed Test state
* provider reload
* safe sanitized error responses
* no API-key exposure
* no unnecessary automatic live probes

Run:

* focused backend LLM Provider tests
* provider adapter tests
* readiness/capability tests
* Settings API tests
* Settings frontend tests
* frontend typecheck
* backend lint/type checks
* production build
* real browser Settings E2E
* real OpenRouter runtime Test

Do not mock the final runtime acceptance.

---

# Required Report

Report:

1. What the old `Test` button actually did.
2. Why it displayed `Connection tested` without proving readiness.
3. Exact reason `Enable` returned `llm provider not ready`.
4. Existing readiness predicate before the fix.
5. Final authoritative readiness model.
6. Real OpenRouter request performed by Test.
7. Generation test result.
8. Research test result.
9. Whether both capabilities are required for readiness.
10. Provider health after Test.
11. Enable result.
12. Modified files.
13. Tests/results.
14. Sanitized runtime evidence.

Do NOT mark this task complete merely because the toast wording changed.

Acceptance requires a real path equivalent to:

```text
stored credential
→ decrypt
→ authenticate
→ real configured-model request
→ capability health established
→ readiness established
→ Enable succeeds
→ NewsCraft can select the Provider
```

---

# Git Commit — REQUIRED

After implementation and verification:

* inspect the working tree
* preserve unrelated changes
* stage only this LLM Provider health/readiness work
* create a dedicated commit
* do not use destructive Git commands

Suggested commit:

```text
fix(settings): verify llm provider readiness with live probes
```

Report:

* commit hash
* final `git status`

Do not leave the task uncommitted after successful verification.
