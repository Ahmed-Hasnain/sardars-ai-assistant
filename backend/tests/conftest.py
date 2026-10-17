"""Give each API test independent process-local rate state."""

import pytest

from app.api.rate_limits import (
    LOGIN_ACCOUNT_LIMITER, LOGIN_IP_LIMITER, QUESTION_LIMITER, TOOL_LIMITER,
)


@pytest.fixture(autouse=True)
def reset_rate_windows():
    for limiter in (QUESTION_LIMITER, TOOL_LIMITER, LOGIN_IP_LIMITER, LOGIN_ACCOUNT_LIMITER):
        limiter.clear()
    yield
    for limiter in (QUESTION_LIMITER, TOOL_LIMITER, LOGIN_IP_LIMITER, LOGIN_ACCOUNT_LIMITER):
        limiter.clear()
