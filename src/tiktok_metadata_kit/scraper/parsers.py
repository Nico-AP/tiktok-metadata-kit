import json
from typing import Any

from bs4 import BeautifulSoup

from .exceptions import (
    TikTokDataExtractionError,
    TikTokMissingRehydrationDataError,
    TikTokRehydrationDataAttributeError,
)


class TikTokParser:
    """Handles parsing of HTML/JSON data received from TikTok."""

    @staticmethod
    def load_rehydration_data(response_text: str) -> dict:
        """Extract the rehydration data from the response text.

        Args:
            response_text: Content of a requests.Response object.

        Returns:
            The extracted rehydration data as a dictionary.

        Raises:
            TikTokMissingRehydrationData: When rehydration data script not found
                in response text.
            TikTokRehydrationDataAttributeError: When rehydration data does not
                have expected attributes.
        """
        soup = BeautifulSoup(response_text, "html.parser")
        rehydration_data = soup.find(
            "script",
            attrs={"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"},
        )

        if not rehydration_data:
            msg = "Rehydration data script not found in response."

            raise TikTokMissingRehydrationDataError(msg)

        try:
            json_data = json.loads(rehydration_data.string)
        except AttributeError as e:
            msg = (
                f"Expected rehydration_data to have 'string' attribute, "
                f"but got {type(rehydration_data).__name__}. "
            )

            raise TikTokRehydrationDataAttributeError(msg) from e

        return json_data

    @staticmethod
    def extract_video_data(json_data: dict) -> dict[str, Any]:
        """Extract the video data from the JSON response.

        Returns all the data found under the path:
        `__DEFAULT_SCOPE__.webapp.video-detail.itemInfo.itemStruct`

        Args:
            json_data: JSON response from TikTok.

        Returns:
            The extracted video data as a dictionary.

        Raises:
            TikTokDataExtractionError: When json_data does not contain expected keys.
        """
        default_video_data_chain = [
            "__DEFAULT_SCOPE__",
            "webapp.video-detail",
            "itemInfo",
            "itemStruct",
        ]

        for key in default_video_data_chain:
            if key in json_data:
                json_data = json_data[key]
            else:
                status_code = None
                if "statusCode" in json_data:
                    status_code = json_data["statusCode"]

                status_msg = None
                if "statusMsg" in json_data:
                    status_msg = json_data["statusMsg"]

                descr = None
                if status_code is not None or status_msg is not None:
                    descr = f"[statusCode: {status_code}; msg: {status_msg}]"

                msg = f"Could not find key '{key}' in json_data {descr}"

                raise TikTokDataExtractionError(msg)

        return json_data

    @staticmethod
    def extract_user_data(json_data: dict) -> dict[str, Any]:
        """Extract the user data from the JSON response.

        Returns all the data found under the path:
        `__DEFAULT_SCOPE__.webapp.user-detail.userInfo`

        Args:
            json_data: JSON response from TikTok.

        Returns:
            The extracted user data as a dictionary.

        Raises:
            TikTokDataExtractionError: When json_data does not contain expected keys.
        """
        default_video_data_chain = [
            "__DEFAULT_SCOPE__",
            "webapp.user-detail",
            "userInfo",
        ]

        for key in default_video_data_chain:
            if key in json_data:
                json_data = json_data[key]
            else:
                status_code = None
                if "statusCode" in json_data:
                    status_code = json_data["statusCode"]

                status_msg = None
                if "statusMsg" in json_data:
                    status_msg = json_data["statusMsg"]

                descr = None
                if status_code is not None or status_msg is not None:
                    descr = f"[statusCode: {status_code}; msg: {status_msg}]"

                msg = f"Could not find key '{key}' in json_data {descr}"

                raise TikTokDataExtractionError(msg)

        return json_data
