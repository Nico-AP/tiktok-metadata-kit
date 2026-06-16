import json
import logging
import random
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, TypedDict, Unpack

import httpx

from . import config
from .exceptions import ResearchAPIAccessTokenRetrievalError, ResearchAPIRequestError

logger = logging.getLogger(__name__)


class QueryOptions(TypedDict, total=False):
    """Filter options accepted by all video-query methods.

    All keys are optional; omitted values fall back to the defaults in
    :meth:`ResearchAPIClient._build_query_body`.
    """

    # DEV NOTE: Keys here must match the keyword parameters of
    #   `ResearchAPIClient._build_query_body` — see its docstring for the contract.

    start_date: datetime | None
    end_date: datetime | None
    max_count: int | None
    is_random: bool


class PageOptions(QueryOptions, total=False):
    """:class:`QueryOptions` plus pagination cursors for single-page calls."""

    # DEV NOTE: Keys here must match the keyword parameters of
    #   `ResearchAPIClient._build_query_body` — see its docstring for the contract.

    cursor: str | None
    search_id: str | None


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

    Two access patterns are exposed for video queries:

    * Single-page primitives — :meth:`query_videos`,
      :meth:`query_user_videos` — return one raw API response. Use these
      when you want fine-grained control or just one page (e.g. debugging,
      interactive use).
    * Generators — :meth:`iter_video_pages` / :meth:`iter_user_video_pages`
      yield each raw page following the API cursor; :meth:`iter_videos` /
      :meth:`iter_user_videos` yield individual video dicts across all
      pages. Use these for bulk retrieval — paging, token refresh, and
      retries all happen transparently.

    Attributes:
        ACCESS_TOKEN_URL (str): OAuth token endpoint.
        VIDEO_QUERY_URL (str): Video metadata query endpoint.
        USER_QUERY_URL (str): User info query endpoint.
        MAX_RETRIES (int): Max retries per request on transient errors.
        BACKOFF_CAP (float): Per-sleep ceiling for computed backoff.
        MAX_RETRY_AFTER (float): Ceiling for server-supplied ``Retry-After``.

    Examples:
        Single page with filter options::

            client = ResearchAPIClient("key", "secret")
            page = client.query_videos(
                ["7123456789", "7987654321"],
                PageOptions(max_count=50),
            )

        Stream all videos for a set of users::

            with ResearchAPIClient("key", "secret") as client:
                for video in client.iter_user_videos(["alice", "bob"]):
                    process(video)

        Page-level iteration with a safety cap::

            for page in client.iter_video_pages(ids, max_pages=10):
                process_page(page)

        Resume from a checkpoint, reusing the same filters::

            filters = QueryOptions(start_date=d0, end_date=d1)
            for page in client.iter_video_pages(
                ids, filters,
                cursor=saved_cursor,
                search_id=saved_search_id,
            ):
                ...

    Raises:
        ResearchAPIAccessTokenRetrievalError: If token retrieval fails.
        ResearchAPIRequestError: If a query request fails or the API
            returns an error response.
    """

    ACCESS_TOKEN_URL = config.ACCESS_TOKEN_URL
    VIDEO_QUERY_URL = config.VIDEO_QUERY_URL
    USER_QUERY_URL = config.USER_QUERY_URL

    # Retry/backoff configuration
    MAX_RETRIES = config.DEFAULT_MAX_RETRIES
    BACKOFF_CAP = config.DEFAULT_BACKOFF_CAP
    MAX_RETRY_AFTER = config.MAX_RETRY_AFTER

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        video_fields: Sequence[str] | None = None,
    ) -> None:
        """Construct a client.

        Args:
            api_key: TikTok Research API client key.
            api_secret: TikTok Research API client secret.
            video_fields: Default fields to request from the video-query
                endpoint. ``None`` uses :data:`config.DEFAULT_VIDEO_FIELDS`.
                Per-call overrides are accepted via the ``fields=`` kwarg on
                ``query_*`` and ``iter_*`` methods.
        """
        self.key = api_key
        self.secret = api_secret
        self._video_fields: tuple[str, ...] = (
            tuple(video_fields)
            if video_fields is not None
            else config.DEFAULT_VIDEO_FIELDS
        )

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

    def query_videos(
        self,
        video_ids: list[str],
        query_params: PageOptions | None = None,
        *,
        fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve a single page of video metadata via Research API.

        For automatic pagination across all results, use :meth:`iter_videos`
        or :meth:`iter_video_pages`.

        Args:
            video_ids: List of TikTok video IDs to query.
            query_params: Filter and pagination parameters. See :class:`PageOptions`.
            fields: Per-call override for response fields. ``None`` uses the
                client default (set via ``video_fields=`` in :meth:`__init__`).

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        return self._make_query(
            self._video_id_query(video_ids),
            fields=fields,
            **(query_params or {}),
        )

    def query_user_videos(
        self,
        user_ids: list[str],
        query_params: PageOptions | None = None,
        *,
        fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve a single page of videos posted by given users via Research API.

        For automatic pagination across all results, use :meth:`iter_user_videos`
        or :meth:`iter_user_video_pages`.

        Args:
            user_ids: List of TikTok usernames to query.
            query_params: Filter and pagination parameters. See :class:`PageOptions`.
            fields: Per-call override for response fields. ``None`` uses the
                client default (set via ``video_fields=`` in :meth:`__init__`).

        Raises:
            ResearchAPIRequestError: If the API request fails or returns an error.
        """
        return self._make_query(
            self._username_query(user_ids),
            fields=fields,
            **(query_params or {}),
        )

    def iter_video_pages(  # noqa: PLR0913
        self,
        video_ids: list[str],
        query_filters: QueryOptions | None = None,
        *,
        max_pages: int | None = None,
        cursor: str | None = None,
        search_id: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield each page of video metadata, following the API cursor.

        Args:
            video_ids: List of TikTok video IDs to query.
            query_filters: Filter parameters. See :class:`QueryOptions`.
            max_pages: Safety cap on pages fetched. ``None`` means no cap.
            cursor: Resume from a prior page's cursor.
            search_id: Resume from a prior page's search_id.
            fields: Per-call override for response fields. ``None`` uses the
                client default.

        Yields:
            Raw API response for each page (includes ``data.videos``,
            ``data.cursor``, ``data.search_id``, ``data.has_more``).
        """
        yield from self._iter_pages(
            self._video_id_query(video_ids),
            max_pages=max_pages,
            cursor=cursor,
            search_id=search_id,
            fields=fields,
            **(query_filters or {}),
        )

    def iter_user_video_pages(  # noqa: PLR0913
        self,
        user_ids: list[str],
        query_filters: QueryOptions | None = None,
        *,
        max_pages: int | None = None,
        cursor: str | None = None,
        search_id: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield each page of videos posted by given users, following the API cursor.

        Args:
            user_ids: List of TikTok usernames to query.
            query_filters: Filter parameters. See :class:`QueryOptions`.
            max_pages: Safety cap on pages fetched. ``None`` means no cap.
            cursor: Resume from a prior page's cursor.
            search_id: Resume from a prior page's search_id.
            fields: Per-call override for response fields. ``None`` uses the
                client default.
        """
        yield from self._iter_pages(
            self._username_query(user_ids),
            max_pages=max_pages,
            cursor=cursor,
            search_id=search_id,
            fields=fields,
            **(query_filters or {}),
        )

    def iter_videos(  # noqa: PLR0913
        self,
        video_ids: list[str],
        query_filters: QueryOptions | None = None,
        *,
        max_pages: int | None = None,
        cursor: str | None = None,
        search_id: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield each video dict across all pages.

        Thin wrapper over :meth:`iter_video_pages`; see it for argument docs.
        """
        for page in self.iter_video_pages(
            video_ids,
            query_filters,
            max_pages=max_pages,
            cursor=cursor,
            search_id=search_id,
            fields=fields,
        ):
            yield from page.get("data", {}).get("videos", [])

    def iter_user_videos(  # noqa: PLR0913
        self,
        user_ids: list[str],
        query_filters: QueryOptions | None = None,
        *,
        max_pages: int | None = None,
        cursor: str | None = None,
        search_id: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield each video dict for the given users across all pages.

        Thin wrapper over :meth:`iter_user_video_pages`; see it for argument docs.
        """
        for page in self.iter_user_video_pages(
            user_ids,
            query_filters,
            max_pages=max_pages,
            cursor=cursor,
            search_id=search_id,
            fields=fields,
        ):
            yield from page.get("data", {}).get("videos", [])

    def _iter_pages(
        self,
        query: dict[str, Any],
        *,
        max_pages: int | None,
        cursor: str | None,
        search_id: str | None,
        fields: Sequence[str] | None = None,
        **kwargs: Unpack[QueryOptions],
    ) -> Iterator[dict[str, Any]]:
        """Drive cursor-based pagination for a given query body."""
        pages_yielded = 0
        while True:
            page = self._make_query(
                query,
                cursor=cursor,
                search_id=search_id,
                fields=fields,
                **kwargs,
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
            cursor = next_cursor
            search_id = data.get("search_id", search_id)

    def _make_query(
        self,
        query: dict[str, Any],
        *,
        fields: Sequence[str] | None = None,
        **kwargs: Unpack[PageOptions],
    ) -> dict[str, Any]:
        """Execute a query against the TikTok Research API.

        Builds the request URL, constructs the query body, and sends the request
        with proper authentication headers. Handles both HTTP and API-level errors.

        Args:
            query: The query structure containing filter conditions.
            fields: Per-call override for response fields. ``None`` uses the
                client default.
            **kwargs: Additional query parameters passed to ``_build_query_body``.

        Returns:
            The API response data.

        Raises:
            ResearchAPIRequestError: If the HTTP request fails (non-200 status)
                or if the API returns an error response.
        """
        url = self._build_url(fields)
        query_body = self._build_query_body(query, **kwargs)
        response = self._post_with_retry(
            url,
            headers=self._get_auth_header(),
            json=query_body,
        )

        if response.status_code != httpx.codes.OK:
            msg = (
                f"Invalid response from Research API. "
                f"Response status code: {response.status_code} for "
                f"url '{url}' and query body '{json.dumps(query_body)}'"
            )
            raise ResearchAPIRequestError(msg)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            msg = (
                "Malformed JSON in Research API response "
                f"(content-type: {response.headers.get('Content-Type')!r}, "
                f"body[:200]: {response.text[:200]!r})"
            )
            raise ResearchAPIRequestError(msg) from exc

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

        # Dev Note:
        #     The keyword parameters of this method must stay in sync with
        #     :class:`QueryOptions` / :class:`PageOptions`. Public methods splat
        #     those TypedDicts into this signature, so any divergence becomes a
        #     runtime ``TypeError`` (extra key) or a silently unreachable param
        #     (missing key).

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

    def _build_url(self, fields: Sequence[str] | None = None) -> str:
        """Build the video-query request URL.

        Args:
            fields: Per-call override for response fields. Falls back to the
                client's default (set via ``video_fields=`` in
                :meth:`__init__`, defaulting to
                :data:`config.DEFAULT_VIDEO_FIELDS`).

        Returns:
            The request URL.
        """
        included_fields = fields if fields is not None else self._video_fields
        return self.VIDEO_QUERY_URL + "?fields=" + ",".join(included_fields)
