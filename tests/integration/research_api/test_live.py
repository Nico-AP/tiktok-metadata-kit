"""Smoke tests against the live TikTok Research API.

Run with ``pytest -m integration``. Skipped without credentials in the env;
see ``conftest.py``.
"""

from datetime import UTC, datetime

import pytest

from tiktok_metadata_kit.research_api import (
    QueryVideosOptions,
    ResearchAPIClient,
)

pytestmark = pytest.mark.integration


def test_token_can_be_obtained(live_client: ResearchAPIClient) -> None:
    """The client successfully obtains an access token on construction."""
    assert live_client.access_token
    assert live_client.token_expires_at is not None


def test_query_videos_by_username_returns_well_formed_videos(
    live_client: ResearchAPIClient,
) -> None:
    """A minimal query yields dicts with the expected shape.

    Uses ``max_count=1`` and ``max_pages=1`` to minimize quota impact.
    """
    videos = list(
        live_client.query_videos_by_username(
            # Public-test video id; replace with one you know exists.
            ["tiktok"],
            options=QueryVideosOptions(max_count=1, max_pages=1),
        )
    )
    # The query may legitimately return zero videos — we only assert shape,
    # not contents.
    assert isinstance(videos, list)
    for video in videos:
        assert isinstance(video, dict)


def test_query_videos_by_id_returns_well_formed_videos(
    live_client: ResearchAPIClient,
) -> None:
    """A minimal query yields dicts with the expected shape.

    Uses ``max_count=1`` and ``max_pages=1`` to minimize quota impact.
    """
    videos = list(
        live_client.query_videos_by_id(
            # Public-test video id; replace with one you know exists.
            ["6584979523391982853"],
            start_date=datetime(2018, 2, 5, tzinfo=UTC).date(),
            end_date=datetime(2018, 2, 10, tzinfo=UTC).date(),
            options=QueryVideosOptions(max_count=1, max_pages=1),
        )
    )
    # The query may legitimately return zero videos — we only assert shape,
    # not contents.
    assert isinstance(videos, list)
    for video in videos:
        assert isinstance(video, dict)


def test_query_videos_by_hashtag_returns_well_formed_videos(
    live_client: ResearchAPIClient,
) -> None:
    """A minimal query yields dicts with the expected shape.

    Uses ``max_count=1`` and ``max_pages=1`` to minimize quota impact.
    """
    videos = list(
        live_client.query_videos_by_hashtag(
            # Public-test video id; replace with one you know exists.
            ["apple"],
            options=QueryVideosOptions(max_count=1, max_pages=1),
        )
    )
    # The query may legitimately return zero videos — we only assert shape,
    # not contents.
    assert isinstance(videos, list)
    for video in videos:
        assert isinstance(video, dict)
