"""TikTok Research API client.

Public surface:

* :class:`ResearchAPIClient` — synchronous client with automatic token
  refresh, retries, and cursor-based pagination.
* :class:`QueryVideosOptions` — dataclass for filter and pagination
  parameters passed to ``query_videos*`` methods.
* :class:`ResearchAPIError` — base exception for all API errors. Subclasses
  (:class:`ResearchAPIAccessTokenInvalidError`,
  :class:`ResearchAPIInternalServerError`,
  :class:`ResearchAPIInvalidParamsError`,
  :class:`ResearchAPIRateLimitExceededError`) let callers ``except`` on the
  specific failure mode.
* :class:`ResearchAPIAccessTokenRetrievalError` — raised when the OAuth
  token-retrieval call itself fails (distinct from a query failing because
  the token is invalid mid-session).
"""

from .client import QueryVideosOptions, ResearchAPIClient
from .exceptions import (
    ResearchAPIAccessTokenInvalidError,
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIError,
    ResearchAPIInternalServerError,
    ResearchAPIInvalidParamsError,
    ResearchAPIRateLimitExceededError,
)

__all__ = [
    "QueryVideosOptions",
    "ResearchAPIAccessTokenInvalidError",
    "ResearchAPIAccessTokenRetrievalError",
    "ResearchAPIClient",
    "ResearchAPIError",
    "ResearchAPIInternalServerError",
    "ResearchAPIInvalidParamsError",
    "ResearchAPIRateLimitExceededError",
]
