# -*- coding: utf-8 -*-
"""EPUB 阅读器行间距设置的 TDD 测试：
1. 设置面板应包含行间距控件（−/显示/+ 按钮）
2. 行间距 JS 逻辑应绑定按钮事件并持久化到 localStorage
3. 中文环境下标签应被翻译为"行间距"
"""

import pytest


TEST_BOOK_ID = 1


@pytest.fixture()
def _epub_book(app, logged_in_client, monkeypatch):
    """mock calibre_db 返回测试书，让 /read/<id>/epub 路由可渲染。"""
    from unittest.mock import MagicMock

    class FakeBook:
        title = "EPUB Test Book"
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


class TestReaderLineSpacing:
    def test_read_page_has_line_spacing_controls(self, _epub_book):
        """阅读器设置面板应包含行间距 −/显示/+ 控件。"""
        resp = _epub_book.get("/read/{}/epub".format(TEST_BOOK_ID))
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert 'id="lineSpacingDecrease"' in html
        assert 'id="lineSpacingDisplay"' in html
        assert 'id="lineSpacingIncrease"' in html

    def test_read_page_has_line_spacing_js_logic(self, _epub_book):
        """行间距 JS 应包含 applyLineSpacing 与 localStorage 持久化逻辑。"""
        resp = _epub_book.get("/read/{}/epub".format(TEST_BOOK_ID))
        html = resp.data.decode("utf-8")
        assert "applyLineSpacing" in html
        assert "calibre.reader.lineSpacing" in html
        assert "cw-line-spacing" in html
        assert "line-height" in html

    def test_line_spacing_label_is_chinese(self, app, _epub_book):
        """中文环境下行间距标签应翻译为"行间距"。"""
        from cps import ub
        with app.app_context():
            user = ub.session.query(ub.User).filter(ub.User.name == "admin").first()
            user.locale = "zh_Hans_CN"
            ub.session_commit()
        resp = _epub_book.get("/read/{}/epub".format(TEST_BOOK_ID),
                              headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        html = resp.data.decode("utf-8")
        assert "行间距" in html, "中文环境下 Line Spacing 应被翻译为'行间距'"

    def test_epub_js_restores_line_spacing(self):
        """epub.js 应在页面渲染后从 localStorage 恢复行间距。"""
        import os
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "cps", "static", "js", "reading", "epub.js")
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        assert "calibre.reader.lineSpacing" in js
        assert "applyLineSpacing" in js
        assert '"rendered"' in js