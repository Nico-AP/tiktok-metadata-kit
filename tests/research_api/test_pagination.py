"""Cursor-based pagination: query_videos_pages, query_videos."""

import json
import logging

import pytest

from tiktok_metadata_kit.research_api import (
    QueryVideosOptions,
    ResearchAPIClient,
)

from .conftest import MockHandler


def _page(
    videos: list[dict],
    *,
    cursor: int | None = None,
    search_id: str | None = None,
    has_more: bool = False,
) -> dict:
    data = {"videos": videos, "has_more": has_more}
    if cursor is not None:
        data["cursor"] = cursor
    if search_id is not None:
        data["search_id"] = search_id
    return {"data": data, "error": {"code": "ok"}}


class TestQueryVideosPages:
    def test_yields_single_page_when_has_more_false(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=False))
        pages = list(client.query_videos_pages({"and": []}))

        assert len(pages) == 1
        assert pages[0]["data"]["videos"] == [{"id": "1"}]

    def test_yields_multiple_pages_following_cursor(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page([{"id": "1"}], cursor=100, search_id="sid", has_more=True),
        )
        mock_handler.add_response(
            _page([{"id": "2"}], cursor=200, search_id="sid", has_more=True),
        )
        mock_handler.add_response(_page([{"id": "3"}], has_more=False))

        pages = list(client.query_videos_pages({"and": []}))

        assert len(pages) == 3
        # Skip the token request (index 0); inspect each query body.
        bodies = [json.loads(r.content) for r in mock_handler.requests[1:]]
        # First request: no cursor yet.
        assert bodies[0].get("cursor") is None
        # Subsequent requests carry the server-supplied cursor.
        assert bodies[1]["cursor"] == 100
        assert bodies[2]["cursor"] == 200
        # search_id is carried forward once the server supplies it.
        assert bodies[1]["search_id"] == "sid"
        assert bodies[2]["search_id"] == "sid"

    def test_max_pages_caps_iteration(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        for i in range(5):
            mock_handler.add_response(
                _page([{"id": str(i)}], cursor=i + 1, has_more=True),
            )

        pages = list(
            client.query_videos_pages(
                {"and": []},
                options=QueryVideosOptions(max_pages=2),
            )
        )

        assert len(pages) == 2
        # Token + 2 page requests = 3 total.
        assert len(mock_handler.requests) == 3

    def test_resume_from_provided_cursor_and_search_id(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=False))
        list(
            client.query_videos_pages(
                {"and": []},
                options=QueryVideosOptions(cursor=500, search_id="saved-sid"),
            )
        )

        body = json.loads(mock_handler.requests[1].content)
        assert body["cursor"] == 500
        assert body["search_id"] == "saved-sid"

    def test_has_more_without_cursor_stops_with_warning(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=True))  # no cursor
        with caplog.at_level(logging.WARNING):
            pages = list(client.query_videos_pages({"and": []}))

        assert len(pages) == 1
        assert any("Pagination stopped" in r.message for r in caplog.records)

    def test_options_forwarded_to_every_page(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([], cursor=10, has_more=True))
        mock_handler.add_response(_page([], has_more=False))

        list(
            client.query_videos_pages(
                {"and": []},
                options=QueryVideosOptions(max_count=25, is_random=True),
            )
        )

        bodies = [json.loads(r.content) for r in mock_handler.requests[1:]]
        assert all(b["max_count"] == 25 for b in bodies)
        assert all(b["is_random"] is True for b in bodies)


class TestQueryVideosFlattening:
    def test_flattens_pages_to_video_dicts(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page([{"id": "1"}, {"id": "2"}], cursor=2, has_more=True),
        )
        mock_handler.add_response(_page([{"id": "3"}], has_more=False))

        videos = list(client.query_videos({"and": []}))

        assert videos == [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    def test_lazy_evaluation_stops_at_break(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Only queue one page. If query_videos eagerly fetched more, this
        # would raise from MockHandler. Breaking after the first item should
        # consume only one page.
        mock_handler.add_response(
            _page([{"id": "1"}, {"id": "2"}], cursor=2, has_more=True),
        )

        for video in client.query_videos({"and": []}):
            assert video["id"] == "1"
            break

        # Only the token + first page should have been requested.
        assert len(mock_handler.requests) == 2


class TestConvenienceWrappersPagination:
    def test_query_videos_by_id_paginates(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], cursor=2, has_more=True))
        mock_handler.add_response(_page([{"id": "2"}], has_more=False))

        videos = list(client.query_videos_by_id([111]))

        assert videos == [{"id": "1"}, {"id": "2"}]
        # Every page request carries the video_id filter.
        for req in mock_handler.requests[1:]:
            body = json.loads(req.content)
            assert body["query"]["and"][0]["field_name"] == "video_id"

    def test_query_videos_by_username_paginates(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page([{"id": "1", "username": "alice"}], cursor=2, has_more=True),
        )
        mock_handler.add_response(
            _page([{"id": "2", "username": "bob"}], has_more=False),
        )

        videos = list(client.query_videos_by_username(["alice", "bob"]))

        assert videos == [
            {"id": "1", "username": "alice"},
            {"id": "2", "username": "bob"},
        ]
        for req in mock_handler.requests[1:]:
            body = json.loads(req.content)
            assert body["query"]["and"][0]["field_name"] == "username"
