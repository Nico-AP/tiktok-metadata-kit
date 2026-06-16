"""Fixtures for integration tests against the real TikTok Research API.

These tests hit the live API and require valid credentials in environment
variables. Without them, tests are skipped — not failed.
"""

import os
from collections.abc import Iterator

import pytest

from tiktok_metadata_kit.research_api import ResearchAPIClient

API_KEY_ENV = "TIKTOK_RESEARCH_API_KEY"
API_SECRET_ENV = "TIKTOK_RESEARCH_API_SECRET"


@pytest.fixture
def real_credentials() -> tuple[str, str]:
    """Return (key, secret) from env, or skip the test if either is missing."""
    key = os.environ.get(API_KEY_ENV)
    secret = os.environ.get(API_SECRET_ENV)
    if not (key and secret):
        pytest.skip(
            f"Integration test requires {API_KEY_ENV} and {API_SECRET_ENV} "
            "to be set in the environment.",
        )
    return key, secret


@pytest.fixture
def live_client(real_credentials: tuple[str, str]) -> Iterator[ResearchAPIClient]:
    """A real client that talks to TikTok's Research API."""
    client = ResearchAPIClient(*real_credentials)
    try:
        yield client
    finally:
        client.close()
