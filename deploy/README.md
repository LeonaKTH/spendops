# 服务器部署手册

目标：把 ProcureBI 部署到一台公网 Linux 服务器，其他人用浏览器访问 `http://<公网 IP>`。
架构：`nginx（静态站 + /api 反向代理）→ FastAPI → PostgreSQL / Redis`，全部由 Docker Compose 管理，只对外暴露 80 端口。

> 本手册假设你已经有一台公网 Linux 服务器。下面的示例 IP `198.51.100.10` 请替换成你自己的公网 IP。

---

## 0. 先处理账号安全

新服务器不要使用简单密码，也不要把密码贴到聊天、文档或代码里。

1. 登录阿里云控制台 → ECS → 实例 → 重置实例密码（改完重启生效）；
2. 推荐改用 SSH 密钥登录，并在 `/etc/ssh/sshd_config` 中关闭 `PasswordAuthentication`；
3. 安全组 22 端口尽量只放行自己的 IP。

建议（可选）：

```bash
# 新建一个日常使用的账号，减少直接用 root 操作
adduser deploy
usermod -aG wheel deploy        # Debian/Ubuntu 用 sudo 组：usermod -aG sudo deploy
```

SSH 密钥登录更安全，但不是本项目的必需步骤。

---

## 1. 放通安全组端口

阿里云控制台 → ECS → 安全组 → 入方向规则：

| 端口 | 来源 | 用途 |
|---|---|---|
| 22/tcp | 你的公网 IP（尽量不收窄为 0.0.0.0/0） | SSH |
| 80/tcp | 0.0.0.0/0 | 网站 |

**不要**放通 5432（PostgreSQL）、6379（Redis）、8000（FastAPI）。生产 compose 只把 80 映射出来。

---

## 2. 安装 Docker

SSH 登录服务器：

```bash
ssh root@198.51.100.10     # 换成你的公网 IP
cat /etc/os-release        # 确认系统版本
```

Ubuntu / Debian：

```bash
apt update
apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version
```

Alibaba Cloud Linux / CentOS：

```bash
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
```

> **Alibaba Cloud Linux 4**：系统的 `$releasever` 是 `4`，Docker 官方 CentOS 仓库没有这个目录，`dnf install` 可能报 404。先执行：
>
> ```bash
> sed -i 's|\$releasever|9|g' /etc/yum.repos.d/docker-ce.repo
> ```
>
> 再重新安装即可（AL4 与 RHEL 9 兼容）。

如果服务器在国内，拉取镜像可能很慢或失败。在阿里云控制台打开「容器镜像服务 → 镜像加速器」，把分配的地址写进 `/etc/docker/daemon.json`：

```json
{
  "registry-mirrors": ["https://<你的加速器地址>.mirror.aliyuncs.com"]
}
```

```bash
systemctl restart docker
```

内存小于 2 GB 时，构建前端镜像容易 OOM，建议先加 2 GB swap：

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 3. 上传代码

在**你自己的 Windows 电脑**上，项目根目录执行（Git Bash）：

```bash
tar --exclude=node_modules --exclude=.venv --exclude=tools --exclude=.git \
    --exclude=dist --exclude=.env --exclude=.env.local \
    -czf procurebi.tar.gz \
    backend frontend sample_data scripts deploy docker-compose.prod.yml .env.example .dockerignore

scp procurebi.tar.gz root@198.51.100.10:/root/     # 换成你的公网 IP
```

在服务器上解压：

```bash
mkdir -p /opt/procurebi
tar -xzf /root/procurebi.tar.gz -C /opt/procurebi
cd /opt/procurebi
```

> `.env` 不会被上传，密钥需要在服务器上单独填写。

---

## 4. 配置服务器环境变量

```bash
cd /opt/procurebi
cp .env.example .env.prod
chmod 600 .env.prod
```

生成两个随机值：

```bash
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
openssl rand -hex 24        # 用作 POSTGRES_PASSWORD
```

编辑 `vim .env.prod`，至少修改这些项：

```dotenv
APP_ENV=prod

# 数据库（compose 会用这两个值创建数据库）
POSTGRES_USER=bi
POSTGRES_PASSWORD=<上面生成的随机值>
POSTGRES_DB=bi

# 大模型
LLM_API_KEY=sk-你的-deepseek-key
LLM_MOCK=false

# 登录
JWT_SECRET=<上面生成的随机值>
JWT_EXPIRE_MINUTES=720
AUTH_COOKIE_SECURE=false        # 目前是 HTTP；上 HTTPS 后改成 true
AUTH_COOKIE_SAMESITE=lax

# 首次启动创建的管理员，务必换成强密码
ADMIN_BOOTSTRAP=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<至少 12 位的强密码>

# 通过 nginx 反向代理，审计日志需要真实 IP
TRUST_PROXY_HEADERS=true
```

说明：

- 数据库密码建议只用字母和数字，避免 `@ : / ?` 破坏 `DATABASE_URL`。
- `ADMIN_PASSWORD` 只在数据库中**没有任何管理员**时生效；首次启动后改这里不会改已有账号的密码。
- 如果把 `.env.prod` 弄丢，JWT_SECRET 变化会让所有人重新登录，其他配置需要重填；请单独备份。

---

## 5. 处理 80 端口冲突（重要）

很多阿里云镜像预装了 nginx，80 端口会显示 `Welcome to nginx!`。先确认它有没有在跑其他站点：

