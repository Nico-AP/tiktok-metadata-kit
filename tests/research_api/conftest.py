"""Shared fixtures for research_api tests."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tiktok_metadata_kit.research_api import ResearchAPIClient

DEFAULT_TOKEN_RESPONSE = {"access_token": "test-token", "expires_in": 7200}


class MockHandler:
    """Programmable httpx.MockTransport handler.

    Tests queue responses via :meth:`add_response`; the handler returns them
    in FIFO order. Each handled request is recorded in :attr:`requests` for
    later assertion.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def add_response(
        self,
        body: dict[str, Any] | str | None = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue a response. ``body`` is JSON-encoded if dict, raw otherwise."""
        if isinstance(body, dict):
            self.responses.append(
                httpx.Response(status_code=status, json=body, headers=headers),
            )
        else:
            self.responses.append(
                httpx.Response(
                    status_code=status,
                    text=body or "",
                    headers=headers,
                ),
            )

    def add_exception(self, exc: Exception) -> None:
        """Queue a transport-level exception for the next request."""
        self.responses.append(exc)  # type: ignore[arg-type]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            msg = (
                f"MockHandler received unexpected request: "
                f"{request.method} {request.url}"
            )
            raise RuntimeError(msg)
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


@pytest.fixture
def mock_handler() -> MockHandler:
    return MockHandler()


@pytest.fixture
def make_client(mock_handler: MockHandler) -> Callable[..., ResearchAPIClient]:
    """Factory for constructing clients backed by ``mock_handler``.

    Tests typically queue a token response (or use the ``client`` fixture
    which does it automatically) and then call this factory.
    """

    def _factory(
        api_key: str = "test-key",
        api_secret: str = "test-secret",  # noqa: S107
        **kwargs: Any,  # noqa: ANN401
    ) -> ResearchAPIClient:
        return ResearchAPIClient(
            api_key,
            api_secret,
            transport=httpx.MockTransport(mock_handler),
            **kwargs,
        )

    return _factory


@pytest.fixture
def client(
    mock_handler: MockHandler,
    make_client: Callable[..., ResearchAPIClient],
) -> ResearchAPIClient:
    """Pre-authenticated client (consumes the first response slot for the token)."""
    mock_handler.add_response(DEFAULT_TOKEN_RESPONSE)
    return make_client()
