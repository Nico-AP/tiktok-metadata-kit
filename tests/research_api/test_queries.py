"""Single-page query primitives: query_videos and query_user_videos."""

import json
from datetime import UTC, datetime

import pytest

from tiktok_metadata_kit.research_api import (
    PageOptions,
    ResearchAPIClient,
    ResearchAPIRequestError,
)

from .conftest import MockHandler


def _success_body(videos: list[dict] | None = None, **extra: object) -> dict:
    return {"data": {"videos": videos or [], **extra}, "error": {"code": "ok"}}


class TestQueryVideos:
    def test_hits_video_endpoint(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_success_body([{"id": "1"}]))
        client.query_videos(["1", "2"])

        # Index 0 was the token request from the `client` fixture.
        query_req = mock_handler.requests[1]
        assert query_req.method == "POST"
        assert str(query_req.url).startswith(ResearchAPIClient.VIDEO_QUERY_URL)

    def test_builds_in_filter_on_video_id(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_success_body())
        client.query_videos(["abc", "def"])

        body = json.loads(mock_handler.requests[1].content)
        assert body["query"] == {
            "and": [
                {
                    "operation": "IN",
                    "field_name": "video_id",
                    "field_values": ["abc", "def"],
                },
            ],
        }

    def test_query_params_forwarded(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_success_body())
        client.query_videos(
            ["1"],
            PageOptions(
                max_count=42,
                cursor="abc",
                search_id="sid",
                is_random=True,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 1, 31, tzinfo=UTC),
            ),
        )

        body = json.loads(mock_handler.requests[1].content)
        assert body["max_count"] == 42
        assert body["cursor"] == "abc"
        assert body["search_id"] == "sid"
        assert body["is_random"] is True
        assert body["start_date"] == "20260101"
        assert body["end_date"] == "20260131"

    def test_fields_override_appears_in_url(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_success_body())
        client.query_videos(["1"], fields=["id", "view_count"])

        url = str(mock_handler.requests[1].url)
        assert "fields=id%2Cview_count" in url or "fields=id,view_count" in url

    def test_default_fields_from_constructor(
        self,
        mock_handler: MockHandler,
        make_client,  # noqa: ANN001
    ) -> None:
        mock_handler.add_response({"access_token": "t", "expires_in": 7200})
        client = make_client(video_fields=["id"])
        mock_handler.add_response(_success_body())
        client.query_videos(["1"])

        url = str(mock_handler.requests[1].url)
        assert "fields=id" in url
        # Verify the default 22-field list isn't present.
        assert "video_description" not in url


class TestQueryUserVideos:
    def test_builds_in_filter_on_username(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_success_body())
        client.query_user_videos(["alice", "bob"])

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
        # query_user_videos filters by username but still queries the video
        # endpoint — that's the documented contract.
        mock_handler.add_response(_success_body())
        client.query_user_videos(["alice"])

        url = str(mock_handler.requests[1].url)
        assert url.startswith(ResearchAPIClient.VIDEO_QUERY_URL)


class TestQueryErrors:
    def test_non_200_raises(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        client.MAX_RETRIES = 0
        mock_handler.add_response("bad", status=400)
        with pytest.raises(ResearchAPIRequestError, match="400"):
            client.query_videos(["1"])

    def test_api_error_in_payload_raises(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            {"data": {}, "error": {"code": "bad_request", "msg": "nope"}},
        )
        with pytest.raises(ResearchAPIRequestError, match="bad_request"):
            client.query_videos(["1"])

    def test_malformed_json_raises_chained(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response("not json", headers={"Content-Type": "text/plain"})
        with pytest.raises(ResearchAPIRequestError) as exc_info:
            client.query_videos(["1"])
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
