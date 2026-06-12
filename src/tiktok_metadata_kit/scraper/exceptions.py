class TikTokClientGetError(Exception):
    """Raised when GET request to TikTok did not return status ok."""


class TikTokMissingRehydrationDataError(Exception):
    """Raised when request to TikTok did not return any rehydration data."""


class TikTokRehydrationDataAttributeError(Exception):
    """Raised when received rehydration data does not have expected attributes."""


class TikTokDataExtractionError(Exception):
    """Raised when TikTok hydration data structure is unexpected or invalid."""
