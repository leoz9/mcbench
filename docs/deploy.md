# 部署指南 / Deployment

架构：**静态前端**（GitHub Pages 和/或 Cloudflare Pages）+ **轻量后端 API**（FastAPI + SQLite，Docker，在你的 VPS 上，经 Cloudflare Tunnel 暴露为 `api.<domain>`，**不开放任何入站端口**）。
后端不可用时，前端自动回退到 `web/data/*.json` 静态数据，提交与投票按钮禁用并显示提示。

## 1. 前端

### GitHub Pages（已启用）
`.github/workflows/pages.yml` 在 push 到 `main` 时发布 `web/`。

### Cloudflare Pages
```bash
npm i -g wrangler && wrangler login
wrangler pages project create mcbench --production-branch main   # 仅首次
wrangler pages deploy                                            # 读取 wrangler.toml：pages_build_output_dir = "web"
```
或在 Cloudflare 控制台 → Workers & Pages → Create → Pages → 连接 GitHub 仓库：Framework = None，Build command 留空，Build output directory = `web`。
`web/_headers` 提供安全头与缓存策略。

### 指向 API
编辑 `web/config.js`：
```js
window.MCBENCH_CONFIG = { apiBase: 'https://api.<your-domain>' };
```
留空 = 纯静态模式。临时测试可用 `?api=https://...` 覆盖。

## 2. 后端（VPS）

前提：Ubuntu 22.04+/Debian 12，Docker + compose plugin，域名已托管在 Cloudflare。

```bash
# 2.1 代码
sudo mkdir -p /opt && cd /opt && sudo git clone https://github.com/leoz9/mcbench.git && sudo chown -R $USER mcbench && cd mcbench

# 2.2 配置（不要提交 .env）
cp server/.env.example server/.env
python3 -c "import secrets;print('ADMIN_TOKEN='+secrets.token_hex(32))"
python3 -c "from cryptography.fernet import Fernet;print('SECRET_KEY='+Fernet.generate_key().decode())"   # 或在容器里生成
# 把上面两个值和 ALLOWED_ORIGINS（如 https://cv.leozto.sbs,https://mcbench.pages.dev）写进 server/.env

# 2.3 Cloudflare Tunnel（在 VPS 上，一次性）
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cf.deb && sudo dpkg -i cf.deb
cloudflared tunnel login                       # 浏览器授权你的域名
cloudflared tunnel create mcbench-api          # 输出 TUNNEL_UUID，并生成 ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns mcbench-api api.<your-domain>
cp ~/.cloudflared/<UUID>.json server/deploy/cloudflared/
cp server/deploy/cloudflared/config.yml.example server/deploy/cloudflared/config.yml   # 填 UUID 与 hostname
chmod 600 server/deploy/cloudflared/*.json

# 2.4 启动（compose 不映射任何宿主端口）
docker compose -f server/docker-compose.yml --env-file server/.env up -d --build
docker compose -f server/docker-compose.yml logs -f api
curl https://api.<your-domain>/api/health
```

防火墙：`sudo ufw default deny incoming && sudo ufw allow OpenSSH && sudo ufw enable`（无需开放 80/443）。

可选 Cloudflare 加固：WAF → Rate limiting rule（`/api/votes`、`/api/submissions`）；Bot Fight Mode；
SSL/TLS = Full (strict)。

### 更新
```bash
cd /opt/mcbench && git pull && docker compose -f server/docker-compose.yml up -d --build
```
官方榜单数据 `web/data` 以只读卷挂载，`git pull` 后立即生效；社区提交保存在 `mcbench-data` 卷中。

### 每日备份
```bash
crontab -e
15 4 * * * /opt/mcbench/server/scripts/backup.sh >> /var/log/mcbench-backup.log 2>&1
```
`BACKUP_TARGET=github`（推到私有备份仓库，保留 14 份；VPS 需配置 deploy key）或 `r2`（需 `aws` CLI 及 `AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY` 环境变量，`R2_ENDPOINT/R2_BUCKET`）或 `none`（本地 `server/backups/`）。备份中的 API key 字段一律清空。

## 3. API 摘要
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查与队列长度 |
| GET | `/api/leaderboard` | 官方榜 + 社区提交（`community:true, verified:false`）|
| GET | `/api/traces/{hard\|core}/{model}/{task}` | 社区提交的轨迹 |
| POST | `/api/submissions` | 提交 OpenAI/Anthropic 兼容端点，入队离线评测 |
| GET | `/api/submissions/{id}` | 状态 / 排队位置 |
| POST | `/api/votes` | 匿名对战投票 |
| GET | `/api/votes/ratings` | 社区 Elo |
| GET/POST | `/api/admin/...` | `Authorization: Bearer $ADMIN_TOKEN`：列表、hide/show/requeue |

## 4. 安全设计
- **Key**：仅以 Fernet（`SECRET_KEY`）加密暂存于 SQLite，评测子进程通过环境变量拿到，结束（成功/失败）后立即清空；422 校验错误不回显请求体；评测日志中出现的 key 会被替换为 `***`；备份不含 key。
- **SSRF**：base_url 必须 https 且解析结果不能是内网/回环/保留地址。
- **限流/反刷**：每 IP（`CF-Connecting-IP`，哈希存储）提交 3 次/小时、投票 10 次/分钟 & 300 次/天；同一 IP 对同一题同一对模型 24h 只能投一次（A/B 交换也算同一对）；honeypot 字段；要求 UA；队列上限 `MAX_QUEUE`。
- **CORS** 仅允许 `ALLOWED_ORIGINS`；请求体 >16KB 拒绝；容器以非 root 运行；无对外端口。
- **评测只在离线冻结快照**上进行，不连接真实点餐服务，不会下单。

## 5. 本地开发
```bash
pip install -e . -r server/requirements.txt
cd server && ALLOW_SCRIPTED=1 ALLOWED_ORIGINS=http://localhost:8000 PYTHONPATH=..:. uvicorn app.main:app --port 8787
python -m http.server -d ../web 8000   # 打开 http://localhost:8000/?api=http://localhost:8787
pytest -q server/tests
```
`ALLOW_SCRIPTED=1` 允许提交脚本代理（`provider: scripted`, `model: demo-planner|demo-greedy|demo-hasty`）做端到端测试。

## 6. 当前线上部署（2026-10-16）
- 站点：https://mcbench.velaios.com（Cloudflare Pages 项目 `mcbench`，`.github/workflows/cloudflare-pages.yml` 在 push `web/**` 时自动部署；仓库 secrets `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`）。备用：https://mcbench.pages.dev；GitHub Pages 保留为镜像。
- API：https://mcbench-api.velaios.com（命名隧道 `mcbench-api`，远程管理 ingress → `http://api:8787`；cloudflared 以 `TUNNEL_TOKEN` 运行在 compose 中）。
  `api.mcbench.velaios.com` 的 DNS/ingress 也已配置，但它是二级子域，Cloudflare 免费 Universal SSL 不覆盖（需 Advanced Certificate Manager 或 Total TLS），因此前端使用 `mcbench-api.velaios.com`。
- VPS：`/opt/mcbench`，`/etc/cron.d/mcbench`（每 15 分钟 `git pull` 同步官方榜单数据；每天 04:15 本地备份到 `server/backups/`，key 字段清空）。