```bash
ss -lntp | grep ':80 '
systemctl status nginx --no-pager
ls /etc/nginx/sites-enabled/
ls /var/www/
```

如果只是默认欢迎页，二选一：

**方案 A（推荐，最简单）**：停掉宿主 nginx，让容器接管 80。

```bash
systemctl stop nginx
systemctl disable nginx
```

**方案 B**：保留宿主 nginx，容器改用 127.0.0.1:8080，再由宿主 nginx 转发。
把 [docker-compose.prod.yml](../docker-compose.prod.yml) 中 `web.ports` 改为 `"127.0.0.1:8080:80"`，然后：

```bash
cp deploy/host-nginx-procurebi.conf /etc/nginx/sites-available/procurebi
ln -sf /etc/nginx/sites-available/procurebi /etc/nginx/sites-enabled/procurebi
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

如果 80 上已经有别的网站在运行，**不要动它**，用方案 B。

---

## 5.1 构建并启动

```bash
cd /opt/procurebi
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
```

首次启动时后端会自动执行 `alembic upgrade head` 建表。看到 `Application startup complete` 即可。

检查：

```bash
curl http://127.0.0.1/api/v1/health
curl -I http://127.0.0.1/
```

浏览器打开 `http://<你的公网 IP>`，用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。
首次登录会提示修改密码，请立即修改；然后在「后台管理 → 用户管理」给朋友创建 `viewer` 账号。

---

## 6. 导入示例数据（可选）

数据库在服务器上是空的。可以在网页「数据接入」里手动上传，也可以在本地电脑一条命令批量导入：

```bash
cd D:/ai-data-agent-bi
NO_PROXY='*' backend/.venv/Scripts/python.exe scripts/seed_demo_data.py \
    --base-url http://<你的公网 IP> \
    --username admin \
    --password '<你的管理员密码>'
```

脚本会跳过服务器上已存在的同名文件，因此可以重复执行。
导入后报表默认使用 2026 账期，问数 Agent 也就能正常工作了。

> LLM 请求由服务器发出，服务器必须能访问 `https://api.deepseek.com`。

---

## 7. 日常运维

```bash
cd /opt/procurebi
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"

$COMPOSE ps                 # 状态
$COMPOSE logs -f backend    # 后端日志
$COMPOSE restart backend    # 重启后端
$COMPOSE down               # 停止（数据卷保留）
$COMPOSE up -d --build      # 更新代码后重新构建
```

更新代码：本地重新打包 → `scp` → 服务器解压覆盖 → `up -d --build`。数据库数据在 Docker 卷 `pgdata` 中，不会因重建镜像丢失。

### 备份与恢复

```bash
# 备份数据库（在服务器上）
$COMPOSE exec -T db pg_dump -U bi bi > /root/procurebi-$(date +%F).sql

# 恢复
cat /root/procurebi-2026-10-21.sql | $COMPOSE exec -T db psql -U bi bi
```

同时备份 `/opt/procurebi/.env.prod`。

### 忘记管理员密码

```bash
cd /opt/procurebi
docker compose --env-file .env.prod -f docker-compose.prod.yml \
    exec backend python -m app.cli reset-password admin
```

按提示输入新密码（不会留在 shell 历史里）。重置后旧会话立即失效。

### 彻底重置（会删除所有数据）

```bash
$COMPOSE down -v
$COMPOSE up -d --build
```

---

## 8. HTTPS（可选）

目前用「IP + HTTP」访问，浏览器会提示「不安全」，登录密码以明文经过网络传输。
自己和朋友演示够用，但不要把它当成正式系统。

有域名后可以升级：

1. 域名解析 A 记录指向服务器公网 IP；
2. 在 compose 中加一个 Caddy 服务代替 nginx 的 80 端口，或给 nginx 挂载证书并监听 443；
3. 把 `.env.prod` 里的 `AUTH_COOKIE_SECURE=true`，重启后端。

注意：阿里云中国大陆节点使用域名访问需要完成 ICP 备案；只用 IP 访问不需要。

---

## 9. 常见问题

| 现象 | 排查 |
|---|---|
| 浏览器打不开 | 安全组是否放通 80；`$COMPOSE ps` 中 web 是否 Up；`ss -lntp \| grep :80` 看端口占用；系统防火墙 `systemctl status firewalld`，必要时 `firewall-cmd --add-port=80/tcp --permanent && firewall-cmd --reload` |
| 502 Bad Gateway | `$COMPOSE logs backend`；多为数据库未启动或迁移失败 |
| 登录一直失败 | 确认 `ADMIN_PASSWORD` 是首次启动时使用的值；用第 7 节命令重置 |
| 上传大文件 413 | 同时调大 `deploy/nginx.conf` 的 `client_max_body_size` 和 `.env.prod` 的 `UPLOAD_MAX_MB`，重建 web 与 backend |
| 问数一直报 LLM 错误 | 服务器出网是否正常；`LLM_API_KEY` 是否有效；查看 backend 日志 |
| 构建镜像很慢 / 失败 | 配置镜像加速器；确认内存与 swap；前端依赖默认走 npmmirror，可在 compose 的 build args 里改 `NPM_REGISTRY` |
| 修改 `.env.prod` 不生效 | 需要 `$COMPOSE up -d` 重建容器；`restart` 不会重新读取 env_file |
