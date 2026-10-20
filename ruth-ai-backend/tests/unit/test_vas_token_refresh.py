"""Token refresh behaviour in VASClient (BL-12 Phase 1).

Two defects are covered:

* the refresh decision derived the token's lifetime as
  ``expires_at - (expires_at - 3600)`` — a constant 3600 regardless of what
  VAS issued — and then compared the *remaining* time against
  ``0.8 * lifetime``, so it refreshed once 20% of the TTL had elapsed rather
  than 80%. With VAS's 3600s tokens that is a refresh every ~12 minutes.
* the refresh itself ran outside any lock, so every concurrent caller started
  its own. VAS rotates refresh tokens, so the rotations revoked each other
  ("Refresh token has been revoked", 27 times in 3h of logs).
"""

import asyncio

import pytest

from app.integrations.vas.client import TOKEN_REFRESH_THRESHOLD, VASClient


def _client() -> VASClient:
    return VASClient(
        base_url="http://vas.invalid",
        client_id="ruth-ai-backend",
        client_secret="secret",
    )


class TestTokenFreshness:
    """_token_is_fresh uses the real TTL and the right side of the threshold."""

    def test_fresh_just_after_issue(self):
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 3600.0
        c._token_expires_at = time.time() + 3600
        assert c._token_is_fresh() is True

    def test_still_fresh_at_half_life(self):
        """The old code refreshed here; 50% elapsed is well inside the window."""
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 3600.0
        c._token_expires_at = time.time() + 1800
        assert c._token_is_fresh() is True

    def test_stale_past_threshold(self):
        """Refresh only once (1 - threshold) of the TTL remains."""
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 3600.0
        remaining = 3600 * (1.0 - TOKEN_REFRESH_THRESHOLD) - 1
        c._token_expires_at = time.time() + remaining
        assert c._token_is_fresh() is False

    def test_honours_a_short_ttl(self):
        """A 60s token must use 60s, not the hardcoded 3600."""
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 60.0
        # 30s left of a 60s token: half-life, still fresh.
        c._token_expires_at = time.time() + 30
        assert c._token_is_fresh() is True
        # 5s left of a 60s token: past the 20%-remaining threshold.
        c._token_expires_at = time.time() + 5
        assert c._token_is_fresh() is False

    def test_no_token_is_never_fresh(self):
        c = _client()
        c._access_token = None
        c._token_lifetime = 3600.0
        assert c._token_is_fresh() is False

    def test_unknown_lifetime_is_never_fresh(self):
        """Before the first successful auth, lifetime is 0: must not be trusted."""
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 0
        c._token_expires_at = time.time() + 3600
        assert c._token_is_fresh() is False


class TestRefreshSerialisation:
    async def test_concurrent_callers_refresh_once(self):
        """20 concurrent fetches must produce exactly one refresh."""
        c = _client()
        c._access_token = "old"
        c._refresh_token = "r"
        c._token_lifetime = 3600.0
        c._token_expires_at = 0  # expired, so a refresh is due
        calls = []

        async def fake_refresh():
            calls.append(1)
            await asyncio.sleep(0.01)  # a real round trip
            async with c._token_lock:
                c._access_token = "new"
                c._token_lifetime = 3600.0
                import time

                c._token_expires_at = time.time() + 3600

        c._refresh_access_token = fake_refresh

        tokens = await asyncio.gather(*(c._ensure_valid_token() for _ in range(20)))

        assert len(calls) == 1, f"expected one refresh, got {len(calls)}"
        assert set(tokens) == {"new"}

    async def test_fresh_token_needs_no_refresh(self):
        import time

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 3600.0
        c._token_expires_at = time.time() + 3600
        calls = []

        async def fake_refresh():
            calls.append(1)

        c._refresh_access_token = fake_refresh

        assert await c._ensure_valid_token() == "tok"
        assert calls == []

    async def test_force_refresh_skips_if_another_caller_already_rotated(self):
        """After a 401, a caller holding an already-replaced token reuses the new one."""
        c = _client()
        c._access_token = "new"  # someone else already rotated
        c._token_lifetime = 3600.0
        calls = []

        async def fake_refresh():
            calls.append(1)

        c._refresh_access_token = fake_refresh

        got = await c._force_refresh_token("stale")

        assert got == "new"
        assert calls == [], "should not rotate again"

    async def test_force_refresh_rotates_once_for_concurrent_401s(self):
        c = _client()
        c._access_token = "stale"
        c._refresh_token = "r"
        c._token_lifetime = 3600.0
        calls = []

        async def fake_refresh():
            calls.append(1)
            await asyncio.sleep(0.01)
            async with c._token_lock:
                c._access_token = "new"

        c._refresh_access_token = fake_refresh

        tokens = await asyncio.gather(
            *(c._force_refresh_token("stale") for _ in range(10))
        )

        assert len(calls) == 1
        assert set(tokens) == {"new"}


class TestFrameFetchTimeout:
    async def test_frame_fetch_uses_the_short_timeout(self):
        """The frame fetch must not inherit the 30s default."""
        from app.integrations.vas.client import FRAME_FETCH_TIMEOUT

        assert 1.0 <= FRAME_FETCH_TIMEOUT <= 5.0

        c = _client()
        c._access_token = "tok"
        c._token_lifetime = 3600.0
        import time

        c._token_expires_at = time.time() + 3600
        seen = {}

        class FakeResponse:
            is_success = True
            content = b"\xff\xd8jpeg"
            headers = {"X-Frame-Width": "1920", "X-Frame-Height": "1080"}

        class FakeClient:
            async def get(self, path, headers=None, params=None, timeout=None):
                seen["path"] = path
                seen["timeout"] = timeout
                return FakeResponse()

        c._client = FakeClient()

        await c.get_latest_frame("abc", max_age_ms=5000)

        assert seen["timeout"] == FRAME_FETCH_TIMEOUT
        assert seen["path"].endswith("/frame/latest")


@pytest.mark.parametrize("threshold", [TOKEN_REFRESH_THRESHOLD])
def test_threshold_is_a_fraction(threshold):
    assert 0.0 < threshold < 1.0
