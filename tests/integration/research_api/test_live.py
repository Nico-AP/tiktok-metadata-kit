"""Smoke tests against the live TikTok Research API.

Run with ``pytest -m integration``. Skipped without credentials in the env;
see ``conftest.py``.
"""

import pytest

from tiktok_metadata_kit.research_api import (
    PageOptions,
    ResearchAPIClient,
)

pytestmark = pytest.mark.integration


def test_token_can_be_obtained(live_client: ResearchAPIClient) -> None:
    """The client successfully obtains an access token on construction."""
    assert live_client.access_token
    assert live_client.token_expires_at is not None


def test_query_videos_returns_well_formed_response(
    live_client: ResearchAPIClient,
) -> None:
    """A minimal query returns the expected top-level shape.

    Uses ``max_count=1`` to minimize quota impact.
    """
    response = live_client.query_videos(
        # Public-test video id; replace with one you know exists.
        ["6584979523391982853"],
        PageOptions(max_count=1),
    )
    assert "data" in response
    assert "error" in response
    # The query may legitimately return zero videos — we only assert shape,
    # not contents.
    assert isinstance(response["data"].get("videos", []), list)
