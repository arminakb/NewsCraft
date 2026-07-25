# Public API contract

`openapi.json` is the canonical, deterministic public wire contract generated from FastAPI/Pydantic. Do not edit it or `frontend/lib/api/generated.ts` by hand.

Regenerate both artifacts from the repository root:

```bash
cd backend
PYTHONPATH=. uv run python scripts/export_openapi.py --output ../contracts/openapi.json
cd ../frontend
npm run api:generate
```

The committed schema carries `x-newscraft-contract.schema = newscraft-openapi-v1`. Frontend transport code may use generated wire types at the HTTP boundary, then map snake_case, nullable/optional values, date-time strings, cursors, and enums into explicit domain types. UI components should not depend directly on generated names.

Mocked browser responses for migrated routes are validated against the exact operation, status, and JSON response schema. An undocumented route/status or a missing required field fails closed. All mocked suites must return a failure for unmatched `/api/backend/**` requests; generic empty success responses are prohibited.

HTTP validation errors use the generated `HTTPValidationError` contract. Capability failures remain documented 503 responses and reconciliation conflicts remain 409 responses. Endpoints whose generated success body is currently `unknown` lack a backend response model; migrate them by adding an explicit Pydantic response model before replacing their handwritten frontend projection.

The public schema must never contain credential values or the internal OpenRouter/Telegram credential-setting field names enforced by `backend/tests/test_openapi_contract.py`.
