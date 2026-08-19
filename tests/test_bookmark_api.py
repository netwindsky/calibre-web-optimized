# -*- coding: utf-8 -*-
"""set_bookmark API 保存进度百分比的 TDD 测试。

API 契约：POST /ajax/bookmark/<book_id>/<book_format>
    form: bookmark (CFI 字符串), progress_percent (可选, "0"-"100" 浮点数字符串)
"""

import pytest

from cps import ub


TEST_BOOK_ID = 1
TEST_FORMAT = "EPUB"


def _cleanup_bookmarks():
    ub.session.query(ub.Bookmark).filter(
        ub.Bookmark.book_id == TEST_BOOK_ID,
        ub.Bookmark.user_id == 1).delete()
    ub.session_commit()


def _get_bookmark():
    return ub.session.query(ub.Bookmark).filter(
        ub.Bookmark.book_id == TEST_BOOK_ID,
        ub.Bookmark.user_id == 1,
        ub.Bookmark.format == TEST_FORMAT).first()


@pytest.mark.usefixtures("fresh_bookmark")
class TestSetBookmarkProgress:
    def test_save_progress_percent_with_bookmark(self, logged_in_client):
        """同时提交 bookmark CFI 与 progress_percent 时两者都保存。"""
        _cleanup_bookmarks()
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/10!/4)", "progress_percent": "42.5"})
        assert resp.status_code == 201
        bookmark = _get_bookmark()
        assert bookmark is not None
        assert bookmark.bookmark_key == "epubcfi(/6/10!/4)"
        assert bookmark.progress_percent == pytest.approx(42.5)

    def test_save_progress_zero(self, logged_in_client):
        """0% 是合法进度值，不应当被当作空值丢弃。"""
        _cleanup_bookmarks()
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/2)", "progress_percent": "0"})
        assert resp.status_code == 201
        bookmark = _get_bookmark()
        assert bookmark.progress_percent == pytest.approx(0.0)

    def test_progress_percent_optional(self, logged_in_client):
        """不传 progress_percent 时行为与旧版一致：仅保存 bookmark_key。"""
        _cleanup_bookmarks()
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/8)"})
        assert resp.status_code == 201
        bookmark = _get_bookmark()
        assert bookmark is not None
        assert bookmark.bookmark_key == "epubcfi(/6/8)"
        assert bookmark.progress_percent is None

    def test_invalid_progress_percent_ignored(self, logged_in_client):
        """非法的 progress_percent（非数字/越界）应当被忽略，不阻塞书签保存。"""
        _cleanup_bookmarks()
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/8)", "progress_percent": "not-a-number"})
        assert resp.status_code == 201
        bookmark = _get_bookmark()
        assert bookmark.bookmark_key == "epubcfi(/6/8)"
        assert bookmark.progress_percent is None

    def test_progress_percent_out_of_range_clamped_or_rejected(self, logged_in_client):
        """越界值（>100 或 <0）不得原样入库。"""
        _cleanup_bookmarks()
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/8)", "progress_percent": "150"})
        assert resp.status_code == 201
        bookmark = _get_bookmark()
        # 越界值被钳制到 100 或忽略（None），都算符合契约；但不能是 150
        assert bookmark.progress_percent is None or bookmark.progress_percent <= 100.0

    def test_update_existing_progress(self, logged_in_client):
        """再次提交应更新（而非叠加）同一条书签记录的进度。"""
        _cleanup_bookmarks()
        logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/4)", "progress_percent": "10"})
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/12)", "progress_percent": "80.5"})
        assert resp.status_code == 201
        bookmarks = ub.session.query(ub.Bookmark).filter(
            ub.Bookmark.book_id == TEST_BOOK_ID,
            ub.Bookmark.user_id == 1,
            ub.Bookmark.format == TEST_FORMAT).all()
        assert len(bookmarks) == 1
        assert bookmarks[0].bookmark_key == "epubcfi(/6/12)"
        assert bookmarks[0].progress_percent == pytest.approx(80.5)

    def test_empty_bookmark_still_deletes(self, logged_in_client):
        """空 bookmark（旧行为：删除书签）必须保持不变。"""
        _cleanup_bookmarks()
        logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/4)", "progress_percent": "10"})
        resp = logged_in_client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": ""})
        assert resp.status_code == 204
        assert _get_bookmark() is None

    def test_requires_login(self, client):
        """未登录访问应被拒绝（重定向到登录页）。"""
        resp = client.post(
            "/ajax/bookmark/{}/{}".format(TEST_BOOK_ID, TEST_FORMAT),
            data={"bookmark": "epubcfi(/6/4)", "progress_percent": "10"})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
