# -*- coding: utf-8 -*-
"""PDF 阅读器应保存/恢复阅读进度的 TDD 测试。"""

import pytest

from cps import ub


TEST_BOOK_ID = 1


def _cleanup():
    ub.session.query(ub.Bookmark).filter(ub.Bookmark.user_id == 1).delete()
    ub.session.query(ub.ReadBook).filter(ub.ReadBook.user_id == 1).delete()
    ub.session_commit()


@pytest.fixture()
def _pdf_book(app, logged_in_client, monkeypatch):
    """mock calibre_db 返回测试书，让 /read/<id>/pdf 路由可渲染。"""
    _cleanup()
    from unittest.mock import MagicMock

    class FakeBook:
        title = "PDF Test Book"
        ordered_authors = []

        def __init__(self):
            self.authors = []

    def fake_get_filtered_book(book_id, allow_show_archived=False):
        return FakeBook()

    def fake_order_authors(entries, list_return=False, combined=False):
        return []

    from cps import web as web_module
    monkeypatch.setattr(web_module.calibre_db, "get_filtered_book", fake_get_filtered_book)
    monkeypatch.setattr(web_module.calibre_db, "order_authors", fake_order_authors)
    yield logged_in_client
    _cleanup()


class TestPdfReaderProgress:
    def test_pdf_route_renders_with_csrf(self, _pdf_book):
        """PDF 阅读页应包含 CSRF token。"""
        resp = _pdf_book.get("/read/{}/pdf".format(TEST_BOOK_ID))
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "csrf_token" in html
        assert 'name="csrf_token"' in html

    def test_pdf_route_passes_bookmark_to_template(self, _pdf_book):
        """有 PDF 书签时，SAVED_PAGE 应被注入到页面 JS。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=TEST_BOOK_ID, format="PDF",
                                     bookmark_key="42", progress_percent=35.0))
        ub.session_commit()
        resp = _pdf_book.get("/read/{}/pdf".format(TEST_BOOK_ID))
        html = resp.data.decode("utf-8")
        assert "SAVED_PAGE" in html
        assert "42" in html, "保存的页码应注入页面"
        assert "/ajax/bookmark/{}/pdf".format(TEST_BOOK_ID) in html

    def test_pdf_bookmark_save_endpoint(self, _pdf_book):
        """POST 页码和进度应成功保存。"""
        resp = _pdf_book.post("/ajax/bookmark/{}/pdf".format(TEST_BOOK_ID),
                              data={"bookmark": "15", "progress_percent": "25.5"})
        assert resp.status_code == 201
        bm = ub.session.query(ub.Bookmark).filter(
            ub.Bookmark.user_id == 1,
            ub.Bookmark.book_id == TEST_BOOK_ID,
            ub.Bookmark.format == "PDF").first()
        assert bm is not None
        assert bm.bookmark_key == "15"
        assert bm.progress_percent == pytest.approx(25.5)

    def test_pdf_progress_appears_in_reading_now(self, _pdf_book):
        """PDF 保存的进度应出现在 /ajax/reading/progress 中。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=TEST_BOOK_ID, format="PDF",
                                     bookmark_key="10", progress_percent=66.0))
        ub.session_commit()
        resp = _pdf_book.get("/ajax/reading/progress")
        data = resp.get_json()
        pdf_entries = [b for b in data["books"] if b["book_id"] == TEST_BOOK_ID]
        assert len(pdf_entries) == 1
        assert pdf_entries[0]["format"] == "PDF"
        assert pdf_entries[0]["progress_percent"] == pytest.approx(66.0)
