import json
import time
from typing import Any

import redis
from datetime import datetime, timezone
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.options import Options


class TikTokCookiesManager:
    """A manager class to handle TikTok cookies.

    Implements methods to create, store (cache), and retrieve TikTok cookies.
    """

    def __init__(self):
        self.redis_client = redis.Redis(host="redis", port=6379, db=0)
        self.key = "tiktok_cookies"
        self.main_url = "https://www.tiktok.com"

    def create_cookies(
        self,
        cache_cookie: bool = True,  # noqa: FBT002
    ) -> dict[str, Any]:
        """Creates a cookie by accessing TikTok through selenium.

        Args:
            cache_cookie: Whether to cache the cookie. Defaults to True.

        Returns:
            A dictionary containing cookie data.
        """
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        try:
            driver = webdriver.Chrome(options=options)
            driver.get(self.main_url)

            # Simulate human behavior to get legitimate cookies.
            time.sleep(5)
            driver.execute_script("window.scrollTo(0, 950)")
            time.sleep(2)

            # Extract cookies.
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            driver.quit()

            if cache_cookie:
                self.cache_cookies(cookies)

        except WebDriverException:
            cookies = None

        return cookies

    def get_or_create_cookies(self) -> dict[str, Any] | None:
        """Tries to get cookie from cache or create a new one.

        Returns:
            The cookies if they could be created or loaded, otherwise None.
        """
        return self.get_cookies() or self.create_cookies()

    def cache_cookies(
        self,
        cookies: dict[str, str],
        ttl_seconds: int = 86400,
    ) -> None:
        """Store a TikTok cookie in cache.

        Args:
            cookies: The cookie dictionary.
            ttl_seconds: The time to live for the cookie in seconds.

        Returns:
            None
        """
        cache_data = {
            "cookies": cookies,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        self.redis_client.set(
            self.key,
            json.dumps(cache_data),
            ex=ttl_seconds,
        )

    def get_cookies(self) -> dict[str, Any] | None:
        """Get cookie from cache.

        Returns:
            The cookies dictionary or None, if cookie data not found.
        """
        cached_data = self.redis_client.get(self.key)
        if cached_data:
            try:
                cache_data = json.loads(cached_data)
                return cache_data["cookies"]
            except json.JSONDecodeError:
                return None
        return None
