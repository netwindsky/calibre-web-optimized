# -*- coding: utf-8 -*-
"""Calibre-Web 阅读进度功能测试夹具。

测试策略：
- app.db（ub 数据库）与 calibre 元数据库均使用临时目录创建，每次会话新建。
- conftest 手动完成 create_app() 的核心初始化步骤（不启动后台线程/更新器），
  并注册与 web 路由相关的全部 blueprints。
- 登录通过 POST /login（admin/admin123）完成，CSRF 在测试中禁用。
"""

import os
import sqlite3
import sys

import pytest

# 确保 calibre-web 根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 最小 calibre 元数据库 schema（与 cps/db.py 的 ORM 映射兼容）
_CALIBRE_SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL, sort TEXT, timestamp TIMESTAMP,
    pubdate TIMESTAMP, series_index REAL, author_sort TEXT, isbn TEXT DEFAULT '', lccn TEXT DEFAULT '',
    path TEXT NOT NULL, flags INTEGER NOT NULL DEFAULT 1, uuid TEXT, has_cover BOOL DEFAULT 0,
    last_modified TIMESTAMP);
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort TEXT, link TEXT NOT NULL DEFAULT '');
CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, author INTEGER NOT NULL);
CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort TEXT);
CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, series INTEGER NOT NULL);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, tag INTEGER NOT NULL);
CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT NOT NULL);
CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, lang_code INTEGER NOT NULL,
    item_order INTEGER DEFAULT 0 NOT NULL);
CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort TEXT);
CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, publisher INTEGER NOT NULL);
CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER NOT NULL DEFAULT 0);
CREATE TABLE books_ratings_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, rating INTEGER NOT NULL);
CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL COLLATE NOCASE,
    uncompressed_size INTEGER NOT NULL, name TEXT NOT NULL);
CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, text TEXT NOT NULL);
CREATE TABLE custom_columns (id INTEGER PRIMARY KEY, label TEXT NOT NULL, name TEXT NOT NULL,
    datatype TEXT NOT NULL, mark_for_delete BOOL DEFAULT 0 NOT NULL, editable BOOL DEFAULT 1 NOT NULL,
    display TEXT DEFAULT '{}' NOT NULL, is_multiple BOOL DEFAULT 0 NOT NULL, normalized BOOL DEFAULT 1 NOT NULL);
CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, type TEXT NOT NULL, val TEXT NOT NULL);
"""

_TEST_BOOKS = [
    # (book_id, title, path, uuid)
    (1, "Test Book One", "test one", "uuid-1"),
    (2, "Test Book Two", "test two", "uuid-2"),
    (3, "Test Book Three", "test three", "uuid-3"),
]


def _create_test_calibre_library(lib_dir):
    """创建最小 calibre metadata.db 并插入测试书籍。"""
    db_file = os.path.join(lib_dir, "metadata.db")
    con = sqlite3.connect(db_file)
    con.executescript(_CALIBRE_SCHEMA)
    for book_id, title, path, uuid in _TEST_BOOKS:
        con.execute(
            "INSERT INTO books (id, title, sort, path, uuid, author_sort, last_modified) VALUES (?,?,?,?,?,?,?)",
            (book_id, title, title, path, uuid, "Author, Test", "2024-01-01"))
    con.execute("INSERT INTO authors (id, name, sort) VALUES (1, 'Test Author', 'Author, Test')")
    for book_id, _, _, _ in _TEST_BOOKS:
        con.execute("INSERT INTO books_authors_link (book, author) VALUES (?, 1)", (book_id,))
        con.execute(
            "INSERT INTO data (book, format, uncompressed_size, name) VALUES (?, 'EPUB', 100, ?)",
            (book_id, "test"))
    con.commit()
    con.close()
    return db_file


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """创建完整初始化（但无后台线程）的 Flask 测试应用。"""
    tmp_dir = str(tmp_path_factory.mktemp("cw-test"))
    app_db_path = os.path.join(tmp_dir, "app.db")
    gdrive_db_path = os.path.join(tmp_dir, "gdrive.db")
    lib_dir = os.path.join(tmp_dir, "calibre-library")
    os.makedirs(lib_dir, exist_ok=True)
    _create_test_calibre_library(lib_dir)

    # --- 按依赖顺序手动初始化（等价于 create_app 的核心步骤，去掉线程/更新器）---
    from cps import cli_param
    cli_param.settings_path = app_db_path
    cli_param.logpath = ""
    cli_param.gd_path = gdrive_db_path

    from cps import ub, config_sql
    ub.init_db(app_db_path)
    encrypt_key, _error = config_sql.get_encryption_key(tmp_dir)
    config_sql.load_configuration(ub.session, encrypt_key)

    from cps import config, db as calibre_db_module
    config.init_config(ub.session, encrypt_key, cli_param)
    config.config_calibre_dir = lib_dir
    config.db_configured = True

    from cps import app as flask_app
    flask_app.secret_key = os.getenv("SECRET_KEY",
                                     config_sql.get_flask_session_key(ub.session))

    from cps import lm, csrf
    from flask_principal import Principal
    Principal(flask_app)
    lm.init_app(flask_app)
    lm.login_view = "web.login"
    lm.anonymous_user = ub.Anonymous
    lm.session_protection = "basic"

    calibre_db_module.CalibreDB.update_config(config, config.config_calibre_dir,
                                              cli_param.settings_path)

    from cps.web import web
    from cps.basic import basic
    from cps.admin import admi
    from cps.jinjia import jinjia
    from cps.about import about
    from cps.search import search
    from cps.shelf import shelf
    from cps.remotelogin import remotelogin
    from cps.tasks_status import tasks
    from cps.editbooks import editbook
    from cps.search_metadata import meta
    from cps.gdrive import gdrive
    try:
        from cps.oauth_bb import oauth
    except ImportError:
        oauth = None

    for bp in [search, tasks, web, basic, jinjia, about, shelf, admi,
               remotelogin, meta, gdrive, editbook]:
        flask_app.register_blueprint(bp)
    if oauth is not None:
        flask_app.register_blueprint(oauth)

    from cps.cw_babel import babel, get_locale
    if hasattr(babel, "localeselector"):
        babel.init_app(flask_app)
        babel.localeselector(get_locale)
    else:
        babel.init_app(flask_app, locale_selector=get_locale)

    csrf.init_app(flask_app)

    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
    )
    return flask_app


@pytest.fixture()
def client(app):
    """未登录的测试客户端。"""
    return app.test_client()


@pytest.fixture(scope="session")
def _admin_login_cache(app):
    """会话级：缓存一次 admin 登录的 Cookie（登录有限流，避免重复触发）。"""
    c = app.test_client()
    resp = c.post("/login", data={"username": "admin", "password": "admin123"})
    assert resp.status_code == 302, "admin 登录应当成功（302 重定向）"
    cookie = c.get_cookie("session")
    assert cookie is not None
    return cookie


@pytest.fixture()
def logged_in_client(app, _admin_login_cache):
    """以 admin 身份登录的测试客户端（复用会话级登录 Cookie）。"""
    c = app.test_client()
    c.set_cookie("session", _admin_login_cache.value, domain="localhost")
    return c


# --------------------------------------------------------------------------------------
# Session 清理夹具
# --------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_ub_session(app):
    """每个测试结束后清理 ub.session，避免跨测试污染。"""
    yield
    from cps import ub as ub_module
    try:
        ub_module.session.rollback()
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# 用户/数据夹具
# --------------------------------------------------------------------------------------

@pytest.fixture()
def admin_user(app):
    """返回 admin 用户对象。"""
    from cps import ub as ub_module
    return ub_module.session.query(ub_module.User).filter(
        ub_module.User.name == "admin").first()


@pytest.fixture()
def fresh_bookmark(app):
    """创建并返回一个 Bookmark 记录，测试结束后删除。"""
    from cps import ub as ub_module
    bookmark = ub_module.Bookmark(
        user_id=1, book_id=12345, format="EPUB", bookmark_key="epubcfi(/6/4)")
    ub_module.session.merge(bookmark)
    ub_module.session_commit()
    yield bookmark
    ub_module.session.query(ub_module.Bookmark).filter(
        ub_module.Bookmark.book_id == 12345,
        ub_module.Bookmark.user_id == 1).delete()
    ub_module.session_commit()
