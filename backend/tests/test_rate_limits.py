"""Local request windows, account lockout, and per-user API behavior."""

from app.api.rate_limits import WindowLimiter


def test_window_refills_and_prunes_idle_keys():
    now = [100.0]
    limiter = WindowLimiter(2, 60, max_keys=2)
    limiter.clock = lambda: now[0]
    assert limiter.hit("staff-a") is None
    assert limiter.hit("staff-a") is None
    assert limiter.hit("staff-a") == 60
    now[0] = 130.0
    assert limiter.hit("staff-a") == 30
    assert limiter.hit("staff-b") is None
    assert limiter.hit("staff-c") == 60  # bounded key storage
    now[0] = 191.0
    assert limiter.hit("staff-c") is None  # idle keys are pruned
    assert limiter.hit("staff-a") is None


def test_successful_account_reset_does_not_clear_other_accounts():
    limiter = WindowLimiter(1, 60)
    limiter.clock = lambda: 0.0
    assert limiter.hit("one@test.local") is None
    assert limiter.hit("two@test.local") is None
    limiter.forget("one@test.local")
    assert limiter.hit("one@test.local") is None
    assert limiter.hit("two@test.local") == 60
