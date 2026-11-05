from app.api.v1.schemas import AdminUserCreateIn
from app.main import validation_message


def test_short_password_message_is_chinese():
    message = validation_message(
        {
            "type": "string_too_short",
            "loc": ("body", "password"),
            "msg": "String should have at least 8 characters",
            "ctx": {"min_length": 8},
        }
    )
    assert message == "密码长度不足（至少 8 个字符）。"


def test_missing_field_message_is_chinese():
    message = validation_message(
        {"type": "missing", "loc": ("body", "username"), "msg": "Field required"}
    )
    assert message == "缺少必填字段：用户名。"


def test_value_error_keeps_chinese_detail():
    message = validation_message(
        {
            "type": "value_error",
            "loc": ("body", "new_password"),
            "msg": "Value error, 新密码至少 8 个字符。",
        }
    )
    assert message == "新密码至少 8 个字符。"


def test_unknown_field_uses_raw_name():
    message = validation_message(
        {
            "type": "string_too_long",
            "loc": ("body", "notes"),
            "ctx": {"max_length": 10},
        }
    )
    assert message == "notes过长（最多 10 个字符）。"


def test_create_user_schema_leaves_password_rules_to_service():
    # 7 位密码应通过 Pydantic，由 users.validate_password 返回中文提示。
    payload = AdminUserCreateIn(username="abc", password="1234567")
    assert payload.password == "1234567"
