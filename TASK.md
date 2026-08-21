# Fix: LLM Provider List Not Populating in Workflow Editor Nodes

## Objective
Resolve a bug where AI-powered nodes in the Workflow Editor fail to load user-configured LLM providers, and ensure all providers added under Settings are fully usable within these nodes.

## Context
- **Location:** Automations → Workflow Editor
- **Affected nodes:** AI Research, AI Generate
- **Related settings:** Settings → LLM Provider (where providers are added/configured)

## Current Behavior (Bug)
When configuring the LLM provider option inside the AI Research or AI Generate node settings, the selector does not display the providers added under Settings → LLM Provider. Instead, it only shows a single hardcoded option, `Deterministic Fake`. None of the previously added providers appear as selectable options.

## Expected Behavior
The LLM provider selector inside AI Research and AI Generate node settings should:
- Dynamically populate with all LLM providers currently configured under Settings → LLM Provider
- Allow the user to select any of these providers for use within that node
- Stay in sync when providers are added, edited, or removed in Settings

## Requirements
1. Identify why the node-level provider selector isn't reading from the Settings → LLM Provider data source (e.g., hardcoded option list, incorrect state/API binding, missing fetch call, stale cache).
2. Connect the node settings UI to the actual source of truth for configured providers.
3. Apply the fix to both the AI Research and AI Generate nodes (and any other nodes sharing this provider-selection component, if applicable).
4. Verify the fix works for:
   - Providers that existed before the fix
   - Newly added providers
   - The edge case of no providers configured (should not break, and shouldn't silently default to only `Deterministic Fake`)

## Acceptance Criteria
- [ ] Opening the LLM provider selector in AI Research / AI Generate nodes shows all providers currently listed in Settings → LLM Provider
- [ ] Selecting a provider in the node correctly persists and is used at execution time
- [ ] No regression to existing node functionality

## Deliverable
Once implemented and verified, commit all changes to git with a clear, descriptive commit message.
