"""运维命令。在服务器容器内执行：

    docker compose --env-file .env.prod -f docker-compose.prod.yml \
        exec backend python -m app.cli reset-password admin

密码不写在命令行时，会交互式读取，避免留在 shell 历史里。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.db.session import SessionLocal
from app.services.users import get_user_by_username, normalize_username, reset_password


async def _reset_password(username: str, password: str) -> int:
    async with SessionLocal() as session:
        async with session.begin():
            user = await get_user_by_username(session, username)
            if user is None:
                print(f"用户不存在：{normalize_username(username)}", file=sys.stderr)
                return 1
            try:
                await reset_password(session, user, password)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(
                f"已重置 {user.username} 的密码；该账号的旧会话立即失效，"
                "下次登录后需要修改密码。"
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="procurebi", description="ProcureBI 运维命令")
    sub = parser.add_subparsers(dest="command", required=True)

    reset = sub.add_parser("reset-password", help="重置指定账号的密码")
    reset.add_argument("username", help="用户名")
    reset.add_argument("--password", help="新密码；省略则交互式输入")

    args = parser.parse_args()

    if args.command == "reset-password":
        password = args.password
        if not password:
            password = getpass.getpass("新密码：")
            confirm = getpass.getpass("确认新密码：")
            if password != confirm:
                print("两次输入的密码不一致。", file=sys.stderr)
                return 1
        return asyncio.run(_reset_password(args.username, password))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
