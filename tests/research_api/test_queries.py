"""Public query methods: query_videos*, query_user_info."""

import json
from datetime import date

import pytest

from tiktok_metadata_kit.research_api import (
    QueryVideosOptions,
    ResearchAPIClient,
    ResearchAPIRequestError,
)

from .conftest import MockHandler


def _page(videos: list[dict] | None = None, **extra: object) -> dict:
    """Build a single-page successful query_videos response."""
    return {
        "data": {"videos": videos or [], "has_more": False, **extra},
        "error": {"code": "ok"},
    }


def _user_info(**fields: object) -> dict:
    return {"data": fields, "error": {"code": "ok"}}


class TestQueryVideosByID:
    def test_hits_video_endpoint(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}]))
        list(client.query_videos_by_id([1, 2]))

        # Index 0 was the token request from the `client` fixture.
        query_req = mock_handler.requests[1]
        assert query_req.method == "POST"
        assert str(query_req.url).startswith(ResearchAPIClient.QUERY_VIDEOS_URL)

    def test_builds_in_filter_on_video_id(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        list(client.query_videos_by_id([111, 222]))

        body = json.loads(mock_handler.requests[1].content)
        assert body["query"] == {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "video_id",
                    "field_values": [111, 222],
                },
            ],
        }


class TestQueryVideosByUsername:
    def test_builds_in_filter_on_username(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        list(client.query_videos_by_username(["alice", "bob"]))

        body = json.loads(mock_handler.requests[1].content)
        assert body["query"] == {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "username",
                    "field_values": ["alice", "bob"],
                },
            ],
        }

    def test_hits_video_endpoint_not_user_info(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # query_videos_by_username filters by username but still queries the
        # video endpoint — that's the documented contract.
        mock_handler.add_response(_page())
        list(client.query_videos_by_username(["alice"]))

        url = str(mock_handler.requests[1].url)
        assert url.startswith(ResearchAPIClient.QUERY_VIDEOS_URL)


class TestQueryVideosRawQuery:
    def test_accepts_raw_query_dict(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "x"}]))
        raw_query = {
            "or": [
                {"operation": "EQ", "field_name": "region_code", "field_values": ["US"]}
            ]
        }

        videos = list(client.query_videos(raw_query))

        assert videos == [{"id": "x"}]
        body = json.loads(mock_handler.requests[1].content)
        assert body["query"] == raw_query

    def test_options_forwarded_to_request_body(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        opts = QueryVideosOptions(
            max_count=42,
            cursor=100,
            search_id="sid",
            is_random=True,
        )
        list(client.query_videos_by_id([1], options=opts))

        body = json.loads(mock_handler.requests[1].content)
        assert body["max_count"] == 42
        assert body["cursor"] == 100
        assert body["search_id"] == "sid"
        assert body["is_random"] is True

    def test_dates_formatted_as_yyyymmdd(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        list(
            client.query_videos_by_id(
                [1],
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            )
        )

        body = json.loads(mock_handler.requests[1].content)
        assert body["start_date"] == "20260101"
        assert body["end_date"] == "20260131"


class TestQueryVideosFields:
    def test_default_fields_used_when_options_omitted(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        list(client.query_videos_by_id([1]))

        # Without an explicit options=, QueryVideosOptions falls back to
        # config.QUERY_VIDEOS_FIELDS via its default_factory.
        url = str(mock_handler.requests[1].url)
        assert "fields=id" in url
        assert "video_description" in url

    def test_options_fields_override(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page())
        list(
            client.query_videos_by_id(
                [1],
                options=QueryVideosOptions(fields=["id", "view_count"]),
            )
        )

        url = str(mock_handler.requests[1].url)
        assert "fields=id%2Cview_count" in url or "fields=id,view_count" in url
        # Confirm the default field list is *not* present.
        assert "video_description" not in url


class TestQueryUserInfo:
    def test_hits_user_info_endpoint(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_user_info(display_name="Alice"))
        result = client.query_user_info("alice")

        url = str(mock_handler.requests[1].url)
        assert url.startswith(ResearchAPIClient.QUERY_USER_INFO_URL)
        assert result["data"]["display_name"] == "Alice"

    def test_sends_username_in_body(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_user_info())
        client.query_user_info("alice")

        body = json.loads(mock_handler.requests[1].content)
        assert body == {"username": "alice"}

    def test_uses_user_info_field_set(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_user_info())
        client.query_user_info("alice")

        url = str(mock_handler.requests[1].url)
        # User-info fields, not video fields.
        assert "display_name" in url
        assert "video_description" not in url


class TestQueryErrors:
    def test_non_200_raises(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        client.MAX_RETRIES = 0
        mock_handler.add_response("bad", status=400)
        with pytest.raises(ResearchAPIRequestError, match="400"):
            list(client.query_videos_by_id([1]))

    def test_api_error_in_payload_raises(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            {"data": {}, "error": {"code": "bad_request", "msg": "nope"}},
        )
        with pytest.raises(ResearchAPIRequestError, match="bad_request"):
            list(client.query_videos_by_id([1]))

    def test_malformed_json_raises_chained(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            "not json",
            headers={"Content-Type": "text/plain"},
        )
        with pytest.raises(ResearchAPIRequestError) as exc_info:
            list(client.query_videos_by_id([1]))
        assert exc_info.value.__cause__ is not None


class TestContextManager:
    def test_context_manager_closes_pool(
        self,
        mock_handler: MockHandler,
        make_client,  # noqa: ANN001
    ) -> None:
        mock_handler.add_response({"access_token": "t", "expires_in": 7200})
        with make_client() as client:
            assert not client._http_client.is_closed
        assert client._http_client.is_closed
