# Handoff — NewsCraft (2026-07-19)

## وضعیت فعلی
- شعبه (branch) جاری برای تحویل: `chore/health-docs-and-test-cleanup`
- PR مربوطه: https://github.com/arminakb/NewsCraft/pull/12 (باز، در انتظار review/merge)
- پایه (base): `main` روی origin
- هدف پایتون پروژه: `>=3.14` (توجه: سینتکس `except A, B:` در ۳.۱۴ معتبر است)

## محتوای PR
۱. اصلاح مثال `daily_bundle` در `README.md` (استفاده از سرویس `worker-source-generation` و ولوم `/output`)
۲. هم‌راستایی `backend/tests/test_docker_config.py` با دستور اصلاح‌شده
۳. فرمت‌دهی (`reformat`) در `backend/app/operations/health.py` و `backend/tests/test_telegram_route_handlers.py`
۴. افزودن `docs/production-readiness-audit-2026-07-15.md`
۵. افزودن یادداشت‌های کاری: `TASK.md`، `ACTIVE_TASK.md`، `solutions.md`، `docs/implementation-reports/phase-01-02-final-deployed-verification.md`
۶. افزودن نتیجهٔ smoke-test: `validation/production-readiness-2026-07-14/smoke-results/*.json`

## نکته مهم دربارهٔ کامیت‌ها
این PR علاوه بر تغییرات بالا، **۷ کامیت محلی روی `main`** که قبلاً پوش نشده بودند را نیز شامل می‌شود
(مثلاً: enforcement کردنیال‌های worker-scoped، restart supervision، outbound proxy policy، readiness/operational health).
پیش از merge مطمئن شوید که این ۷ کامیت هم مدنظرتان هست.

## خارج‌شده از PR (به‌صورت عمدی)
- پوشهٔ `.sentry-native/` — دایرکتوری build سیستم، غیرقابل‌خواندن (متعلق به root)

## نحوهٔ اجرای تست
```bash
pytest backend/tests/test_docker_config.py backend/tests/test_telegram_route_handlers.py
```

## گام‌های بعدی پیشنهادی
- بررسی و merge کردن PR #12
- اگر قصد ادامهٔ Phase 10 (Frontend/Backend Contract Drift) را دارید، طبق `solutions.md` و `ACTIVE_TASK.md` پیش بروید
- اطمینان از اینکه ۷ کامیت قدیمیِ `main` آگاهانه وارد تاریخچه می‌شوند
