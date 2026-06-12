import time
from collections.abc import Generator
from typing import Any, TypedDict

from .client import TikTokClient
from .config import BASE_URLS, RATE_LIMIT_DELAY
from .parsers import TikTokParser


class VideoScrapingSuccess(TypedDict):
    success: bool  # Always True
    data: dict[str, Any]
    video_id: str


class VideoScrapingError(TypedDict):
    success: bool  # Always False
    error: str
    video_id: str


class UserScrapingSuccess(TypedDict):
    success: bool  # Always True
    data: dict[str, Any]
    username: str


class UserScrapingError(TypedDict):
    success: bool  # Always False
    error: str
    username: str


VideoScrapingResult = VideoScrapingSuccess | VideoScrapingError
UserScrapingResult = UserScrapingSuccess | UserScrapingError


class TikTokScraper:
    """Scraper for extracting TikTok video metadata from tiktok.com.

    This scraper orchestrates the video metadata extraction from TikTok
    by coordinating HTTP requests, HTML parsing, and data extraction.
    It handles both single video and batch processing with built-in rate limiting
    and error handling.

    Attributes:
        client (TikTokClient): HTTP client for making requests to TikTok
        parser (TikTokParser): Parser class for extracting data from responses
        rate_delay (float): Delay in seconds between requests for rate limiting

    Examples:
        >>> scraper = TikTokScraper(rate_delay=1.0)
        >>>
        >>> # Process videos with error handling
        >>> for result in scraper.scrape_video_list(["123", "456"]):
        ...     if result["success"]:
        ...         process_video(result["data"])
        ...     else:
        ...         print(f"Failed {result['video_id']}: {result['error']}")
    """

    def __init__(self, rate_delay: float = RATE_LIMIT_DELAY):
        self.client = TikTokClient()
        self.parser = TikTokParser
        self.rate_delay = rate_delay

    def scrape_video_list(
        self,
        video_ids: list[str],
    ) -> Generator[VideoScrapingResult, None, None]:
        """Generator that yields video scraping results with error handling.

        Args:
            video_ids: List of video IDs to scrape.

        Yields:
            Either success with data or error with message.

        Examples:
            >>> for result in scraper.scrape_video_list(["123", "456"]):
            ...     if result["success"]:
            ...         process_video(result["data"])
            ...     else:
            ...         print(f"Failed {result['video_id']}: {result['error']}")
        """
        for i, video_id in enumerate(video_ids):
            try:
                video_data = self.scrape_video(video_id)
                yield VideoScrapingSuccess(
                    success=True,
                    data=video_data,
                    video_id=video_id,
                )
            except Exception as e:  # noqa: BLE001
                yield VideoScrapingError(success=False, error=str(e), video_id=video_id)

            if self.rate_delay and i < len(video_ids) - 1:
                time.sleep(self.rate_delay)

    def scrape_video(self, video_id: str) -> dict[str, Any]:
        """Scrape a single video.

        Args:
            video_id: ID of the video to scrape.

        Returns:
            The extracted video data.

        Raises:
            TikTokClientGetFailed: Raised when GET request to TikTok did not
                return status ok.
            TikTokMissingRehydrationData: When rehydration data script not found
                in response text.
            TikTokRehydrationDataAttributeError: When rehydration data does not
                have expected attributes.
            TikTokDataExtractionError: When TikTok hydration data structure is
                unexpected or invalid.
        """
        url = self.get_video_url(video_id)
        response = self.client.get(url)
        rehydration_data = self.parser.load_rehydration_data(response.text)
        return self.parser.extract_video_data(rehydration_data)

    def scrape_user_list(
        self,
        usernames: list[str],
    ) -> Generator[UserScrapingResult, None, None]:
        """Generator that yields user scraping results with error handling.

        Args:
            usernames: List of usernames to scrape.

        Yields:
            Either success with data or error with message.

        Examples:
            >>> for result in scraper.scrape_user_list(["namea", "nameB"]):
            ...     if result["success"]:
            ...         # do something
            ...         pass
            ...     else:
            ...         print(f"Failed {result['video_id']}: {result['error']}")
        """
        for i, username in enumerate(usernames):
            try:
                user_data = self.scrape_user(username)
                yield UserScrapingSuccess(
                    success=True,
                    data=user_data,
                    username=username,
                )
            except Exception as e:  # noqa: BLE001
                yield UserScrapingError(success=False, error=str(e), username=username)

            if self.rate_delay and i < len(username) - 1:
                time.sleep(self.rate_delay)

    def scrape_user(self, username: str) -> dict[str, Any]:
        """Scrape a single user.

        Args:
            username: Unique username of the user to scrape.

        Returns:
            The extracted user data.

        Raises:
            TikTokClientGetFailed: Raised when GET request to TikTok did not
                return status ok.
            TikTokMissingRehydrationData: When rehydration data script not found
                in response text.
            TikTokRehydrationDataAttributeError: When rehydration data does not
                have expected attributes.
            TikTokDataExtractionError: When TikTok hydration data structure is
                unexpected or invalid.
        """
        url = self.get_video_url(username)
        response = self.client.get(url)
        rehydration_data = self.parser.load_rehydration_data(response.text)
        return self.parser.extract_user_data(rehydration_data)

    @staticmethod
    def get_video_url(video_id: str) -> str:
        """Construct video url.

        Args:
            video_id: Video id.

        Returns:
            The generic url pointing to the video.
        """
        return BASE_URLS["video"].replace("{id}", str(video_id))

    @staticmethod
    def get_user_url(user_id: str) -> str:
        """Construct user url.

        Args:
            user_id: UserVideo id.

        Returns:
            The generic url pointing to the user page.
        """
        return BASE_URLS["user"].replace("{username}", str(user_id))
