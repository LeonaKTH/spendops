"""G4 P0 防护测试：演示数据重置脚本的安全性（库名校验、确认、禁止硬编码密码）。"""

from __future__ import annotations

import os

import pytest

from scripts.generate_demo_data import _validate_reset_target


def test_reset_target_rejects_main_db():
    for db in ("spendops", "spendops_test", "postgres"):
        with pytest.raises(ValueError, match="受保护"):
            _validate_reset_target(f"postgresql+asyncpg://u:p@127.0.0.1:5433/{db}")


def test_reset_target_rejects_non_dedicated_db():
    with pytest.raises(ValueError, match="_demo/_test/_perf"):
        _validate_reset_target("postgresql+asyncpg://u:p@127.0.0.1:5433/some_other_db")


def test_reset_target_accepts_dedicated_db():
    for db in ("spendops_perf", "spendops_demo", "spendops_extra_test"):
        name = _validate_reset_target(f"postgresql+asyncpg://u:p@127.0.0.1:5433/{db}")
        assert name == db


def test_no_hardcoded_password_in_source():
    """源码中不得硬编码数据库管理员密码（RESET_URL 无默认值）。"""
    import scripts.generate_demo_data as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "spendops_dev_pw" not in source
    assert "RESET_URL = os.environ.get" in source
    assert '""' in source  # 默认值为空字符串
