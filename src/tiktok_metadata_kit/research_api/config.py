# TikTok endpoints
ACCESS_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/research/video/query/"
USER_QUERY_URL = "https://open.tiktokapis.com/v2/research/user/info/"

# Client configuration
DEFAULT_REFRESH_TOKEN_EXP_TIME = 7200  # seconds = 2 hours
DEFAULT_QUERY_PERIOD = 30  # 30 days
DEFAULT_POST_TIMEOUT = 15  # 15 seconds
DEFAULT_MAX_RESULTS = 100