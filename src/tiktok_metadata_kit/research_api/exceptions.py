class ResearchAPIAccessTokenRetrievalError(Exception):
    """Access token could not be obtained from TikTok."""


class ResearchAPIError(Exception):
    """Response retrieved from Research API contains errors."""


class ResearchAPIAccessTokenInvalidError(ResearchAPIError):
    """The access token is invalid or not found in the request. (401)"""


class ResearchAPIInternalServerError(ResearchAPIError):
    """TikTok internal error. (500)"""


class ResearchAPIInvalidParamsError(ResearchAPIError):
    """One or more fields in request is invalid. (400)"""


class ResearchAPIRateLimitExceededError(ResearchAPIError):
    """The API rate limit was exceeded. (429)"""
