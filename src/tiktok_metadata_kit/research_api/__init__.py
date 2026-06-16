"""TikTok Research API client.

Public surface:

* :class:`ResearchAPIClient` — synchronous client with automatic token
  refresh, retries, and cursor-based pagination.
* :class:`QueryOptions`, :class:`PageOptions` — TypedDicts for passing
  filter and pagination parameters to query methods.
* :class:`ResearchAPIAccessTokenRetrievalError`,
  :class:`ResearchAPIRequestError` — exceptions raised by the client.
"""

from .client import PageOptions, QueryOptions, ResearchAPIClient
from .exceptions import (
    ResearchAPIAccessTokenRetrievalError,
    ResearchAPIRequestError,
)

__all__ = [
    "PageOptions",
    "QueryOptions",
    "ResearchAPIAccessTokenRetrievalError",
    "ResearchAPIClient",
    "ResearchAPIRequestError",
]
