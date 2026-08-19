# -*- coding: utf-8 -*-
"""Bookmark 模型 progress_percent 字段 + 数据库迁移的 TDD 测试。"""

import os

from cps import ub


class TestBookmarkProgressColumn:
    """红色阶段：Bookmark 模型应具有 progress_percent (Float, nullable) 字段。"""

    def test_bookmark_model_has_progress_percent_column(self):
        col = ub.Bookmark.__table__.columns.get("progress_percent")
        assert col is not None, "Bookmark 模型缺少 progress_percent 列"
        assert col.nullable is True, "progress_percent 列应当 nullable"

    def test_bookmark_instance_accepts_progress_percent(self):
        bookmark = ub.Bookmark(user_id=1, book_id=1, format="EPUB",
                               bookmark_key="epubcfi(/6/4)",
                               progress_percent=42.5)
        assert bookmark.progress_percent == 42.5


class TestBookmarkMigration:
    """红色阶段：migrate_Database 应为旧数据库补齐 bookmark.progress_percent 列。

    注意：不调用 ub.init_db（它会替换全局 ub.session 指向测试临时库），
    而是复刻 init_db 的"已存在数据库"分支：create_all + migrate_Database。
    """

    @staticmethod
    def _migrate_legacy_db(db_file):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///{}".format(db_file), echo=False)
        legacy_session = sessionmaker(bind=engine)()
        ub.Base.metadata.create_all(engine)
        ub.migrate_Database(legacy_session)
        legacy_session.close()
        engine.dispose()

    def test_migrate_adds_progress_percent_to_existing_db(self, tmp_path):
        from sqlalchemy import create_engine, inspect, text

        db_file = str(tmp_path / "legacy_app.db")
        engine = create_engine("sqlite:///{}".format(db_file))
        # 模拟旧版 bookmark 表（无 progress_percent 列）
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE bookmark (id INTEGER PRIMARY KEY, user_id INTEGER, "
                "book_id INTEGER, format VARCHAR COLLATE NOCASE, bookmark_key VARCHAR)"))
            conn.commit()
        engine.dispose()

        self._migrate_legacy_db(db_file)

        check_engine = create_engine("sqlite:///{}".format(db_file))
        inspector = inspect(check_engine)
        columns = [c["name"] for c in inspector.get_columns("bookmark")]
        check_engine.dispose()
        assert "progress_percent" in columns, \
            "迁移后 bookmark 表应包含 progress_percent 列"

    def test_migrate_idempotent_when_column_exists(self, tmp_path):
        """列已存在时迁移不应报错（幂等）。"""
        from sqlalchemy import create_engine, inspect, text

        db_file = str(tmp_path / "legacy2_app.db")
        engine = create_engine("sqlite:///{}".format(db_file))
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE bookmark (id INTEGER PRIMARY KEY, user_id INTEGER, "
                "book_id INTEGER, format VARCHAR COLLATE NOCASE, bookmark_key VARCHAR, "
                "progress_percent FLOAT)"))
            conn.commit()
        engine.dispose()

        self._migrate_legacy_db(db_file)  # 不应抛出异常

        check_engine = create_engine("sqlite:///{}".format(db_file))
        inspector = inspect(check_engine)
        columns = [c["name"] for c in inspector.get_columns("bookmark")]
        check_engine.dispose()
        assert "progress_percent" in columns

    def test_migrate_preserves_existing_data(self, tmp_path):
        """迁移不得丢失 bookmark 表已有数据。"""
        from sqlalchemy import create_engine, text

        db_file = str(tmp_path / "legacy3_app.db")
        engine = create_engine("sqlite:///{}".format(db_file))
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE bookmark (id INTEGER PRIMARY KEY, user_id INTEGER, "
                "book_id INTEGER, format VARCHAR COLLATE NOCASE, bookmark_key VARCHAR)"))
            conn.execute(text(
                "INSERT INTO bookmark (user_id, book_id, format, bookmark_key) "
                "VALUES (1, 9, 'EPUB', 'epubcfi(/6/4)')"))
            conn.commit()
        engine.dispose()

        self._migrate_legacy_db(db_file)

        check_engine = create_engine("sqlite:///{}".format(db_file))
        with check_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT user_id, book_id, format, bookmark_key, progress_percent "
                "FROM bookmark")).fetchall()
        check_engine.dispose()
        assert len(rows) == 1
        assert rows[0] == (1, 9, "EPUB", "epubcfi(/6/4)", None)
