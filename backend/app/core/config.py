from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ProcureBI"
    app_env: str = "dev"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "postgresql+asyncpg://bi:bi@localhost:5432/bi"
    # 迁移专用连接（DDL 权限，如 spendops_migrator）。留空时复用 database_url。
    migrate_database_url: str = ""
    # 测试专用连接（与演示库分离）。留空时测试连接默认不可用，防止误连演示库。
    test_database_url: str = ""
    # 只读角色连接（用于 SQL 安全测试）。留空时只读角色测试跳过。
    ro_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model_sql: str = "deepseek-chat"
    llm_model_fast: str = "deepseek-chat"
    llm_mock: bool = False

    upload_max_mb: int = 20
    query_row_limit: int = 500
    query_timeout_seconds: int = 10

    # 报表多币种：账单中的 USD 金额按该汇率折算为人民币。
    fx_usd_cny: float = 7.2
    # 公开分享端点限流，防止泄露的链接被无限抓取。
    share_rate_max_requests: int = 60
    share_rate_window_seconds: int = 300

    # 认证：JWT 放在 HttpOnly Cookie 中，避免前端脚本读取。
    jwt_secret: str = ""
    jwt_expire_minutes: int = 720
    jwt_leeway_seconds: int = 10
    auth_cookie_name: str = "procurebi_session"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    bcrypt_rounds: int = 12

    # 首次启动时创建管理员；只在数据库中不存在管理员时生效。
    admin_bootstrap: bool = True
    admin_username: str = "admin"
    admin_password: str = ""

    # 登录失败限流，按 (用户名, IP) 与 IP 两个维度计数。
    login_max_attempts: int = 5
    login_ip_max_attempts: int = 20
    login_lockout_seconds: int = 300
    trust_proxy_headers: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
