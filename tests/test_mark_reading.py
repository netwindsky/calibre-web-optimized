# -*- coding: utf-8 -*-
"""mark_book_as_reading helper + read_book 路由自动设置 STATUS_IN_PROGRESS 的 TDD 测试。"""

from datetime import datetime, timedelta, timezone

import pytest

from cps import ub


TEST_BOOK_ID = 1


def _cleanup():
    ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == 1, ub.ReadBook.book_id == TEST_BOOK_ID).delete()
    ub.session_commit()


def _get_read_book():
    return ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == 1, ub.ReadBook.book_id == TEST_BOOK_ID).first()


@pytest.fixture()
def _login_and_clean(app, logged_in_client):
    """helper 依赖 current_user，因此需要请求上下文 + 登录态。"""
    _cleanup()
    with app.test_request_context():
        from cps.cw_login import login_user
        user = ub.session.query(ub.User).filter(ub.User.name == "admin").first()
        login_user(user)
        yield logged_in_client
    _cleanup()


class TestMarkBookAsReading:
    def test_unread_book_becomes_in_progress(self, _login_and_clean):
        """未读书籍标记为 STATUS_IN_PROGRESS，并记录开始时间与次数。"""
        from cps.helper import mark_book_as_reading
        before = datetime.now(timezone.utc)
        mark_book_as_reading(TEST_BOOK_ID)
        read_book = _get_read_book()
        assert read_book is not None
        assert read_book.read_status == ub.ReadBook.STATUS_IN_PROGRESS
        assert read_book.last_time_started_reading is not None
        assert read_book.last_time_started_reading >= before.replace(tzinfo=None) - timedelta(seconds=5)
        assert read_book.times_started_reading == 1

    def test_in_progress_book_not_recounted(self, _login_and_clean):
        """已处于阅读中的书：状态不变，times_started_reading 不重复递增。"""
        from cps.helper import mark_book_as_reading
        mark_book_as_reading(TEST_BOOK_ID)
        mark_book_as_reading(TEST_BOOK_ID)
        read_book = _get_read_book()
        assert read_book.read_status == ub.ReadBook.STATUS_IN_PROGRESS
        assert read_book.times_started_reading == 1

    def test_finished_book_not_downgraded(self, _login_and_clean):
        """已读完（STATUS_FINISHED）的书不被降级为阅读中。"""
        from cps.helper import mark_book_as_reading
        read_book = _get_read_book() or ub.ReadBook(user_id=1, book_id=TEST_BOOK_ID)
        read_book.read_status = ub.ReadBook.STATUS_FINISHED
        read_book.times_started_reading = 1
        ub.session.merge(read_book)
        ub.session_commit()

        mark_book_as_reading(TEST_BOOK_ID)
        refreshed = _get_read_book()
        assert refreshed.read_status == ub.ReadBook.STATUS_FINISHED

    def test_unread_to_in_progress_via_toggle_semantics(self, _login_and_clean):
        """从 UNREAD -> IN_PROGRESS 时 last_time_started_reading 更新。"""
        from cps.helper import mark_book_as_reading
        mark_book_as_reading(TEST_BOOK_ID)
        read_book = _get_read_book()
        assert read_book.last_time_started_reading is not None


class TestReadBookRoute:
    def test_read_book_marks_in_progress(self, app, logged_in_client, monkeypatch):
        """GET /read/<id>/<fmt> 应自动把书籍标记为阅读中。"""
        _cleanup()
        # mock calibre_db.get_filtered_book 返回 mock 书对象
        from unittest.mock import MagicMock

        class FakeBook:
            title = "Test Book One"
            ordered_authors = []

            def __init__(self):
                self.authors = []

        def fake_get_filtered_book(book_id, allow_show_archived=False):
            return FakeBook()

        def fake_order_authors(entries, list_return=False, combined=False):
            return []

        from cps import web as web_module
        monkeypatch.setattr(web_module.calibre_db, "get_filtered_book",
                            fake_get_filtered_book)
        monkeypatch.setattr(web_module.calibre_db, "order_authors",
                            fake_order_authors)

        resp = logged_in_client.get("/read/{}/epub".format(TEST_BOOK_ID))
        assert resp.status_code == 200, "阅读页应正常渲染，实际: {} {}".format(
            resp.status_code, resp.data[:500])

        read_book = _get_read_book()
        assert read_book is not None, "read_book 路由应创建 ReadBook 记录"
        assert read_book.read_status == ub.ReadBook.STATUS_IN_PROGRESS
        _cleanup()
