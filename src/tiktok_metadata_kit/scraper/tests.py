import pytest

from .client import TikTokClient
from .config import BASE_URLS
from .exceptions import TikTokDataExtractionError, TikTokMissingRehydrationDataError
from .parsers import TikTokParser
from .scraper import TikTokScraper
from .utils import int_or_none

TEST_VIDEO_ID = "7470493179767344430"
TEST_CREATOR_NAME = "tiktok"


class TestTikTokClient:
    def test_get_video_url(self):
        client = TikTokClient()
        video_url = BASE_URLS["video"]
        video_url = video_url.replace("{id}", TEST_VIDEO_ID)

        response = client.get(video_url)
        assert response.status_code == 200

        parser = TikTokParser()
        rehydr_data = parser.load_rehydration_data(response.text)

        parsed_response = parser.extract_video_data(rehydr_data)

        assert "id" in parsed_response
        assert "video" in parsed_response

    def test_get_user_url(self):
        user_id = TEST_CREATOR_NAME
        user_url = BASE_URLS["user"].replace("{username}", str(user_id))

        client = TikTokClient()
        response = client.get(user_url)

        assert response.status_code == 200

        parser = TikTokParser()
        rehydr_data = parser.load_rehydration_data(response.text)

        parsed_response = parser.extract_user_data(rehydr_data)

        assert "user" in parsed_response


class TestTikTokScraper:
    def test_get_video_url(self):
        video_id = "123"
        url = TikTokScraper.get_video_url(video_id)
        assert url == "https://www.tiktok.com/@tiktok/video/123"

    def test_get_user_url(self):
        user_id = "123"
        url = TikTokScraper.get_user_url(user_id)
        assert url == "https://www.tiktok.com/@123"


class TestTikTokParser:
    def test_load_rehydration_data(self):
        test_response = """
        <h1> Test Data</h1>
        <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{"test": 123}</script>
        """
        parser = TikTokParser()
        hydr_data = parser.load_rehydration_data(test_response)
        assert hydr_data["test"] == 123

    def test_load_rehydration_data_missing_script(self):
        test_response = """
        <h1> Test Data</h1>
        <script id="__DATA_FOR_REHYDRATION__">{"test": 123}</script>
        """
        parser = TikTokParser()
        with pytest.raises(TikTokMissingRehydrationDataError):
            parser.load_rehydration_data(test_response)

    def test_extract_video_data_with_valid_data(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "itemStruct": "some data",
                    },
                },
            },
        }
        data = TikTokParser.extract_video_data(example_data)
        assert data == "some data"

    def test_extract_video_data_with_invalid_data(self):
        example_data = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "missingKey": None,
                    },
                },
            },
        }
        with pytest.raises(TikTokDataExtractionError):
            TikTokParser.extract_video_data(example_data)

    def test_extract_user_data_with_valid_data(self):
        pass

    def test_extract_user_data_with_invalid_data(self):
        pass


class TestUtils:
    def test_int_or_none(self):
        assert int_or_none(None) is None
        assert int_or_none("abc") is None
        assert int_or_none(True) == 1
        assert int_or_none(1.3) == 1
