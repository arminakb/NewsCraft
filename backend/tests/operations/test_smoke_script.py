from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from smoke import SmokeDriver, main  # noqa: E402

STEPS = [
    "health",
    "configure",
    "manual_intake",
    "collect",
    "research",
    "generate_four_platforms",
    "edit_and_approve",
    "telegram_dry_run",
    "export",
    "manual_plan",
    "pause_and_resume",
    "history",
    "diagnostics",
]
SECRET_CANARY = "smoke-response-secret-canary"


def _uuid(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012d}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeSmokeAPI:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.job_reads: dict[str, int] = {}
        self.option_reads = 0
        self.research_citations = True
        self.control = {
            "global_pause": False,
            "dry_run": False,
            "pause_reason": None,
            "paused_at": None,
            "updated_at": "2026-07-13T09:00:00Z",
        }
        self.plan_scheduled_for = "2026-07-14T09:00:00Z"
        self.server: ThreadingHTTPServer | None = None
        self.thread: Thread | None = None
        self.ids = {
            "source": _uuid(1),
            "destination": _uuid(2),
            "destination_job": _uuid(3),
            "brand": _uuid(4),
            "prompt": _uuid(5),
            "provider": _uuid(6),
            "route": _uuid(7),
            "activation_job": _uuid(8),
            "manual_job": _uuid(9),
            "story": _uuid(10),
            "evidence": _uuid(11),
            "research_run": _uuid(12),
            "research_job": _uuid(13),
            "story_revision": _uuid(14),
            "generation_job": _uuid(15),
            "generation_child_job": _uuid(16),
            "pack": _uuid(17),
            "telegram_variant": _uuid(18),
            "instagram_variant": _uuid(19),
            "x_variant": _uuid(20),
            "blog_variant": _uuid(21),
            "telegram_revision": _uuid(22),
            "instagram_revision": _uuid(23),
            "x_revision": _uuid(24),
            "blog_revision": _uuid(25),
            "edited_revision": _uuid(26),
            "dry_run_job": _uuid(27),
            "dispatch": _uuid(28),
            "export_job": _uuid(29),
            "plan": _uuid(30),
            "backfill_job": _uuid(31),
        }
        self.hashes = {
            "telegram": "a" * 64,
            "instagram": "b" * 64,
            "x": "c" * 64,
            "blog": "d" * 64,
            "edited": "e" * 64,
        }

    @property
    def base_url(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                fake.handle(self)

            def do_POST(self) -> None:  # noqa: N802
                fake.handle(self)

            def do_PATCH(self) -> None:  # noqa: N802
                fake.handle(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def handle(self, request: BaseHTTPRequestHandler) -> None:
        parsed = urlsplit(request.path)
        length = int(request.headers.get("Content-Length", "0"))
        raw_body = request.rfile.read(length) if length else b""
        body = json.loads(raw_body) if raw_body else None
        record = {
            "method": request.command,
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "headers": dict(request.headers.items()),
            "body": body,
        }
        self.requests.append(record)
        try:
            status, payload = self.response(
                request.command,
                parsed.path,
                body,
                parse_qs(parsed.query),
            )
        except AssertionError as exc:
            status, payload = 500, {"detail": str(exc) or "fake assertion failed"}
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        request.send_response(status)
        request.send_header(
            "Content-Type",
            "application/octet-stream" if isinstance(payload, bytes) else "application/json",
        )
        request.send_header("Content-Length", str(len(encoded)))
        request.end_headers()
        request.wfile.write(encoded)

    def response(
        self,
        method: str,
        path: str,
        body: object,
        query: dict[str, list[str]],
    ) -> tuple[int, object]:
        ids = self.ids
        if (method, path) == ("GET", "/health/live"):
            return 200, {"status": "alive", "token": SECRET_CANARY}
        if (method, path) == ("GET", "/automation-control"):
            return 200, self.control
        if (method, path) == ("PATCH", "/automation-control"):
            self.control = {
                **self.control,
                **body,
                "pause_reason": body.get("pause_reason") if body.get("global_pause") else None,
                "paused_at": "2026-07-13T09:30:00Z" if body.get("global_pause") else None,
                "updated_at": "2026-07-13T09:30:00Z",
            }
            return 200, self.control
        if (method, path) == ("POST", "/brand-profiles"):
            assert body == {
                "name": f"{self._run_id()}-brand",
                "output_language": "fa",
                "tone": "حرفه‌ای، دقیق و شفاف",
                "editorial_rules": ["ادعاها باید به شواهد ثبت‌شده متکی باشند."],
                "attribution_rules": {"preserve_sources": True},
                "default_hashtags": [],
                "platform_preferences": {"direction": "rtl"},
                "is_default": False,
            }
            return 201, {"id": ids["brand"], **body}
        if (method, path) == ("POST", "/llm-providers"):
            assert body == {
                "name": f"{self._run_id()}-provider",
                "protocol": "fake",
                "default_model": "fake-v1",
                "enabled": True,
            }
            return 201, {
                "id": ids["provider"],
                **body,
                "settings": {},
                "configured": True,
                "generation_ready": True,
                "research_ready": True,
            }
        if (method, path) == ("POST", "/telegram/sources"):
            return 201, {
                "id": ids["source"],
                "name": body["name"],
                "channel_ref": body["channel_ref"],
                "access_mode": "public_html",
                "language_hint": "fa",
                "configured": True,
            }
        if (method, path) == ("POST", "/telegram/destinations"):
            assert body["target"].startswith("@newscraft_smoke_")
            assert body["bot_token"].startswith("123456:deterministic-smoke-token-")
            return 202, {
                "destination": {
                    "id": ids["destination"],
                    "name": body["name"],
                    "target_ref": body["target"],
                    "enabled": False,
                    "health_status": "unknown",
                    "configured": True,
                    "administrator_status": "checking",
                },
                "job": {
                    "job_id": ids["destination_job"],
                    "status": "queued",
                    "deduplicated": False,
                },
            }
        if (method, path) == ("POST", f"/telegram/destinations/{ids['destination']}/enable"):
            return 200, {
                "id": ids["destination"],
                "name": "Smoke destination",
                "target_ref": "@newscraft_smoke_test",
                "enabled": True,
                "health_status": "healthy",
                "configured": True,
                "administrator_status": "administrator",
            }
        if (method, path) == ("GET", "/telegram/automations/options"):
            self.option_reads += 1
            capability_status = "available" if self.option_reads > 1 else "unknown"
            capability_available = self.option_reads > 1
            return 200, {
                "sources": [
                    {
                        "id": ids["source"],
                        "name": "Smoke source",
                        "access_mode": "public_html",
                        "capability_state": {"status": capability_status},
                    }
                ],
                "destinations": [
                    {
                        "id": ids["destination"],
                        "name": "Smoke destination",
                        "health_status": "healthy",
                        "capability_state": {"status": capability_status},
                    }
                ],
                "brand_profiles": [{"id": ids["brand"], "name": "Default Newsroom"}],
                "prompt_template_versions": [{"id": ids["prompt"], "version": 1}],
                "ai_provider_profiles": [
                    {
                        "id": ids["provider"],
                        "name": "Deterministic Fake",
                        "provider_type": "fake",
                        "default_model": "fake-v1",
                        "configured": capability_available,
                        "capabilities": {
                            "generation": capability_available,
                            "research": capability_available,
                        },
                    }
                ],
            }
        if (method, path) == ("POST", "/telegram/automations"):
            return 201, self._route(body["name"], {"status": "not_initialized"})
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/activate"):
            cursor = {
                "status": "initializing",
                "activation_requested_at": "2026-07-13T09:00:00Z",
                "activation_message_id": None,
                "last_message_id": None,
                "recent_fingerprints": {},
            }
            return 202, {
                "route": self._route("Smoke route", cursor),
                "job": {
                    "job_id": ids["activation_job"],
                    "status": "queued",
                    "deduplicated": False,
                },
            }
        if (method, path) == ("GET", f"/telegram/automations/{ids['route']}"):
            return 200, self._route(
                "Smoke route",
                {
                    "status": "ready",
                    "activation_requested_at": "2026-07-13T09:00:00Z",
                    "activation_message_id": 44,
                    "last_message_id": 44,
                    "recent_fingerprints": {},
                },
            )
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/backfill") and body == {"count": 101}:
            return 422, {"detail": "count must be less than or equal to 100"}
        if (method, path) == ("POST", "/stories/manual"):
            return 202, {
                "job_id": ids["manual_job"],
                "status": "queued",
                "deduplicated": False,
            }
        if (method, path) == ("GET", f"/stories/{ids['story']}"):
            return 200, {
                "id": ids["story"],
                "title": "گزارش آزمایشی",
                "status": "inbox",
                "evidence_count": 1,
                "completeness": {"complete": False},
            }
        if (method, path) == ("GET", f"/stories/{ids['story']}/evidence"):
            return 200, [
                {
                    "id": ids["evidence"],
                    "evidence_key": "content:smoke",
                    "content_text": "متن مستند آزمایشی برای گردش کامل محلی.",
                    "content_sha256": _sha("evidence"),
                    "source_url": None,
                }
            ]
        if (method, path) == ("POST", f"/stories/{ids['story']}/research-runs"):
            return 202, {
                "disposition": "enqueued",
                "run_id": ids["research_run"],
                "job_id": ids["research_job"],
                "completeness": {
                    "complete": False,
                    "score": 25,
                    "reasons": ["fewer_than_two_independent_sources"],
                    "independent_source_count": 1,
                    "body_character_count": 50,
                    "has_primary_evidence": True,
                },
            }
        if (method, path) == ("GET", f"/research-runs/{ids['research_run']}"):
            return 200, {
                "id": ids["research_run"],
                "story_id": ids["story"],
                "status": "succeeded",
                "result_revision_id": ids["story_revision"],
                "job_status": "succeeded",
                "sources": [],
                "events": [{"event_type": "research.succeeded"}],
            }
        if (method, path) == ("GET", f"/stories/{ids['story']}/revisions"):
            citations = (
                [
                    {
                        "evidence_key": "content:smoke",
                        "evidence_snapshot_id": ids["evidence"],
                        "source_url": None,
                        "locator": "chars:0-40",
                        "excerpt_sha256": _sha("evidence"),
                    }
                ]
                if self.research_citations
                else []
            )
            return 200, [
                {
                    "id": ids["story_revision"],
                    "story_id": ids["story"],
                    "revision_number": 1,
                    "citations": citations,
                    "created_by": "research",
                }
            ]
        if (method, path) == ("POST", f"/stories/{ids['story']}/content-packs"):
            return 202, {
                "job_id": ids["generation_job"],
                "status": "queued",
                "deduplicated": False,
            }
        if (method, path) == ("GET", f"/content-packs/{ids['pack']}"):
            return 200, self._pack()
        if method == "POST" and path.startswith("/platform-variant-revisions/") and path.endswith("/approve"):
            revision_id = path.split("/")[2]
            if revision_id == ids["edited_revision"] and body["expected_content_hash"] != self.hashes["edited"]:
                return 409, {"detail": "revision content hash changed"}
            return 200, self._approved_revision(revision_id)
        if (method, path) == (
            "POST",
            f"/platform-variants/{ids['telegram_variant']}/revisions",
        ):
            return 201, {
                **self._telegram_revision(ids["edited_revision"], self.hashes["edited"]),
                "parent_revision_id": ids["telegram_revision"],
                "revision_number": 2,
                "approval_state": "pending_review",
            }
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/dry-run"):
            count = sum(request["method"] == "POST" and request["path"] == path for request in self.requests)
            return 202, {
                "route": self._route("Smoke route", {"status": "ready", "last_message_id": 44}),
                "job": {
                    "job_id": ids["dry_run_job"],
                    "status": "succeeded" if count > 1 else "queued",
                    "deduplicated": count > 1,
                },
            }
        if (method, path) == ("GET", f"/telegram/automations/{ids['route']}/dispatches"):
            return 200, [
                {
                    "id": ids["dispatch"],
                    "route_id": ids["route"],
                    "source_key": "dry:job:album:900",
                    "source_fingerprint": _sha("album"),
                    "source_message_ids": [42, 43, 44],
                    "dispatch_kind": "dry_run",
                    "status": "needs_review",
                    "variant_revision_id": ids["edited_revision"],
                }
            ]
        if (method, path) == ("POST", f"/content-packs/{ids['pack']}/exports"):
            return 202, {
                "job_id": ids["export_job"],
                "status": "queued",
                "deduplicated": False,
            }
        if (method, path) == ("GET", f"/exports/{ids['export_job']}"):
            return 200, self._export()
        if method == "GET" and path.startswith(f"/exports/{ids['export_job']}/download/"):
            file_name = path.removeprefix(f"/exports/{ids['export_job']}/download/")
            return 200, self._export_downloads()[file_name]
        if (method, path) == ("POST", "/manual-publication-plans"):
            self.plan_scheduled_for = body["scheduled_for"]
            return 201, self._plan(self.plan_scheduled_for)
        if (method, path) == (
            "GET",
            f"/platform-variant-revisions/{ids['instagram_revision']}/manual-publication-plan",
        ):
            return 200, self._plan(self.plan_scheduled_for)
        if (method, path) == (
            "PATCH",
            f"/manual-publication-plans/{ids['plan']}/checklist",
        ):
            assert body == {
                "checklist_state": {
                    "caption_final": True,
                    "carousel_order": True,
                    "source_attribution": True,
                }
            }
            return 200, {**self._plan(self.plan_scheduled_for), "status": "ready", **body}
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/pause"):
            route = self._route("Smoke route", {"status": "ready", "last_message_id": 44})
            route["paused_at"] = "2026-07-13T09:31:00Z"
            return 200, route
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/resume"):
            return 200, self._route("Smoke route", {"status": "ready", "last_message_id": 44})
        if (method, path) == ("POST", f"/telegram/automations/{ids['route']}/backfill"):
            assert body in ({"count": 101}, {"count": 1})
            if body == {"count": 101}:
                return 422, {"detail": "count must be less than or equal to 100"}
            return 202, {
                "route": self._route("Smoke route", {"status": "ready", "last_message_id": 44}),
                "job": {
                    "job_id": ids["backfill_job"],
                    "status": "queued",
                    "deduplicated": False,
                },
            }
        if (method, path) == ("GET", "/operations/history"):
            return 200, {
                "items": [
                    {
                        "id": "event:smoke",
                        "category": "pause" if query.get("category") == ["pause"] else "generation",
                        "status": "succeeded",
                        "job_id": ids["generation_child_job"],
                        "subject_url": (
                            f"/automations/{ids['route']}"
                            if query.get("subject_type") == ["automation_route"]
                            else f"/stories/{ids['story']}"
                        ),
                    }
                ],
                "next_cursor": None,
            }
        if (method, path) == ("GET", "/operations/diagnostics"):
            return 200, {
                "generated_at": "2026-07-13T10:00:00Z",
                "global_paused": self.control["global_pause"],
                "dry_run": self.control["dry_run"],
                "components": {
                    name: {
                        "status": "healthy",
                        "observed_at": "2026-07-13T09:59:00Z",
                        "last_success_at": "2026-07-13T09:59:00Z",
                        "message": "healthy",
                        "action_url": None,
                    }
                    for name in (
                        "worker-source-generation",
                        "worker-publishing",
                        "scheduler",
                    )
                },
                "queue_counts": {
                    "queued": 0,
                    "running": 0,
                    "retrying": 0,
                    "succeeded": 7,
                    "failed": 0,
                    "needs_review": 1,
                    "cancelled": 0,
                },
                "attention": [],
            }
        if method == "GET" and path.startswith("/jobs/"):
            return 200, self._job(path.removeprefix("/jobs/"))
        return 404, {"detail": f"unexpected fake route: {method} {path}"}

    def _run_id(self) -> str:
        for request in self.requests:
            key = str(request["headers"].get("Idempotency-Key", ""))
            if key.startswith("smoke-"):
                return key.split(":", 1)[0]
        raise AssertionError("smoke run id unavailable")

    def _route(self, name: str, cursor: dict[str, object]) -> dict[str, object]:
        ids = self.ids
        return {
            "id": ids["route"],
            "name": name,
            "source_id": ids["source"],
            "destination_id": ids["destination"],
            "brand_profile_id": ids["brand"],
            "prompt_template_version_id": ids["prompt"],
            "ai_provider_profile_id": ids["provider"],
            "access_mode": "public_html",
            "research_mode": "off",
            "content_filters": {},
            "media_policy": "preserve",
            "attribution_policy": "preserve",
            "custom_footer": None,
            "publishing_policy": "review_required",
            "poll_interval_seconds": 300,
            "quiet_hours": {},
            "retry_policy": {},
            "cursor_state": cursor,
            "enabled": cursor.get("status") != "not_initialized",
            "paused_at": None,
        }

    def _job(self, job_id: str) -> dict[str, object]:
        ids = self.ids
        self.job_reads[job_id] = self.job_reads.get(job_id, 0) + 1
        if job_id == ids["backfill_job"] and self.job_reads[job_id] == 1:
            return {
                "id": job_id,
                "job_type": "telegram.route.backfill",
                "status": "queued",
                "origin": "manual",
                "pause_sensitive": True,
                "started_at": None,
                "result": {},
            }
        if self.job_reads[job_id] == 1:
            return {"id": job_id, "status": "running", "result": {}}
        results = {
            ids["destination_job"]: {"destination_id": ids["destination"]},
            ids["activation_job"]: {"route_id": ids["route"]},
            ids["manual_job"]: {"story_id": ids["story"]},
            ids["research_job"]: {
                "run_id": ids["research_run"],
                "story_revision_id": ids["story_revision"],
            },
            ids["generation_job"]: {
                "story_revision_id": ids["story_revision"],
                "continuation_job_id": ids["generation_child_job"],
            },
            ids["generation_child_job"]: {"content_pack_id": ids["pack"]},
            ids["dry_run_job"]: {"dispatch_id": ids["dispatch"]},
            ids["export_job"]: {"export_id": ids["export_job"]},
            ids["backfill_job"]: {"captured": 1},
        }
        assert job_id in results
        return {"id": job_id, "status": "succeeded", "result": results[job_id]}

    def _telegram_revision(self, revision_id: str, content_hash: str) -> dict[str, object]:
        return {
            "id": revision_id,
            "platform": "telegram",
            "platform_variant_id": self.ids["telegram_variant"],
            "content_pack_id": self.ids["pack"],
            "content": {
                "body": "<b>گزارش آزمایشی</b>",
                "parse_mode": "HTML",
                "buttons": [],
                "source_item_id": None,
                "source_url": None,
                "media_policy": "omit",
                "media_asset_ids": [],
                "direction": "rtl",
                "dry_run": False,
            },
            "content_hash": content_hash,
            "evidence_map": [{"evidence_snapshot_id": self.ids["evidence"]}],
            "approval_state": "pending_review",
            "parent_revision_id": None,
            "revision_number": 1,
        }

    def _pack(self) -> dict[str, object]:
        ids = self.ids
        citation = {
            "evidence_key": "content:smoke",
            "evidence_snapshot_id": ids["evidence"],
            "source_url": None,
            "locator": "chars:0-40",
            "excerpt_sha256": _sha("evidence"),
        }
        revisions = {
            "telegram": self._telegram_revision(ids["telegram_revision"], self.hashes["telegram"]),
            "instagram": {
                "id": ids["instagram_revision"],
                "platform": "instagram",
                "platform_variant_id": ids["instagram_variant"],
                "content_pack_id": ids["pack"],
                "content": {
                    "caption": "گزارش آزمایشی",
                    "carousel": [],
                    "citations": [citation],
                },
                "content_hash": self.hashes["instagram"],
                "approval_state": "pending_review",
            },
            "x": {
                "id": ids["x_revision"],
                "platform": "x",
                "platform_variant_id": ids["x_variant"],
                "content_pack_id": ids["pack"],
                "content": {"posts": [{"text": "Smoke", "citations": [citation]}]},
                "content_hash": self.hashes["x"],
                "approval_state": "pending_review",
            },
            "blog": {
                "id": ids["blog_revision"],
                "platform": "blog",
                "platform_variant_id": ids["blog_variant"],
                "content_pack_id": ids["pack"],
                "content": {
                    "title": "Smoke",
                    "body_markdown": "# Smoke\n\nGrounded body.",
                    "citations": [citation],
                },
                "content_hash": self.hashes["blog"],
                "approval_state": "pending_review",
            },
        }
        return {
            "id": ids["pack"],
            "story_id": ids["story"],
            "story_revision_id": ids["story_revision"],
            "status": "draft",
            "variants": [
                {
                    "id": ids[f"{platform}_variant"],
                    "platform": platform,
                    "current_revision": revisions[platform],
                }
                for platform in ("telegram", "instagram", "x", "blog")
            ],
        }

    def _approved_revision(self, revision_id: str) -> dict[str, object]:
        ids = self.ids
        if revision_id in {ids["telegram_revision"], ids["edited_revision"]}:
            result = self._telegram_revision(
                revision_id,
                self.hashes["edited"] if revision_id == ids["edited_revision"] else self.hashes["telegram"],
            )
        else:
            platform = {
                ids["instagram_revision"]: "instagram",
                ids["x_revision"]: "x",
                ids["blog_revision"]: "blog",
            }[revision_id]
            result = next(item["current_revision"] for item in self._pack()["variants"] if item["platform"] == platform)
        return {**result, "approval_state": "approved"}

    def _export(self) -> dict[str, object]:
        ids = self.ids
        revision_ids = {
            "telegram": ids["edited_revision"],
            "instagram": ids["instagram_revision"],
            "x": ids["x_revision"],
            "blog": ids["blog_revision"],
        }
        hashes = {**self.hashes, "telegram": self.hashes["edited"]}
        file_contents = self._export_file_contents()
        manifest = {
            "schema_version": "newscraft-export-v1",
            "content_pack_id": ids["pack"],
            "story_revision_id": ids["story_revision"],
            "created_at": "2026-07-13T09:45:00Z",
            "variants": [
                {
                    "platform": platform,
                    "platform_variant_id": ids[f"{platform}_variant"],
                    "revision_id": revision_ids[platform],
                    "content_hash": hashes[platform],
                    "approval_state": "approved",
                    "evidence_urls": [],
                }
                for platform in ("telegram", "instagram", "x", "blog")
            ],
            "files": [
                {
                    "file_name": file_name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "byte_length": len(content),
                    "kind": {"json": "json", "md": "markdown", "html": "html"}[file_name.rsplit(".", 1)[1]],
                    "platform": platform,
                    "revision_id": revision_ids[platform],
                    "media_asset_id": None,
                }
                for platform in ("telegram", "instagram", "x", "blog")
                for file_name, content in file_contents.items()
                if file_name.startswith(f"{platform}/")
            ],
        }
        manifest_hash = hashlib.sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return {
            "export_id": ids["export_job"],
            "status": "succeeded",
            "finished_at": "2026-07-13T09:45:01Z",
            "artifact": {
                "export_id": ids["export_job"],
                "content_pack_id": ids["pack"],
                "state": "complete",
                "manifest_file": "manifest.json",
                "manifest_sha256": manifest_hash,
                "archive_file": "bundle.zip",
                "archive_sha256": hashlib.sha256(b"deterministic-fake-archive").hexdigest(),
                "manifest": manifest,
            },
            "downloads": [
                f"/exports/{ids['export_job']}/download/{name}"
                for name in ("manifest.json", "bundle.zip", *file_contents)
            ],
            "error_code": None,
            "error_message": None,
        }

    def _export_file_contents(self) -> dict[str, bytes]:
        ids = self.ids
        revision_ids = {
            "telegram": ids["edited_revision"],
            "instagram": ids["instagram_revision"],
            "x": ids["x_revision"],
            "blog": ids["blog_revision"],
        }
        return {
            f"{platform}/{revision_ids[platform]}/content.{extension}": (
                f"{platform}-{extension}-acceptance\n".encode()
            )
            for platform in ("telegram", "instagram", "x", "blog")
            for extension in ("json", "md", "html")
        }

    def _export_downloads(self) -> dict[str, bytes]:
        export = self._export()
        artifact = export["artifact"]
        assert isinstance(artifact, dict)
        manifest = artifact["manifest"]
        return {
            "manifest.json": json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            "bundle.zip": b"deterministic-fake-archive",
            **self._export_file_contents(),
        }

    def _plan(self, scheduled_for: str) -> dict[str, object]:
        return {
            "id": self.ids["plan"],
            "platform_variant_revision_id": self.ids["instagram_revision"],
            "platform": "instagram",
            "scheduled_for": scheduled_for,
            "display_timezone": "Asia/Tehran",
            "status": "planned",
            "checklist_state": {
                "caption_final": False,
                "carousel_order": False,
                "source_attribution": False,
            },
            "external_url": None,
            "operator_note": None,
            "completed_at": None,
            "created_at": "2026-07-13T09:50:00Z",
            "updated_at": "2026-07-13T09:50:00Z",
        }


@pytest.fixture
def fake_http() -> Iterator[FakeSmokeAPI]:
    fake = FakeSmokeAPI()
    fake.start()
    try:
        yield fake
    finally:
        fake.close()


def test_smoke_driver_runs_complete_fake_workflow(
    fake_http: FakeSmokeAPI,
    tmp_path: Path,
) -> None:
    result = SmokeDriver(
        base_url=fake_http.base_url,
        output_dir=tmp_path,
        poll_interval_seconds=0,
    ).run()

    assert result.steps == STEPS
    assert result.failed == []
    assert result.report_path.exists()

    report_text = result.report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert re.fullmatch(r"smoke-\d{8}T\d{12}Z-[0-9a-f]{8}", report["run_id"])
    assert report["status"] == "succeeded"
    assert report["timeout_seconds"] == 300
    assert [step["name"] for step in report["steps"]] == STEPS
    assert all(step["status"] == "succeeded" for step in report["steps"])
    assert all(isinstance(step["duration_ms"], int) for step in report["steps"])
    recorded_invariants = {invariant for step in report["steps"] for invariant in step["invariants"]}
    assert {
        "new_post_only_route_activation",
        "bounded_backfill_validation",
        "album_preservation",
        "research_citations",
        "four_platform_payloads",
        "edit_invalidates_approval",
        "exact_reapproval",
        "duplicate_publish_prevention",
        "export_manifest_checksums",
        "export_download_bytes_verified",
        "manual_publication_plan",
        "manual_checklist_completed",
        "global_pause_override",
        "pause_sensitive_job_held",
        "pause_sensitive_job_resumed",
        "subject_history",
        "route_history",
        "pause_history",
        "history_secret_absence",
        "runtime_diagnostics",
    }.issubset(recorded_invariants)
    assert SECRET_CANARY not in report_text
    assert "secret_ref" not in report_text

    polled_jobs = {
        fake_http.ids[key]
        for key in (
            "activation_job",
            "destination_job",
            "manual_job",
            "research_job",
            "generation_job",
            "generation_child_job",
            "dry_run_job",
            "export_job",
            "backfill_job",
        )
    }
    assert fake_http.job_reads == {job_id: 2 for job_id in polled_jobs}

    non_poll_sequence = [
        (request["method"], request["path"])
        for request in fake_http.requests
        if not str(request["path"]).startswith("/jobs/")
    ]
    assert non_poll_sequence == [
        ("GET", "/health/live"),
        ("GET", "/automation-control"),
        ("PATCH", "/automation-control"),
        ("POST", "/brand-profiles"),
        ("POST", "/llm-providers"),
        ("POST", "/telegram/sources"),
        ("POST", "/telegram/destinations"),
        ("POST", f"/telegram/destinations/{fake_http.ids['destination']}/enable"),
        ("GET", "/telegram/automations/options"),
        ("GET", "/telegram/automations/options"),
        ("POST", "/telegram/automations"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/activate"),
        ("GET", f"/telegram/automations/{fake_http.ids['route']}"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/backfill"),
        ("POST", "/stories/manual"),
        ("GET", f"/stories/{fake_http.ids['story']}"),
        ("GET", f"/stories/{fake_http.ids['story']}/evidence"),
        ("POST", f"/stories/{fake_http.ids['story']}/research-runs"),
        ("GET", f"/research-runs/{fake_http.ids['research_run']}"),
        ("GET", f"/stories/{fake_http.ids['story']}/revisions"),
        ("POST", f"/stories/{fake_http.ids['story']}/content-packs"),
        ("GET", f"/content-packs/{fake_http.ids['pack']}"),
        (
            "POST",
            f"/platform-variant-revisions/{fake_http.ids['telegram_revision']}/approve",
        ),
        (
            "POST",
            f"/platform-variants/{fake_http.ids['telegram_variant']}/revisions",
        ),
        (
            "POST",
            f"/platform-variant-revisions/{fake_http.ids['edited_revision']}/approve",
        ),
        (
            "POST",
            f"/platform-variant-revisions/{fake_http.ids['edited_revision']}/approve",
        ),
        (
            "POST",
            f"/platform-variant-revisions/{fake_http.ids['instagram_revision']}/approve",
        ),
        ("POST", f"/platform-variant-revisions/{fake_http.ids['x_revision']}/approve"),
        ("POST", f"/platform-variant-revisions/{fake_http.ids['blog_revision']}/approve"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/dry-run"),
        ("GET", f"/telegram/automations/{fake_http.ids['route']}/dispatches"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/dry-run"),
        ("GET", f"/telegram/automations/{fake_http.ids['route']}/dispatches"),
        ("POST", f"/content-packs/{fake_http.ids['pack']}/exports"),
        ("GET", f"/exports/{fake_http.ids['export_job']}"),
        *[
            (
                "GET",
                f"/exports/{fake_http.ids['export_job']}/download/{file_name}",
            )
            for file_name in fake_http._export_downloads()
        ],
        ("POST", "/manual-publication-plans"),
        (
            "GET",
            f"/platform-variant-revisions/{fake_http.ids['instagram_revision']}/manual-publication-plan",
        ),
        ("PATCH", f"/manual-publication-plans/{fake_http.ids['plan']}/checklist"),
        ("PATCH", "/automation-control"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/resume"),
        ("GET", "/automation-control"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/backfill"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/pause"),
        ("POST", f"/telegram/automations/{fake_http.ids['route']}/resume"),
        ("PATCH", "/automation-control"),
        ("GET", "/operations/history"),
        ("GET", "/operations/history"),
        ("GET", "/operations/history"),
        ("GET", "/operations/diagnostics"),
        ("PATCH", "/automation-control"),
    ]

    mutations = [request for request in fake_http.requests if request["method"] in {"POST", "PATCH"}]
    assert all(str(request["headers"].get("Idempotency-Key", "")).startswith(report["run_id"]) for request in mutations)
    destination_request = next(request for request in mutations if request["path"] == "/telegram/destinations")
    assert destination_request["body"]["target"].startswith("@newscraft_smoke_")
    assert destination_request["body"]["bot_token"].startswith("123456:deterministic-smoke-token-")
    assert "secret_ref" not in destination_request["body"]
    source_request = next(request for request in mutations if request["path"] == "/telegram/sources")
    assert source_request["body"]["channel_ref"] == "example_channel"
    assert source_request["body"]["access_mode"] == "public_html"
    generation_request = next(
        request for request in mutations if request["path"] == f"/stories/{fake_http.ids['story']}/content-packs"
    )
    assert generation_request["body"]["platforms"] == ["telegram", "instagram", "x", "blog"]
    export_request = next(
        request for request in mutations if request["path"] == f"/content-packs/{fake_http.ids['pack']}/exports"
    )
    assert export_request["body"]["formats"] == ["json", "markdown", "html", "zip"]
    checklist_request = next(request for request in mutations if request["path"].endswith("/checklist"))
    assert all(checklist_request["body"]["checklist_state"].values())
    history_requests = [request for request in fake_http.requests if request["path"] == "/operations/history"]
    assert [request["query"] for request in history_requests] == [
        {
            "subject_type": ["story"],
            "subject_id": [fake_http.ids["story"]],
            "limit": ["50"],
        },
        {
            "subject_type": ["automation_route"],
            "subject_id": [fake_http.ids["route"]],
            "limit": ["50"],
        },
        {"category": ["pause"], "limit": ["50"]},
    ]
    control_mutations = [request["body"] for request in mutations if request["path"] == "/automation-control"]
    assert control_mutations[0] == {"global_pause": False, "dry_run": True}
    assert control_mutations[-1] == {"global_pause": False, "dry_run": False}
    assert fake_http.control["global_pause"] is False
    assert fake_http.control["dry_run"] is False
    assert all("Authorization" not in request["headers"] for request in fake_http.requests)


def test_smoke_cli_stops_on_first_invariant_failure_and_writes_safe_report(
    fake_http: FakeSmokeAPI,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_http.research_citations = False

    exit_code = main(
        [
            "--base-url",
            fake_http.base_url,
            "--provider",
            "fake",
            "--telegram-mode",
            "dry-run",
            "--output-dir",
            str(tmp_path),
        ],
        poll_interval_seconds=0,
    )

    assert exit_code == 1
    reports = list(tmp_path.glob("smoke-*.json"))
    assert len(reports) == 1
    report_text = reports[0].read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["status"] == "failed"
    assert report["failed"] == ["research"]
    assert [step["name"] for step in report["steps"]] == STEPS[:5]
    assert report["steps"][-1]["status"] == "failed"
    assert SECRET_CANARY not in report_text
    assert fake_http.control["global_pause"] is False
    assert fake_http.control["dry_run"] is False
    assert not any(
        request["path"] == f"/stories/{fake_http.ids['story']}/content-packs" for request in fake_http.requests
    )
    output = capsys.readouterr()
    assert "research" in output.err
    assert SECRET_CANARY not in output.err
