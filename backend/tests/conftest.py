"""Shared backend test environment."""

import os

# Application routes must distinguish test harness calls from deployed principals.
# Production behavior is exercised with explicit Settings objects in security tests.
os.environ.setdefault("APP_ENV", "test")
