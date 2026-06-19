# TikTok endpoints
ACCESS_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
QUERY_VIDEOS_URL = "https://open.tiktokapis.com/v2/research/video/query/"
QUERY_USER_INFO_URL = "https://open.tiktokapis.com/v2/research/user/info/"

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

# Default set of fields requested from the video-query endpoint.
# See https://developers.tiktok.com/doc/research-api-specs-query-videos#query_parameters
QUERY_VIDEOS_FIELDS: tuple[str, ...] = (
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
    "favorites_count",
)

QUERY_USER_INFO_FIELDS: tuple[str, ...] = (
    "display_name",
    "bio_description",
    "avatar_url",
    "is_verified",
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
    "bio_url",
)
