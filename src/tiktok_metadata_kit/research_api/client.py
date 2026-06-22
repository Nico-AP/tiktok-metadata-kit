import json
import logging
import random
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Self

import httpx

from . import config
from .exceptions import (
    ResearchAPIAccessTokenInvalidError,
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIError,
    ResearchAPIInternalServerError,
    ResearchAPIInvalidParamsError,
    ResearchAPIRateLimitExceededError,
)

logger = logging.getLogger(__name__)


@dataclass
class QueryVideosOptions:
    """Optional parameters for the query_videos endpoint.

    Args:
        max_count: Videos per page, 1-100. Defaults to 100. Actual results may
            be fewer if videos were deleted or set to private.
        cursor: Resume pagination from this index. Use together with
            ``search_id`` when resuming a previous search.
        search_id: Unique identifier of a cached search result. Use together
            with ``cursor`` when resuming a previous search.
        is_random: If ``True``, returns 1-100 videos in random order.
            If ``False`` (default), returns results by descending video ID.
        fields: Response fields to include. Defaults to client config.
        max_pages: Maximum number of pages to fetch. ``None`` fetches all.

    Note:
        ``search_id`` and ``cursor`` should be used together when resuming
        a previous search.
    """

    max_count: int | None = 100
    cursor: int | None = None
    search_id: str | None = None
    is_random: bool = False
    fields: Sequence[str] = field(default_factory=lambda: config.QUERY_VIDEOS_FIELDS)
    max_pages: int | None = None  # client-side, not sent to API


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header value (seconds or HTTP-date) into seconds."""
    try:
        return float(value)
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return (target - datetime.now(tz=UTC)).total_seconds()


# Mapping TikTok's error code strings to specific exception classes.
# see: https://developers.tiktok.com/doc/tiktok-api-v2-error-handling
_TIKTOK_ERROR_CODE_MAP: dict[str, type[ResearchAPIError]] = {
    "access_token_invalid": ResearchAPIAccessTokenInvalidError,
    "internal_error": ResearchAPIInternalServerError,
    "invalid_params": ResearchAPIInvalidParamsError,
    "rate_limit_exceeded": ResearchAPIRateLimitExceededError,
}


# Fallback mapping for when the response body isn't parseable JSON
# and all we have is the HTTP status code.
_HTTP_STATUS_MAP: dict[int, type[ResearchAPIError]] = {
    400: ResearchAPIInvalidParamsError,
    401: ResearchAPIAccessTokenInvalidError,
    429: ResearchAPIRateLimitExceededError,
    500: ResearchAPIInternalServerError,
}


def _parse_tiktok_error(error: dict[str, Any]) -> tuple[str, str, str]:
    """Extract ``(code, message, log_id)`` from a TikTok error object.

    Falls back to placeholder strings when fields are missing, empty, or
    null. Accepts both the documented ``message`` key and the legacy ``msg``
    spelling — TikTok responses have been seen with either.
    """
    code = error.get("code") or "unknown"
    message = error.get("message") or error.get("msg") or "no message provided"
    log_id = error.get("log_id") or "unavailable"
    return code, message, log_id


class ResearchAPIClient:
    """Client for interacting with TikTok's Research API.

    Handles authentication, request formatting, and querying. Access tokens
    are obtained on construction and refreshed proactively before expiry, so
    callers do not need to manage token lifecycle.

    Transient failures (network errors, HTTP 429, 5xx) are retried with
    exponential backoff and jitter; the server's ``Retry-After`` header is
    honored up to :attr:`MAX_RETRY_AFTER`. Connections are pooled via a
    persistent ``httpx.Client``; use the client as a context manager (or
    call :meth:`close`) to release them.

    Public surface:

    * :meth:`query_videos` — generator yielding individual videos that match
      a raw query dict, across all pages.
    * :meth:`query_videos_pages` — generator yielding raw API pages for the
      same query (with ``data.has_more``, ``data.cursor``, ``data.search_id``
      etc.). Use when you need page metadata for checkpointing.
    * :meth:`query_videos_by_id` / :meth:`query_videos_by_username` /
      :meth:`query_videos_by_hashtag` — convenience wrappers that build the
      corresponding ``IN`` filter and delegate to :meth:`query_videos`.
    * :meth:`query_user_info` — single, non-paginated call to the user-info
      endpoint; returns the raw API response dict.

    Filter and pagination knobs (``max_count``, ``cursor``, ``search_id``,
    ``is_random``, ``fields``, ``max_pages``) are passed via
    :class:`QueryVideosOptions`. Pagination — cursor following, token
    refresh, retries — happens transparently inside the generators.

    Attributes:
        ACCESS_TOKEN_URL (str): OAuth token endpoint.
        QUERY_VIDEOS_URL (str): Video metadata query endpoint.
        QUERY_USER_INFO_URL (str): User info query endpoint.
        MAX_RETRIES (int): Max retries per request on transient errors.
        BACKOFF_CAP (float): Per-sleep ceiling for computed backoff.
        MAX_RETRY_AFTER (float): Ceiling for server-supplied ``Retry-After``.

    Examples:
        Stream all videos for given users::

            with ResearchAPIClient("key", "secret") as client:
                for video in client.query_videos_by_username(["alice", "bob"]):
                    process(video)

        Stream videos by ID with a per-call field selection and a page cap::

            opts = QueryVideosOptions(
                fields=["id", "view_count"],
                max_count=50,
                max_pages=10,
            )
            for video in client.query_videos_by_id([1234, 5678], options=opts):
                ...

        Page-level iteration for checkpointing::

            for page in client.query_videos_pages({"and": [...]}):
                save_progress(page["data"].get("cursor"),
                              page["data"].get("search_id"))
                for video in page["data"]["videos"]:
                    process(video)

        Resume from a saved checkpoint::

            opts = QueryVideosOptions(cursor=saved_cursor, search_id=saved_search_id)
            for page in client.query_videos_pages({"and": [...]}, options=opts):
                ...

        Look up user metadata (single response)::

            info = client.query_user_info("alice")
            print(info["data"]["follower_count"])

    Raises:
        ResearchAPIAccessTokenRetrievalError: If token retrieval fails.
        ResearchAPIError: If a query request fails or the API
            returns an error response.
    """

    ACCESS_TOKEN_URL = config.ACCESS_TOKEN_URL
    QUERY_VIDEOS_URL = config.QUERY_VIDEOS_URL
    QUERY_USER_INFO_URL = config.QUERY_USER_INFO_URL

    # Retry/backoff configuration
    MAX_RETRIES = config.DEFAULT_MAX_RETRIES
    BACKOFF_CAP = config.DEFAULT_BACKOFF_CAP
    MAX_RETRY_AFTER = config.MAX_RETRY_AFTER

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Construct a client.

        Args:
            api_key: TikTok Research API client key.
            api_secret: TikTok Research API client secret.
            transport: Custom ``httpx`` transport. ``None`` uses the default
                network transport. Primarily intended for tests, which can
                inject :class:`httpx.MockTransport` to drive the client
                without network access.
        """
        self.key = api_key
        self.secret = api_secret

        self.access_token = None
        self.token_expires_at = None
        self._http_client = httpx.Client(
            timeout=config.DEFAULT_POST_TIMEOUT,
            transport=transport,
        )
        self._refresh_access_token()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post_with_retry(self, url: str, **kwargs) -> httpx.Response:
        """POST with exponential backoff on transient errors.

        Retries on transport errors and on retryable status codes (429, 5xx).
        Honors ``Retry-After`` (seconds or HTTP-date) when present.
        """
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self._http_client.post(url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                response = None
            else:
                if response.status_code not in config.RETRYABLE_STATUS_CODES:
                    return response

            if attempt == self.MAX_RETRIES:
                break

            delay = self._compute_backoff(attempt, response)
            logger.warning(
                "POST %s failed (attempt %d/%d); retrying in %.2fs",
                url,
                attempt + 1,
                self.MAX_RETRIES + 1,
                delay,
            )
            time.sleep(delay)

        if response is not None:
            return response
        assert last_exc is not None
        raise last_exc

    def _compute_backoff(self, attempt: int, response: httpx.Response | None) -> float:
        """Return seconds to sleep before the next retry."""
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                requested = _parse_retry_after(retry_after)
                if requested is not None:
                    if requested > self.MAX_RETRY_AFTER:
                        logger.warning(
                            "Server requested Retry-After=%.1fs; clamping to %.1fs",
                            requested,
                            self.MAX_RETRY_AFTER,
                        )
                    return max(0.0, min(requested, self.MAX_RETRY_AFTER))

        backoff = config.DEFAULT_BACKOFF_BASE * (2**attempt)
        jitter = random.uniform(0, config.DEFAULT_BACKOFF_BASE)  # noqa: S311
        return min(backoff + jitter, self.BACKOFF_CAP)

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

        response = self._post_with_retry(
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

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            e = (
                "Malformed JSON in Research API access-token response "
                f"(content-type: {response.headers.get('Content-Type')!r}, "
                f"body[:200]: {response.text[:200]!r})"
            )
            logger.error(e)  # noqa: TRY400
            raise ResearchAPIAccessTokenRetrievalError(e) from exc

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

    def query_videos(
        self,
        query: dict[str, Any],
        start_date: date | None = None,
        end_date: date | None = None,
        options: QueryVideosOptions | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield individual videos matching the given query across all pages.

        Args:
            query: Filter conditions with ``and``, ``or``, and ``not`` keys,
                each a list of condition objects. At least one non-empty key
                is required. See API docs for condition structure.
            start_date: Lower bound of video creation time (UTC). Defaults to today.
            end_date: Upper bound of video creation time (UTC). Defaults to 29 days ago.
                Must be within 30 days of ``start_date``.
            options: Optional pagination and filter settings - see
                ``QueryVideosOptions```

        Raises:
            ResearchAPIError: If the API request fails or returns an error.

        Note:
            ``end_date`` must be within 30 days of ``start_date`` or the API
            will reject the request.
        """
        for page in self.query_videos_pages(query, start_date, end_date, options):
            yield from page.get("data", {}).get("videos", [])

    def query_videos_pages(
        self,
        query: dict[str, Any],
        start_date: date | None = None,
        end_date: date | None = None,
        options: QueryVideosOptions | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield raw API response pages for the query_videos endpoint.

        Args:
            query: Filter conditions with ``and``, ``or``, and ``not`` keys,
                each a list of condition objects. At least one non-empty key
                is required. See API docs for condition structure.
            start_date: Lower bound of video creation time (UTC).
                Defaults to 29 days ago.
            end_date: Upper bound of video creation time (UTC). Defaults to today.
                Must be within 30 days of ``start_date``.
            options: Optional pagination and filter settings - see
                ``QueryVideosOptions```

        Raises:
            ResearchAPIError: If the API request fails or returns an error.

        Note:
            ``end_date`` must be within 30 days of ``start_date`` or the API
            will reject the request.
        """
        end_date = end_date or datetime.now(tz=UTC).date()
        start_date = start_date or datetime.now(tz=UTC).date() - timedelta(days=29)
        options = options or QueryVideosOptions()

        query_body = {
            "query": query,
            "start_date": start_date.isoformat().replace("-", ""),
            "end_date": end_date.isoformat().replace("-", ""),
            "max_count": options.max_count,
            "cursor": options.cursor,
            "search_id": options.search_id,
            "is_random": options.is_random,
        }

        yield from self._iter_pages(
            query_body,
            endpoint_url=self.QUERY_VIDEOS_URL,
            fields=options.fields,
            max_pages=options.max_pages,
        )

    def query_videos_by_id(
        self,
        video_ids: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        options: QueryVideosOptions | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield videos matching the given video IDs.

        Convenience wrapper around ``query_videos`` — see it for full argument docs.

        Args:
            video_ids: TikTok video IDs to retrieve.
            start_date: See ``query_videos``.
            end_date: See ``query_videos``.
            options: See ``QueryVideosOptions``.

        Raises:
            ResearchAPIError: If the API request fails or returns an error.
        """
        yield from self.query_videos(
            self._video_id_query(video_ids), start_date, end_date, options
        )

    def query_videos_by_username(
        self,
        usernames: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        options: QueryVideosOptions | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield videos published by the given users.

        Convenience wrapper around ``query_videos`` — see it for full argument docs.

        Args:
            usernames: Names of users for which to retrieve TikTok videos.
            start_date: See ``query_videos``.
            end_date: See ``query_videos``.
            options: See ``QueryVideosOptions``.

        Raises:
            ResearchAPIError: If the API request fails or returns an error.
        """
        yield from self.query_videos(
            self._username_query(usernames), start_date, end_date, options
        )

    def query_videos_by_hashtag(
        self,
        hashtags: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        options: QueryVideosOptions | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield videos associated with one of the given hashtags.

        Convenience wrapper around ``query_videos`` — see it for full argument docs.

        Args:
            hashtags: Names of hashtags for which to retrieve TikTok videos.
            start_date: See ``query_videos``.
            end_date: See ``query_videos``.
            options: See ``QueryVideosOptions``.

        Raises:
            ResearchAPIError: If the API request fails or returns an error.
        """
        yield from self.query_videos(
            self._hashtag_query(hashtags), start_date, end_date, options
        )

    def query_user_info(self, username: str) -> dict[str, Any]:
        """Yield user infor for the given username.

        Args:
            username: Name of the user for which to query infos.

        Raises:
            ResearchAPIError: If the API request fails or returns an error.
        """
        query_body = {"username": username}
        return self._make_query(
            query_body,
            endpoint_url=self.QUERY_USER_INFO_URL,
            fields=config.QUERY_USER_INFO_FIELDS,
        )

    def _iter_pages(
        self,
        query_body: dict[str, Any],
        endpoint_url: str,
        fields: Sequence[str] | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Generic paginator."""
        pages_yielded = 0
        while True:
            page = self._make_query(
                query_body,
                endpoint_url=endpoint_url,
                fields=fields,
            )
            yield page
            pages_yielded += 1

            if max_pages is not None and pages_yielded >= max_pages:
                return

            data = page.get("data") or {}
            if not data.get("has_more"):
                return

            next_cursor = data.get("cursor")
            if next_cursor is None:
                logger.warning(
                    "Pagination stopped: response reported has_more=True "
                    "but did not include a cursor",
                )
                return

            query_body["cursor"] = next_cursor
            if "search_id" in data:
                query_body["search_id"] = data.get("search_id")

    def _make_query(
        self,
        query_body: dict[str, Any],
        endpoint_url: str,
        fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a query against the TikTok Research API.

        Builds the request URL, cand sends the request with proper
        authentication headers. Handles both HTTP and API-level errors.

        Args:
            query_body: The body of the query.
            endpoint_url: Target endpoint (e.g. :attr:`QUERY_VIDEOS_URL`).
            fields: Response fields.

        Returns:
            The API response data.

        Raises:
            ResearchAPIError: If the HTTP request fails (non-200 status)
                or if the API returns an error response.
        """
        url = self._build_url(endpoint_url, fields)

        response = self._post_with_retry(
            url,
            headers=self._get_auth_header(),
            json=query_body,
        )

        if response.status_code != httpx.codes.OK:
            exc_class: type[ResearchAPIError] = _HTTP_STATUS_MAP.get(
                response.status_code,
                ResearchAPIError,
            )
            try:
                error_body = response.json()
            except json.JSONDecodeError:
                msg = (
                    f"Research API returned HTTP {response.status_code} "
                    f"with non-JSON body "
                    f"(content-type: {response.headers.get('Content-Type')!r}, "
                    f"body[:200]: {response.text[:200]!r}, "
                    f"url: '{url}', query body: '{json.dumps(query_body)}')"
                )
            else:
                code, message, log_id = _parse_tiktok_error(
                    error_body.get("error", {}) if isinstance(error_body, dict) else {},
                )
                exc_class = _TIKTOK_ERROR_CODE_MAP.get(code, exc_class)
                msg = (
                    f"Research API error '{code}': {message} "
                    f"(HTTP {response.status_code}, log_id: {log_id}, "
                    f"url: '{url}', query body: '{json.dumps(query_body)}')"
                )
            raise exc_class(msg)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            msg = (
                "Malformed JSON in Research API HTTP 200 response "
                f"(content-type: {response.headers.get('Content-Type')!r}, "
                f"body[:200]: {response.text[:200]!r})"
            )
            raise ResearchAPIError(msg) from exc

        # A 200 response can still carry an application-level error.
        error = data.get("error", {})
        if error.get("code", "ok") != "ok":
            code, message, log_id = _parse_tiktok_error(error)
            exc_class = _TIKTOK_ERROR_CODE_MAP.get(code, ResearchAPIError)
            msg = (
                f"Research API error '{code}': {message} "
                f"(HTTP 200, log_id: {log_id}, url: '{url}', "
                f"query body: '{json.dumps(query_body)}')"
            )
            raise exc_class(msg)

        return data

    def _get_auth_header(self) -> dict[str, str]:
        """Returns the authorization header with a valid access token."""
        self._ensure_valid_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_url(endpoint_url: str, fields: Sequence[str]) -> str:
        """Build a Research API request URL for the given endpoint.

        Args:
            endpoint_url: Base URL of the target endpoint
                (e.g. :attr:`QUERY_VIDEOS_URL`, :attr:`QUERY_USER_INFO_URL`).
            fields: Response fields to request.

        Returns:
            The fully qualified request URL with ``?fields=`` appended.
        """
        if fields:
            return endpoint_url + "?fields=" + ",".join(fields)
        return endpoint_url

    @staticmethod
    def _video_id_query(video_ids: list[str]) -> dict[str, Any]:
        return {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "video_id",
                    "field_values": video_ids,
                },
            ],
        }

    @staticmethod
    def _username_query(user_ids: list[str]) -> dict[str, Any]:
        return {
            "and": [
                {"operation": "IN", "field_name": "username", "field_values": user_ids},
            ],
        }

    @staticmethod
    def _hashtag_query(hashtag_names: list[str]) -> dict[str, Any]:
        return {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "hashtag_name",
                    "field_values": hashtag_names,
                },
            ],
        }
