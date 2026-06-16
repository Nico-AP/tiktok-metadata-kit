"""Retry and backoff: status-based retries, Retry-After honoring, transport errors."""

import logging
import time

import httpx
import pytest

from tiktok_metadata_kit.research_api import (
    ResearchAPIClient,
    ResearchAPIRequestError,
)

from .conftest import MockHandler


def _ok_page() -> dict:
    return {"data": {"videos": [], "has_more": False}, "error": {"code": "ok"}}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real backoff delays so the retry tests run in milliseconds."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


class TestRetryOnStatus:
    def test_retries_on_429(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response("rate limited", status=429)
        mock_handler.add_response(_ok_page())

        result = client.query_videos(["1"])

        assert result["error"]["code"] == "ok"
        # Token request + 429 + success.
        assert len(mock_handler.requests) == 3

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_5xx(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        status: int,
    ) -> None:
        mock_handler.add_response("server error", status=status)
        mock_handler.add_response(_ok_page())

        client.query_videos(["1"])

        assert len(mock_handler.requests) == 3

    def test_does_not_retry_on_400(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response("bad", status=400)
        with pytest.raises(ResearchAPIRequestError):
            client.query_videos(["1"])

        # Only token request + the single failing query (no retry).
        assert len(mock_handler.requests) == 2

    def test_gives_up_after_max_retries(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Reduce retries to keep the test fast.
        client.MAX_RETRIES = 2
        for _ in range(3):  # MAX_RETRIES + 1 attempts
            mock_handler.add_response("server error", status=500)

        with pytest.raises(ResearchAPIRequestError):
            client.query_videos(["1"])

        # Token + 3 failed attempts.
        assert len(mock_handler.requests) == 4


class TestRetryAfterHeader:
    def test_honors_retry_after_seconds(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        mock_handler.add_response(
            "rate limited",
            status=429,
            headers={"Retry-After": "7"},
        )
        mock_handler.add_response(_ok_page())

        client.query_videos(["1"])

        assert sleeps == [7.0]

    def test_clamps_retry_after_above_ceiling_and_logs(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        # MAX_RETRY_AFTER defaults to 300. Server asks for 9999.
        mock_handler.add_response(
            "rate limited",
            status=429,
            headers={"Retry-After": "9999"},
        )
        mock_handler.add_response(_ok_page())

        with caplog.at_level(logging.WARNING):
            client.query_videos(["1"])

        assert sleeps == [client.MAX_RETRY_AFTER]
        assert any(
            "Retry-After" in r.message and "clamping" in r.message
            for r in caplog.records
        )

    def test_malformed_retry_after_falls_back_to_backoff(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        mock_handler.add_response(
            "rate limited",
            status=429,
            headers={"Retry-After": "not-a-number"},
        )
        mock_handler.add_response(_ok_page())

        client.query_videos(["1"])

        # Exponential backoff for attempt 0: base * 2^0 + jitter ∈ [1, 2].
        assert len(sleeps) == 1
        assert 1.0 <= sleeps[0] <= 2.0


class TestTransportErrors:
    def test_retries_on_transport_error(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_exception(httpx.ConnectError("boom"))
        mock_handler.add_response(_ok_page())

        client.query_videos(["1"])

        assert len(mock_handler.requests) == 3

    def test_reraises_last_transport_error_after_exhaustion(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        client.MAX_RETRIES = 1
        mock_handler.add_exception(httpx.ConnectError("first"))
        mock_handler.add_exception(httpx.ConnectError("second"))

        with pytest.raises(httpx.ConnectError, match="second"):
            client.query_videos(["1"])
