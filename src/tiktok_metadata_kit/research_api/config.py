# TikTok endpoints
ACCESS_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/research/video/query/"
USER_QUERY_URL = "https://open.tiktokapis.com/v2/research/user/info/"

# Client configuration
DEFAULT_REFRESH_TOKEN_EXP_TIME = 7200  # seconds = 2 hours
DEFAULT_QUERY_PERIOD = 30  # days
DEFAULT_POST_TIMEOUT = 15  # seconds
DEFAULT_MAX_RESULTS = 100

# Retry/backoff
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE = 1.0  # seconds; delay = base * 2**attempt + jitter
DEFAULT_BACKOFF_CAP = 30.0  # seconds; max single sleep for computed backoff
MAX_RETRY_AFTER = 300.0  # seconds; ceiling for server-supplied Retry-After
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
