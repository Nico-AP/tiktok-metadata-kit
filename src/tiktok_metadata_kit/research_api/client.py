import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from . import config
from .exceptions import ResearchAPIAccessTokenRetrievalError, ResearchAPIRequestError

logger = logging.getLogger(__name__)


class ResearchAPIClient:
    """Client for interacting with TikTok's Research API.

    This client handles authentication, request formatting, and querying
    TikTok's Research API. It automatically manages access token lifecycle,
    including proactive refresh to prevent expiration during long-running operations.

    The client supports querying videos by ID and retrieving user-posted content
    with automatic pagination handling. All requests include comprehensive error
    handling and logging for debugging and monitoring.

    Attributes:
        ACCESS_TOKEN_URL (str): Endpoint for OAuth token retrieval
        VIDEO_QUERY_URL (str): Endpoint for video metadata queries
        USER_QUERY_URL (str): Endpoint for user information queries

    Examples:
        >>> client = ResearchAPIClient("my-api-key", "my-api-secret")
        >>> videos = client.query_videos(["7123456789", "7987654321"])
        >>> user_videos = client.query_user_videos(["username1", "username2"])

    Raises:
        AttributeError: If API credentials are not configured in settings
        ResearchAPIAccessTokenRetrievalFailed: If token retrieval fails
        ResearchAPIRequestError: If API requests fail
    """

    ACCESS_TOKEN_URL = config.ACCESS_TOKEN_URL
    VIDEO_QUERY_URL = config.VIDEO_QUERY_URL
    USER_QUERY_URL = config.USER_QUERY_URL

    def __init__(self, api_key: str, api_secret: str) -> None:
        self.key = api_key
        self.secret = api_secret

        self.access_token = None
        self.token_expires_at = None
        self._http_client = httpx.Client(timeout=config.DEFAULT_POST_TIMEOUT)
        self._refresh_access_token()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http_client.close()

    def __enter__(self) -> "ResearchAPIClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _refresh_access_token(self) -> None:
        """Retrieves and stores a new access token from TikTok.

        Updates both the access_token and token_expires_at attributes.
        Tokens typically expire after 2 hours (7200 seconds).
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        payload = {
            "client_key": self.key,
            "client_secret": self.secret,
            "grant_type": "client_credentials",
        }

        response = self._http_client.post(
            self.ACCESS_TOKEN_URL,
            headers=headers,
            data=payload,
        )

        if response.status_code != httpx.codes.OK:
            e = (
                "Error getting access token for Research API. "
                f"(response status: {response.status_code})"
            )
            logger.error(e)
            raise ResearchAPIAccessTokenRetrievalError(e)

        data = response.json()

        if "error" in data:
            e = f"{data['error']}: {data.get('error_description')}"
            logger.error(e)
            raise ResearchAPIAccessTokenRetrievalError(e)

        self.access_token = data["access_token"]
        expires_in = data.get("expires_in", config.DEFAULT_REFRESH_TOKEN_EXP_TIME)
        self.token_expires_at = datetime.now(tz=UTC) + timedelta(seconds=expires_in)

        logger.info("Access token refreshed, expires at %s", self.token_expires_at)

    def _ensure_valid_token(self) -> None:
        """Ensures the access token is valid, refreshing if necessary.

        Checks if the token will expire within the next 5 minutes and
        refreshes it proactively to avoid request failures.
        """
        if self.token_expires_at is None or self.token_expires_at <= datetime.now(
            tz=UTC
        ) + timedelta(minutes=5):
            logger.info("Access token expired or expiring soon, refreshing...")
            self._refresh_access_token()

    def get_access_token(self) -> str:
        """Retrieves the current access token, refreshing if necessary.

        Returns:
            Valid access token
        """
        self._ensure_valid_token()
        return self.access_token

    def query_user_videos(self, user_ids: list[str], **kwargs) -> dict[str, Any]:
        """Retrieve videos posted by specific TikTok users via Research API.

        Args:
            user_ids: List of TikTok usernames to query.
            **kwargs: Additional parameters passed to make_query() including:
                start_date, end_date, max_count, cursor, search_id, is_random.

        Returns:
            API response containing retrieved video data and pagination info.

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "username",
                    "field_values": user_ids,
                },
            ],
        }
        return self._make_query(query, **kwargs)

    def query_videos(self, video_ids: list[str], **kwargs) -> dict[str, Any]:
        """Retrieve metadata for specific TikTok videos via Research API.

        Args:
            video_ids: List of TikTok video IDs to query.
            **kwargs: Additional parameters passed to make_query() including:
                start_date, end_date, max_count, cursor, search_id, is_random.

        Returns:
            API response containing video data and pagination info.

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        query = {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "video_id",
                    "field_values": video_ids,
                },
            ],
        }
        return self._make_query(query, **kwargs)

    def _make_query(self, query: dict[str, Any], **kwargs) -> dict[str, Any]:
        """Execute a query against the TikTok Research API.

        Builds the request URL, constructs the query body, and sends the request
        with proper authentication headers. Handles both HTTP and API-level errors.

        Args:
            query: The query structure containing filter conditions.
            **kwargs: Additional query parameters passed to get_query_body().

        Returns:
            The API response data.

        Raises:
            ResearchAPIRequestError: If the HTTP request fails (non-200 status)
                or if the API returns an error response.
        """
        url = self._build_url()
        query_body = self._build_query_body(query, **kwargs)
        response = self._http_client.post(
            url,
            headers=self._get_auth_header(),
            data=query_body,
        )

        if response.status_code != httpx.codes.OK:
            msg = (
                f"Invalid response from Research API. "
                f"Response status code: {response.status_code} for "
                f"url '{url}' and query body '{json.dumps(query_body)}'"
            )
            raise ResearchAPIRequestError(msg)

        data = response.json()
        if "error" in data and data["error"].get("code") != "ok":
            msg = (
                f"Error in Research API response: "
                f"{data['error'].get('msg')} ({data['error'].get('code')})"
            )
            raise ResearchAPIRequestError(msg)

        return data

    def _get_auth_header(self) -> dict[str, str]:
        """Returns the authorization header with a valid access token."""
        self._ensure_valid_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _build_query_body(  # noqa: PLR0913
        self,
        query: dict[str, Any],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        max_count: int | None = config.DEFAULT_MAX_RESULTS,
        cursor: str | None = None,
        search_id: str | None = None,
        is_random: bool | None = False,  # noqa: FBT002
    ) -> dict[str, Any]:
        """Constructs the request body for Research API queries.

        Builds the complete query payload including filter conditions, date ranges,
        pagination parameters, and other query options. Handles date formatting
        and provides sensible defaults for optional parameters.

        Args:
            query: Filter conditions (e.g., video IDs, usernames).
            start_date: Query start date. If None, defaults to 30 days before
                end_date (API maximum).
            end_date: Query end date. If None, defaults to three days before
                current date.
            max_count: Maximum results per request (1-100). Default: 100.
            cursor: Pagination cursor for retrieving next page.
            search_id: Search session ID for paginated results.
            is_random: Whether to randomize result order. Default: False.

        Returns:
            Complete request body ready for API submission.

        Note:
            Dates are automatically converted to YYYYMMDD format as required by the API.
            The start_date cannot be more than 30 days before end_date per API limits.
        """
        if end_date is None:
            end_date = datetime.now(tz=UTC).date() - timedelta(days=3)
        else:
            end_date = end_date.date()

        if start_date is None:
            # Start date can be max. 30 days before end_date.
            start_date = end_date - timedelta(days=config.DEFAULT_QUERY_PERIOD)

        if type(start_date) is not date:
            start_date = start_date.date()

        return {
            "query": query,
            "start_date": start_date.isoformat().replace("-", ""),
            "end_date": end_date.isoformat().replace("-", ""),
            "max_count": max_count,
            "cursor": cursor,
            "search_id": search_id,
            "is_random": is_random,
        }

    def _build_url(self, query_fields: list[str] | None = None) -> str:
        """Build request URL.

        Includes all available query fields by default (for an overview, see
        https://developers.tiktok.com/doc/research-api-specs-query-videos#query_parameters)

        Args:
            query_fields: Query fields to include in response.

        Returns:
            The request URL.
        """
        if query_fields is None:
            query_fields = [
                "id",
                "video_description",
                "create_time",
                "region_code",
                "share_count",
                "view_count",
                "like_count",
                "comment_count",
                "music_id",
                "hashtag_names",
                "username",
                "effect_ids",
                "playlist_id",
                "voice_to_text",
                "is_stem_verified",
                "video_duration",
                "hashtag_info_list",
                "sticker_info_list",
                "effect_info_list",
                "video_mention_list",
                "video_label",
                "video_tag",
            ]

        return self.VIDEO_QUERY_URL + "?fields=" + ",".join(query_fields)
