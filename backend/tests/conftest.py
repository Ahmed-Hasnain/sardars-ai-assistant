"""Give each API test independent process-local rate state."""

import pytest

from app.api.rate_limits import (
    HISTORY_LIMITER, LOGIN_ACCOUNT_LIMITER, LOGIN_IP_LIMITER, QUESTION_LIMITER, TOOL_LIMITER, SITEMAP_LIMITER,
)


@pytest.fixture(autouse=True)
def reset_rate_windows():
    for limiter in (QUESTION_LIMITER, TOOL_LIMITER, HISTORY_LIMITER, LOGIN_IP_LIMITER, LOGIN_ACCOUNT_LIMITER, SITEMAP_LIMITER):
        limiter.clear()
    yield
    for limiter in (QUESTION_LIMITER, TOOL_LIMITER, HISTORY_LIMITER, LOGIN_IP_LIMITER, LOGIN_ACCOUNT_LIMITER, SITEMAP_LIMITER):
        limiter.clear()
