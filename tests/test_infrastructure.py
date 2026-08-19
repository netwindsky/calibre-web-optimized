# -*- coding: utf-8 -*-
"""测试基础设施冒烟测试：验证 app / 登录 / 基本页面可用。"""


class TestInfrastructure:
    def test_app_created(self, app):
        assert app is not None
        assert app.config["TESTING"] is True

    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_admin_login(self, logged_in_client):
        resp = logged_in_client.get("/")
        # 登录后访问首页：应渲染 index（200）而非重定向到 /login
        assert resp.status_code == 200

    def test_admin_user_exists(self, admin_user):
        assert admin_user is not None
        assert admin_user.name == "admin"
