# -*- coding: utf-8 -*-
"""批量获取阅读进度 API 的 TDD 测试。

API 契约：GET /ajax/reading/progress
    响应 JSON：{"books": [{"book_id": int, "progress_percent": float, "format": str}, ...]}
"""

import pytest

from cps import ub


def _cleanup():
    ub.session.query(ub.Bookmark).filter(ub.Bookmark.user_id == 1).delete()
    ub.session.query(ub.ReadBook).filter(ub.ReadBook.user_id == 1).delete()
    ub.session_commit()


@pytest.fixture(autouse=True)
def _reset_progress_data():
    _cleanup()
    yield
    _cleanup()


class TestReadingProgressApi:
    def test_endpoint_exists(self, logged_in_client):
        """红色阶段：路由 GET /ajax/reading/progress 应当存在并返回 200 JSON。"""
        resp = logged_in_client.get("/ajax/reading/progress")
        assert resp.status_code == 200
        assert resp.is_json

    def test_empty_progress_list(self, logged_in_client):
        """没有任何进度记录时返回空 books 数组。"""
        resp = logged_in_client.get("/ajax/reading/progress")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"books": []}

    def test_returns_all_book_progress(self, logged_in_client):
        """应返回当前用户全部含进度的书签记录。"""
        for book_id, fmt, pct in [(1, "EPUB", 10.0), (2, "EPUB", 55.5), (3, "PDF", 99.0)]:
            ub.session.merge(ub.Bookmark(user_id=1, book_id=book_id, format=fmt,
                                         bookmark_key="epubcfi(/6/4)",
                                         progress_percent=pct))
        ub.session_commit()

        resp = logged_in_client.get("/ajax/reading/progress")
        assert resp.status_code == 200
        data = resp.get_json()
        books = {b["book_id"]: b for b in data["books"]}
        assert set(books.keys()) == {1, 2, 3}
        assert books[1]["progress_percent"] == pytest.approx(10.0)
        assert books[1]["format"] == "EPUB"
        assert books[2]["progress_percent"] == pytest.approx(55.5)
        assert books[3]["progress_percent"] == pytest.approx(99.0)
        assert books[3]["format"] == "PDF"

    def test_only_own_progress(self, logged_in_client):
        """不得返回其他用户的进度。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=1, format="EPUB",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=30.0))
        ub.session.merge(ub.Bookmark(user_id=2, book_id=2, format="EPUB",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=60.0))
        ub.session_commit()

        resp = logged_in_client.get("/ajax/reading/progress")
        data = resp.get_json()
        book_ids = [b["book_id"] for b in data["books"]]
        assert 2 not in book_ids
        assert 1 in book_ids

    def test_bookmarks_without_progress_excluded(self, logged_in_client):
        """没有 progress_percent（None）的书签不应出现在结果里。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=1, format="EPUB",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=None))
        ub.session.merge(ub.Bookmark(user_id=1, book_id=2, format="EPUB",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=12.0))
        ub.session_commit()

        resp = logged_in_client.get("/ajax/reading/progress")
        data = resp.get_json()
        book_ids = [b["book_id"] for b in data["books"]]
        assert 1 not in book_ids
        assert 2 in book_ids

    def test_response_schema(self, logged_in_client):
        """每条记录只含 book_id / progress_percent / format 三个字段，类型正确。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=7, format="epub",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=25.0))
        ub.session_commit()

        resp = logged_in_client.get("/ajax/reading/progress")
        data = resp.get_json()
        entry = data["books"][0]
        assert set(entry.keys()) == {"book_id", "progress_percent", "format"}
        assert isinstance(entry["book_id"], int)
        assert isinstance(entry["progress_percent"], (int, float))
        assert isinstance(entry["format"], str)

    def test_requires_login(self, client):
        """未登录应被拒绝。"""
        resp = client.get("/ajax/reading/progress")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
