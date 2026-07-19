# Persian generation qualification

`corpus-v1.json` is the locked synthetic 36-story baseline: 18 RSS and 18
Telegram fixtures, balanced by length, with 12 calibration and 24 held-out
stories. Evidence hashes are checked before any funded call.

The live campaign is intentionally available only through the protected manual
workflow. It requires an isolated database, one explicitly selected provider
profile, a positive preapproved budget, and two independent repeats. The normal
API does not expose the evaluation-run identity used to prevent deduplication.
The selected OpenRouter profile must use the exact funded model and include
explicit pricing plus a frozen qualified policy, for example:

```json
{
  "pricing": {
    "input_usd_per_million": "1.25",
    "output_usd_per_million": "5.00"
  },
  "generation_policy": {
    "qualification_status": "qualified",
    "max_output_tokens": 12000,
    "max_attempts": 3,
    "max_pack_cost_usd": "2.00",
    "max_elapsed_seconds": 180,
    "retryable_http_statuses": [408, 429, 500, 502, 503, 504],
    "automatic_model_fallback": false
  }
}
```

Production keeps that exact checksum disabled until the signed campaign passes;
enabling the same profile does not change its generation checksum.

After the run, two blinded native-Persian editors independently complete one
review per generated variant using `reviews-template-v1.json`. Every score
difference greater than one point must be listed in `adjudicated_variant_ids`.
Do not change prompts after reviewing held-out output; create a new prompt
version and restart the cohort.

Score and sign the completed review set only in the protected environment:

```bash
cd backend
PYTHONPATH=. python -m app.validation.persian_generation score \
  --run ../validation/persian-generation/run-v1.json \
  --reviews ../validation/persian-generation/reviews-v1.json \
  --output ../validation/persian-generation/report-v1.json \
  --signing-key-file /run/secrets/PERSIAN_EVALUATION_SIGNING_KEY
```

The scorer exits nonzero unless every Phase 13 schema, reliability, grounding,
Persian, title, promotion, cost, latency, and agreement threshold passes.
