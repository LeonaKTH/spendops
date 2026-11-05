import pytest

from app.services.query import SqlValidationError, validate_readonly_sql

ALLOWED = {"ds.t_bills", "ds.t_quotas"}


def test_select_is_allowed_and_gets_limit():
    sql = validate_readonly_sql(
        "SELECT supplier, SUM(amount) FROM ds.t_bills GROUP BY 1",
        ALLOWED,
    )
    assert "LIMIT 500" in sql.upper()


def test_existing_limit_is_kept():
    sql = validate_readonly_sql("SELECT * FROM ds.t_bills LIMIT 10", ALLOWED)
    assert "LIMIT 10" in sql.upper()
    assert "LIMIT 500" not in sql.upper()


def test_oversized_limit_is_capped():
    # 显式超大 LIMIT 必须被上界约束，防止绕过行数限制。
    sql = validate_readonly_sql("SELECT * FROM ds.t_bills LIMIT 999999", ALLOWED)
    assert "LIMIT 500" in sql.upper()
    assert "999999" not in sql.upper()


def test_limit_all_is_capped():
    # LIMIT ALL 表示无界，必须强制安全上限。
    sql = validate_readonly_sql("SELECT * FROM ds.t_bills LIMIT ALL", ALLOWED)
    assert "LIMIT 500" in sql.upper()


def test_join_between_registered_tables_is_allowed():
    sql = validate_readonly_sql(
        """
        SELECT b.supplier, q.quota
        FROM ds.t_bills AS b
        JOIN ds.t_quotas AS q ON q.supplier = b.supplier
        """,
        ALLOWED,
    )
    assert "JOIN" in sql.upper()


def test_cte_is_allowed():
    sql = validate_readonly_sql(
        """
        WITH monthly AS (
            SELECT date_trunc('month', bill_date) AS month, SUM(amount) AS amount
            FROM ds.t_bills
            GROUP BY 1
        )
        SELECT month, amount FROM monthly
        """,
        ALLOWED,
    )
    assert "WITH" in sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ds.t_bills SET amount = 0",
        "DELETE FROM ds.t_bills",
        "INSERT INTO ds.t_bills (amount) VALUES (1)",
        "DROP TABLE ds.t_bills",
        "CREATE TABLE ds.t_new (id int)",
    ],
)
def test_write_statements_are_rejected(sql: str):
    with pytest.raises(SqlValidationError):
        validate_readonly_sql(sql, ALLOWED)


def test_multiple_statements_are_rejected():
    with pytest.raises(SqlValidationError, match="一条"):
        validate_readonly_sql("SELECT * FROM ds.t_bills; DROP TABLE ds.t_bills", ALLOWED)


def test_unregistered_table_is_rejected():
    with pytest.raises(SqlValidationError, match="未注册"):
        validate_readonly_sql("SELECT * FROM ds.t_secret", ALLOWED)


def test_missing_ds_schema_is_rejected():
    with pytest.raises(SqlValidationError, match="ds"):
        validate_readonly_sql("SELECT * FROM t_bills", ALLOWED)


def test_cross_database_query_is_rejected():
    with pytest.raises(SqlValidationError, match="跨库"):
        validate_readonly_sql("SELECT * FROM other.ds.t_bills", ALLOWED)


def test_dangerous_function_is_rejected():
    with pytest.raises(SqlValidationError, match="pg_sleep"):
        validate_readonly_sql("SELECT pg_sleep(1)", ALLOWED)


def test_empty_sql_is_rejected():
    with pytest.raises(SqlValidationError, match="没有生成"):
        validate_readonly_sql("   ", ALLOWED)
