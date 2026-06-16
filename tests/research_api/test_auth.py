"""Token lifecycle: retrieval, refresh, and failure modes."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from tiktok_metadata_kit.research_api import (
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIClient,
)
from tiktok_metadata_kit.research_api import config as research_config

from .conftest import DEFAULT_TOKEN_RESPONSE, MockHandler


class TestTokenRetrieval:
    def test_token_fetched_on_construction(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response(DEFAULT_TOKEN_RESPONSE)
        client = make_client()

        assert client.access_token == "test-token"
        assert client.token_expires_at is not None
        assert len(mock_handler.requests) == 1
        token_req = mock_handler.requests[0]
        assert str(token_req.url) == ResearchAPIClient.ACCESS_TOKEN_URL
        assert token_req.method == "POST"

    def test_token_request_sends_client_credentials(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response(DEFAULT_TOKEN_RESPONSE)
        make_client(api_key="my-key", api_secret="my-secret")

        body = mock_handler.requests[0].content.decode()
        assert "client_key=my-key" in body
        assert "client_secret=my-secret" in body
        assert "grant_type=client_credentials" in body

    def test_expires_at_uses_response_expires_in(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response({"access_token": "tok", "expires_in": 60})
        before = datetime.now(tz=UTC)
        client = make_client()
        after = datetime.now(tz=UTC)

        assert client.token_expires_at is not None
        assert before + timedelta(seconds=60) <= client.token_expires_at
        assert client.token_expires_at <= after + timedelta(seconds=60)

    def test_expires_at_defaults_when_response_omits_expires_in(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response({"access_token": "tok"})
        before = datetime.now(tz=UTC)
        client = make_client()

        assert client.token_expires_at is not None
        expected = before + timedelta(
            seconds=research_config.DEFAULT_REFRESH_TOKEN_EXP_TIME,
        )
        # Allow a couple seconds of slack to avoid flakiness.
        assert abs((client.token_expires_at - expected).total_seconds()) < 5


class TestTokenRetrievalFailures:
    def test_non_200_response_raises(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response("bad request", status=400)
        with pytest.raises(ResearchAPIAccessTokenRetrievalError, match="400"):
            make_client()

    def test_api_error_response_raises(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response(
            {"error": "invalid_client", "error_description": "bad credentials"},
        )
        with pytest.raises(
            ResearchAPIAccessTokenRetrievalError,
            match="invalid_client",
        ):
            make_client()

    def test_malformed_json_raises_chained(
        self,
        mock_handler: MockHandler,
        make_client: Callable[..., ResearchAPIClient],
    ) -> None:
        mock_handler.add_response(
            "not json at all", headers={"Content-Type": "text/plain"}
        )
        with pytest.raises(ResearchAPIAccessTokenRetrievalError) as exc_info:
            make_client()
        assert exc_info.value.__cause__ is not None


class TestTokenRefresh:
    def test_get_access_token_refreshes_when_expiring_soon(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Force expiry within the 5-minute proactive-refresh window.
        client.token_expires_at = datetime.now(tz=UTC) + timedelta(minutes=1)
        mock_handler.add_response({"access_token": "refreshed", "expires_in": 7200})

        token = client.get_access_token()

        assert token == "refreshed"
        # Original token call + the refresh call.
        assert len(mock_handler.requests) == 2

    def test_get_access_token_does_not_refresh_when_fresh(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Token is fresh from the fixture (~2h ahead). No further requests expected.
        token = client.get_access_token()

        assert token == "test-token"
        assert len(mock_handler.requests) == 1

    def test_refresh_failure_during_query_propagates(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Disable retries on this instance — the retry mechanism is exercised
        # in test_retry.py; here we only care that token-refresh failure
        # surfaces as the right exception type.
        client.MAX_RETRIES = 0
        client.token_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        mock_handler.add_response("server error", status=500)

        with pytest.raises(ResearchAPIAccessTokenRetrievalError):
            client.get_access_token()
