# token-usage-dash

[English](README.md) | **简体中文**

将 Claude、OpenAI Codex 与 OpenCode Go 的订阅套餐用量推送到 [dot.mindreset.tech](https://dot.mindreset.tech) 墨水屏，渲染为一张 296×152 的图片。

![墨水屏上的用量展示](docs/preview.jpg)

## 展示内容

- **Claude** — 5 小时与 7 天用量（已用百分比、剩余百分比、重置倒计时）
- **OpenAI Codex** — 5 小时与每周用量
- **OpenCode Go** — 5 小时、每周与每月用量

## 安装配置

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp .env.sample .env
```

编辑 `.env`，填入你的凭据：

| 变量 | 说明 |
|-----|-------------|
| `QUOTE_API_KEY` | dot.mindreset.tech 的 Bearer Token |
| `QUOTE_DEVICE_ID` | 设备序列号 |
| `CLAUDE_ENABLED` | 设为 `false` 可跳过 Claude 抓取（默认：`true`） |
| `OPENAI_ENABLED` | 设为 `false` 可跳过 OpenAI 抓取（默认：`true`） |
| `OPENCODE_ENABLED` | 设为 `false` 可跳过 OpenCode Go 抓取（默认：`true`） |
| `UPDATE_INTERVAL` | 循环模式下两次更新的间隔秒数（默认：`1800`） |
| `QUOTE_LINK` | 可选，Image API 内容的 NFC 跳转链接 |
| `QUOTE_BORDER` | 可选，屏幕边框颜色，`0` 白色、`1` 黑色（默认：`0`） |
| `QUOTE_DITHER_TYPE` | 可选，抖动模式：`NONE`、`DIFFUSION` 或 `ORDERED`（默认：`NONE`） |
| `QUOTE_DITHER_KERNEL` | 可选，抖动核，例如 `FLOYD_STEINBERG` |
| `QUOTE_TASK_KEY` | 可选，存在多个 Image API 内容时指定目标任务 key |
| `QUOTE_TASK_ALIAS` | 可选，设备任务列表中显示的别名 |
| `CODEX_ACCESS_TOKEN` | 可选，覆盖 Codex OAuth Token（默认读取 `~/.codex/auth.json`） |
| `CODEX_REFRESH_TOKEN` | 可选，Codex refresh token，用于自动续期 |
| `CODEX_ACCOUNT_ID` | 可选，覆盖 Codex 账户 ID |
| `CODEX_TOKEN_CACHE` | 可选，Codex 续期 token 的缓存路径（默认 `~/.cache/token-usage-dash/codex_token.json`） |
| `OPENCODE_GO_API_KEY` | 可选，覆盖 OpenCode Go API Key（默认读取 `~/.local/share/opencode/auth.json`） |

### 3. Claude 授权

Claude 凭据会自动从 `~/.claude/.credentials.json` 读取（使用 [Claude Code](https://claude.ai/code) 登录后即会生成该文件）。

### 4. OpenAI Codex 授权

Codex 凭据会自动从 `~/.codex/auth.json` 读取（使用 [Codex](https://github.com/openai/codex) 登录后即会生成该文件）。先运行一次 `codex` 完成登录。

也可以直接在 `.env` 中设置 `CODEX_ACCESS_TOKEN` 手动提供 Token；同时配置 `CODEX_REFRESH_TOKEN` 可让容器自动续期，无需再手动维护。

### 5. OpenCode Go 授权

OpenCode Go 是面向开源编程模型的 10 美元/月订阅。前往 [opencode.ai/auth](https://opencode.ai/auth) 订阅，然后在 [OpenCode](https://opencode.ai) 中执行 `/connect` → **OpenCode Go** 并粘贴 API Key。

Key 会自动从 `~/.local/share/opencode/auth.json` 中的 `opencode-go` 条目读取。也可以直接在 `.env` 中设置 `OPENCODE_GO_API_KEY` 手动提供。

用量分为三个窗口，均为「占该模型每月额度上限的百分比」：5 小时（上限的 20%）、每周（50%）、每月（100%）。

### 6. 在 Content Studio 中添加 Image API 内容

在 dot.mindreset.tech App 中，为你的设备添加一个 **Image API** 内容位。脚本会向该内容位推送图片。如果你有多个 Image API 内容位，请将 `QUOTE_TASK_KEY` 设置为要更新的那个内容位的 task key。

如果 API 调用成功但设备上仍显示图片占位符，说明 Content Studio 中的内容位可能已失效或绑定错误。请删除原有的 Image API 内容位，为设备当前布局或播放列表重新添加一个 Image API 内容位，然后再次运行 `uv run display.py --preview`。

## 使用方法

```bash
# 单次更新
uv run display.py

# 每 30 分钟循环更新
uv run display.py --loop

# 自定义间隔循环，并保存预览图
uv run display.py --loop --interval 900 --preview

# 仅生成预览图，不推送到设备
uv run render.py   # 保存至 /tmp/usage_preview.png

# 仅在终端打印用量
uv run usage.py
uv run usage.py --claude-only
uv run usage.py --openai-only
uv run usage.py --opencode-only
```

## Docker 部署

容器**完全通过环境变量读取凭据**，无需映射宿主机上的任何凭据文件。

### 1. 把凭据写入 `.env`

```bash
cp .env.sample .env
```

```dotenv
QUOTE_API_KEY=dot_app_...
QUOTE_DEVICE_ID=XXXXXXXXXXXX

# Claude（可选，不配置则设 CLAUDE_ENABLED=false 跳过）
CLAUDE_ACCESS_TOKEN=sk-ant-oat01-...
CLAUDE_REFRESH_TOKEN=sk-ant-ort01-...

# OpenAI Codex（可选，配置 CODEX_REFRESH_TOKEN 可自动续期）
CODEX_ACCESS_TOKEN=...
CODEX_REFRESH_TOKEN=...
CODEX_ACCOUNT_ID=...

# OpenCode Go（可选）
OPENCODE_GO_API_KEY=sk-...
```

各字段来源：

| 提供商 | 变量 | 取值位置 |
|---|---|---|
| Claude | `CLAUDE_ACCESS_TOKEN`、`CLAUDE_REFRESH_TOKEN` | `~/.claude/.credentials.json` 中的 `accessToken` / `refreshToken`（运行 `claude` 后生成） |
| Codex | `CODEX_ACCESS_TOKEN`、`CODEX_REFRESH_TOKEN`、`CODEX_ACCOUNT_ID` | `~/.codex/auth.json` 中的 `tokens.access_token` / `tokens.refresh_token` / `tokens.account_id`（运行 `codex` 后生成） |
| OpenCode Go | `OPENCODE_GO_API_KEY` | `~/.local/share/opencode/auth.json` 中的 `opencode-go.key` |

> Claude 与 Codex 的 access token 都会过期（Claude 约几小时，Codex 约 10 天）。配置对应的 refresh token 后容器会自动续期，续期结果保存在容器内的临时文件中，运行期间只在需要时刷新一次；容器重建后会基于 refresh token 重新刷新。若只配 access token，过期后需手动更新。
>
> Codex 对刷新有频率限制：接口会返回 `earliest_refresh_at`，早于该时间刷新会被拒绝。程序已遵循此限制，不会提前刷新。

### 2. 启动

```bash
# 默认循环模式，随宿主机自启
docker compose up -d

# 查看日志
docker compose logs -f
```

不使用 Compose 时：

```bash
docker build -t token-usage-dash .

# 循环模式（默认 CMD 即 --loop）
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  token-usage-dash

# 单次更新
docker run --rm --env-file .env token-usage-dash

# 仅在终端打印用量
docker run --rm --env-file .env --entrypoint python token-usage-dash usage.py
```

**无需映射任何目录**。凭据全部来自环境变量；程序唯一写入的文件是容器内的 token 续期缓存（以及使用 `--preview` 时的 `/tmp/usage_preview.png`）。

### 3. 时区与代理

**时区。** 镜像内已安装 `tzdata`，默认 `TZ=Asia/Shanghai`，用于控制图片头部显示的时间。可按部署环境覆盖：

```bash
docker run ... -e TZ=America/New_York token-usage-dash
```

使用 Compose 时，在 shell 或 `.env` 中设置 `TZ` 即可，compose 文件带默认值：

```yaml
TZ: "${TZ:-Asia/Shanghai}"
```

**代理。** `docker-compose.yml` 已把对外请求指向宿主机上的代理——当 Codex / Claude 接口无法直连时这是必需的：

```yaml
HTTP_PROXY: "${HTTP_PROXY_HOST:-http://host.docker.internal:7890}"
HTTPS_PROXY: "${HTTP_PROXY_HOST:-http://host.docker.internal:7890}"
NO_PROXY: "localhost,127.0.0.1,::1"
extra_hosts:
  - "host.docker.internal:host-gateway"
```

可用 `HTTP_PROXY_HOST` 改端口或地址，例如 `HTTP_PROXY_HOST=http://192.168.1.10:7890 docker compose up -d`。其中 `extra_hosts` 是让 Linux 上 `host.docker.internal` 能解析的关键（Docker Desktop 自带，无需配置）。若容器本身可直连，这些代理设置也无副作用。

直接用 `docker run` 时需显式传入：

```bash
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  -e TZ=Asia/Shanghai \
  -e HTTPS_PROXY=http://host.docker.internal:7890 \
  -e HTTP_PROXY=http://host.docker.internal:7890 \
  --add-host host.docker.internal:host-gateway \
  token-usage-dash --loop
```

### 4. 构建并推送 x86 镜像

部署到 amd64 服务器时，用 `build.sh` 构建并推送：

```bash
# 先设置你的仓库地址（也可直接改 build.sh 顶部的 REGISTRY）
export REGISTRY=registry.example.com/your-namespace/your-image

./build.sh                 # 构建 linux/amd64 并推送 :latest
./build.sh --tag v1.0      # 额外推送一个 tag
./build.sh --no-push       # 仅构建到本地 Docker
```

`build.sh` 里的仓库地址是占位符，未替换前会拒绝推送。可通过 `REGISTRY` 环境变量、`--registry` 参数，或直接编辑文件来设置。推送前需先执行 `docker login <你的仓库>`。在 x86 服务器上运行：

```bash
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  "$REGISTRY:latest" --loop
```

脚本额外处理了两件直接 `docker buildx build` 不会处理的事：

- **在 Apple Silicon 上交叉构建**：`--platform linux/amd64` 通过模拟构建出真正的 x86_64 镜像。
- **镜像仓库的 manifest 兼容性**：部分仓库（如阿里云 ACR）会拒绝 BuildKit 默认产出的带 provenance 证明的 OCI manifest list，报 `unknown manifest class for application/vnd.oci.empty.v1+json`。脚本改用 Docker media type 并关闭证明（`--provenance=false --sbom=false --output ...,oci-mediatypes=false`）。

如果你想保留一份写死真实仓库地址的本机脚本，请命名为 `build.local.sh`——`.gitignore` 已排除 `*.local.sh`，不会进入仓库。

## 文件说明

| 文件 | 用途 |
|------|---------|
| `usage.py` | 抓取 Claude、OpenAI Codex 与 OpenCode Go 的用量数据 |
| `render.py` | 渲染 296×152 的 PNG 图片 |
| `display.py` | 串联「抓取 → 渲染 → 推送到设备」流程 |
| `Dockerfile` | 容器镜像（纯环境变量驱动，无需映射凭据） |
| `docker-compose.yml` | Compose 服务定义（不挂载任何卷） |
| `build.sh` | 交叉构建 linux/amd64 并推送到你的仓库（占位地址） |

## 说明

- 三个提供商相互独立：任意一个抓取失败只会输出警告，不影响其余数据的渲染与推送。
- 当三个提供商同时有数据时，Claude 只展示 5 小时与 7 天两行（不含 7dS / 7dO 子额度行），以保证 296×152 画布能完整容纳三个分区。
