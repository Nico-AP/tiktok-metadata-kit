from typing import Any

import requests

from .config import DEFAULT_HEADERS
from .cookies import TikTokCookiesManager
from .exceptions import TikTokClientGetError


class TikTokClient:
    """Handles HTTP requests with proper headers/session management."""

    def __init__(self):
        self.session = requests.Session()

        # Add default headers to session.
        self.session.headers.update(DEFAULT_HEADERS)

        # Add TikTok cookies to session.
        self.cookie_manager = TikTokCookiesManager()
        cookies = self.cookie_manager.get_or_create_cookies()

        if cookies:
            self.session.cookies.update(cookies)

    def get(self, url: str) -> requests.Response:
        """Send GET request to TikTok and return response.

        Args:
            url: The url to get.

        Returns:
            Response from request.

        Raises:
            TikTokClientGetFailed: If request failed.
        """
        try:
            response = self.session.get(url)
            response.raise_for_status()
        except requests.HTTPError as e:
            msg = f"Request failed: {e}"
            raise TikTokClientGetError(msg) from e

        return response

    def get_json(self, url: str) -> dict[str, Any]:
        """Send GET request to TikTok and return JSON response.

        Args:
            url: The url to get.

        Returns:
            JSON response as dictionary.

        Raises:
            TikTokClientGetFailed: If request failed or response is not valid JSON.
        """
        response = self.get(url)
        try:
            return response.json()
        except requests.JSONDecodeError as e:
            msg = f"Invalid JSON response: {e}"
            raise TikTokClientGetError(msg) from e
