"""TikTok metadata collection toolkit.

This package exposes two independent subpackages:

* :mod:`tiktok_metadata_kit.research_api` — client for the official TikTok Research API.
* :mod:`tiktok_metadata_kit.scraper` — web-scraping fallback.

Import from a subpackage directly, e.g.::

    from tiktok_metadata_kit.research_api import ResearchAPIClient
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tiktok-metadata-kit")
except PackageNotFoundError:  # editable install before metadata is built
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
