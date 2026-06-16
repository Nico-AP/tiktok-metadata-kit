"""Cursor-based pagination: iter_video_pages / iter_videos and friends."""

import json
import logging

import pytest

from tiktok_metadata_kit.research_api import (
    QueryOptions,
    ResearchAPIClient,
)

from .conftest import MockHandler


def _page(
    videos: list[dict],
    *,
    cursor: str | None = None,
    search_id: str | None = None,
    has_more: bool = False,
) -> dict:
    data = {"videos": videos, "has_more": has_more}
    if cursor is not None:
        data["cursor"] = cursor
    if search_id is not None:
        data["search_id"] = search_id
    return {"data": data, "error": {"code": "ok"}}


class TestIterVideoPages:
    def test_yields_single_page_when_has_more_false(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=False))
        pages = list(client.iter_video_pages(["any"]))

        assert len(pages) == 1
        assert pages[0]["data"]["videos"] == [{"id": "1"}]

    def test_yields_multiple_pages_following_cursor(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page(
                [{"id": "1"}],
                cursor="c2",
                search_id="sid",
                has_more=True,
            )
        )
        mock_handler.add_response(
            _page(
                [{"id": "2"}],
                cursor="c3",
                search_id="sid",
                has_more=True,
            )
        )
        mock_handler.add_response(_page([{"id": "3"}], has_more=False))

        pages = list(client.iter_video_pages(["any"]))

        assert len(pages) == 3
        # Skip the token request (index 0) and inspect query bodies.
        bodies = [json.loads(r.content) for r in mock_handler.requests[1:]]
        assert bodies[0]["cursor"] is None
        assert bodies[1]["cursor"] == "c2"
        assert bodies[2]["cursor"] == "c3"
        # search_id is carried forward once the server supplies it.
        assert bodies[1]["search_id"] == "sid"

    def test_max_pages_caps_iteration(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        for i in range(5):
            mock_handler.add_response(
                _page(
                    [{"id": str(i)}],
                    cursor=f"c{i + 1}",
                    has_more=True,
                )
            )
        pages = list(client.iter_video_pages(["any"], max_pages=2))

        assert len(pages) == 2

    def test_resume_from_provided_cursor(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=False))
        list(
            client.iter_video_pages(
                ["any"],
                cursor="saved-cursor",
                search_id="saved-sid",
            )
        )

        body = json.loads(mock_handler.requests[1].content)
        assert body["cursor"] == "saved-cursor"
        assert body["search_id"] == "saved-sid"

    def test_has_more_without_cursor_stops_with_warning(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=True))  # no cursor
        with caplog.at_level(logging.WARNING):
            pages = list(client.iter_video_pages(["any"]))

        assert len(pages) == 1
        assert any("Pagination stopped" in r.message for r in caplog.records)

    def test_query_filters_forwarded_to_every_page(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([], cursor="c2", has_more=True))
        mock_handler.add_response(_page([], has_more=False))

        list(
            client.iter_video_pages(
                ["any"],
                QueryOptions(max_count=25, is_random=True),
            )
        )

        bodies = [json.loads(r.content) for r in mock_handler.requests[1:]]
        assert all(b["max_count"] == 25 for b in bodies)
        assert all(b["is_random"] is True for b in bodies)


class TestIterVideos:
    def test_flattens_pages_to_video_dicts(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page(
                [{"id": "1"}, {"id": "2"}],
                cursor="c2",
                has_more=True,
            )
        )
        mock_handler.add_response(_page([{"id": "3"}], has_more=False))

        videos = list(client.iter_videos(["any"]))

        assert videos == [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    def test_lazy_evaluation_stops_at_break(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        # Only queue one page. If iter_videos eagerly fetched more, this
        # would raise from MockHandler. Breaking after the first item should
        # consume only one page.
        mock_handler.add_response(
            _page(
                [{"id": "1"}, {"id": "2"}],
                cursor="c2",
                has_more=True,
            )
        )
        for video in client.iter_videos(["any"]):
            assert video["id"] == "1"
            break

        # Only the token + first page should have been requested.
        assert len(mock_handler.requests) == 2


class TestIterUserVideos:
    def test_user_video_pages_uses_username_filter(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(_page([{"id": "1"}], has_more=False))
        list(client.iter_user_video_pages(["alice"]))

        body = json.loads(mock_handler.requests[1].content)
        assert body["query"]["and"][0]["field_name"] == "username"
        assert body["query"]["and"][0]["field_values"] == ["alice"]

    def test_iter_user_videos_flattens_pages_to_video_dicts(
        self,
        mock_handler: MockHandler,
        client: ResearchAPIClient,
    ) -> None:
        mock_handler.add_response(
            _page(
                [{"id": "1", "username": "alice"}, {"id": "2", "username": "alice"}],
                cursor="c2",
                has_more=True,
            )
        )
        mock_handler.add_response(
            _page([{"id": "3", "username": "bob"}], has_more=False),
        )

        videos = list(client.iter_user_videos(["alice", "bob"]))

        assert videos == [
            {"id": "1", "username": "alice"},
            {"id": "2", "username": "alice"},
            {"id": "3", "username": "bob"},
        ]
        # Verify the username filter was sent on every page request.
        for req in mock_handler.requests[1:]:
            body = json.loads(req.content)
            assert body["query"]["and"][0]["field_name"] == "username"
