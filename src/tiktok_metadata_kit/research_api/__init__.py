"""TikTok Research API client.

Public surface:

* :class:`ResearchAPIClient` — synchronous client with automatic token
  refresh, retries, and cursor-based pagination.
* :class:`QueryVideosOptions` — dataclass for filter and pagination
  parameters passed to ``query_videos*`` methods.
* :class:`ResearchAPIAccessTokenRetrievalError`,
  :class:`ResearchAPIRequestError` — exceptions raised by the client.
"""

from .client import QueryVideosOptions, ResearchAPIClient
from .exceptions import (
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIRequestError,
)

__all__ = [
    "QueryVideosOptions",
    "ResearchAPIAccessTokenRetrievalError",
    "ResearchAPIClient",
    "ResearchAPIRequestError",
]
