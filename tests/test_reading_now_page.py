# -*- coding: utf-8 -*-
"""Reading Now 页面 UI 功能的 TDD 测试：
1. 页面包含"标记已读完"按钮（调用 /ajax/toggleread）
2. 页面标题与按钮使用中文翻译（i18n）
3. 有进度的书显示进度条与"继续阅读"按钮
"""

import pytest

from cps import ub


TEST_BOOK_ID = 1


def _cleanup():
    ub.session.query(ub.Bookmark).filter(ub.Bookmark.user_id == 1).delete()
    ub.session.query(ub.ReadBook).filter(ub.ReadBook.user_id == 1).delete()
    ub.session_commit()


@pytest.fixture()
def _in_progress_book(app, logged_in_client):
    """把测试书 1 标记为 STATUS_IN_PROGRESS。"""
    _cleanup()
    with app.test_request_context():
        from cps.cw_login import login_user
        user = ub.session.query(ub.User).filter(ub.User.name == "admin").first()
        login_user(user)
        from cps.helper import mark_book_as_reading
        mark_book_as_reading(TEST_BOOK_ID)
    yield logged_in_client
    _cleanup()


class TestReadingNowPage:
    def test_page_has_mark_finished_button(self, _in_progress_book):
        """Reading Now 卡片应包含标记已读完按钮(toggleread)和继续阅读按钮。"""
        resp = _in_progress_book.get("/in_progress/stored")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert '/ajax/toggleread/{}'.format(TEST_BOOK_ID) in html
        assert 'mark-finished-cover' in html
        assert 'cover-play-btn' in html

    def test_mark_finished_button_is_chinese(self, app, _in_progress_book):
        """按钮文案与页面标题在中文 locale 下应被翻译。"""
        # Flask-Babel 通过 current_user.locale 决定语言
        with app.app_context():
            user = ub.session.query(ub.User).filter(ub.User.name == "admin").first()
            user.locale = "zh_Hans_CN"
            ub.session_commit()
        resp = _in_progress_book.get("/in_progress/stored",
                                     headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        html = resp.data.decode("utf-8")
        assert "正在阅读" in html, "中文环境下 Reading Now 应被翻译为'正在阅读'"
        assert "标记已读完" in html, "按钮文案应为中文'标记已读完'"

    def test_progress_bar_shown_when_bookmark_exists(self, _in_progress_book):
        """有进度记录的书应在封面上显示进度条。"""
        ub.session.merge(ub.Bookmark(user_id=1, book_id=TEST_BOOK_ID, format="EPUB",
                                     bookmark_key="epubcfi(/6/4)", progress_percent=42.0))
        ub.session_commit()
        resp = _in_progress_book.get("/in_progress/stored")
        html = resp.data.decode("utf-8")
        assert "reading-progress-cover" in html
        assert "42%" in html


class TestI18nTranslationsCompiled:
    """验证中文 .po 包含关键新增字符串的翻译。"""

    def test_po_contains_reading_now_translation(self):
        import os, re
        po_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "cps", "translations", "zh_Hans_CN", "LC_MESSAGES", "messages.po")
        content = open(po_path, encoding="utf-8").read()
        # 必须包含 Reading Now 的翻译条目
        assert re.search(r'msgid "Reading Now"\s*\n\s*msgstr "[^"]+"', content), \
            "中文 .po 应包含 Reading Now 的非空翻译"
        assert re.search(r'msgid "Continue Reading"\s*\n\s*msgstr "[^"]+"', content), \
            "中文 .po 应包含 Continue Reading 的非空翻译"
        assert re.search(r'msgid "Show books currently being read"\s*\n\s*msgstr "[^"]+"', content), \
            "中文 .po 应包含 Show books currently being read 的非空翻译"
        assert re.search(r'msgid "Mark as Finished"\s*\n\s*msgstr "[^"]+"', content), \
            "中文 .po 应包含 Mark as Finished 的非空翻译"

    def test_mo_is_newer_than_po(self):
        """编译后的 .mo 应不比 .po 旧，否则翻译不生效。"""
        import os
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "cps", "translations", "zh_Hans_CN", "LC_MESSAGES")
        po = os.path.join(base, "messages.po")
        mo = os.path.join(base, "messages.mo")
        assert os.path.getmtime(mo) >= os.path.getmtime(po), \
            ".mo 应在 .po 更新后重新编译"
