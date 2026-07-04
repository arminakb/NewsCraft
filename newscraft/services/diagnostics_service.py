class DiagnosticsService:
    def source_diagnostics(self):
        # ponytail: no network diagnostics here; call legacy diagnostics from an ops job when needed.
        return {"status": "ok", "checks": []}
