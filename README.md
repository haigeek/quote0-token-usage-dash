# token-usage-dash

**English** | [简体中文](README.zh-CN.md)

Pushes Claude, OpenAI Codex and OpenCode Go subscription plan usage to a [dot.mindreset.tech](https://dot.mindreset.tech) e-ink display as a 296×152 image.

![Token usage on e-ink display](docs/preview.jpg)

## What it shows

- **Claude** — 5-hour and 7-day utilization (% used, % left, time to reset)
- **OpenAI Codex** — 5-hour and weekly utilization
- **OpenCode Go** — 5-hour, weekly and monthly utilization

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure

```bash
cp .env.sample .env
```

Edit `.env` with your credentials:

| Key | Description |
|-----|-------------|
| `QUOTE_API_KEY` | Bearer token from dot.mindreset.tech |
| `QUOTE_DEVICE_ID` | Device serial number |
| `CLAUDE_ENABLED` | Set to `false` to skip Claude fetching (default: `true`) |
| `OPENAI_ENABLED` | Set to `false` to skip OpenAI fetching (default: `true`) |
| `OPENCODE_ENABLED` | Set to `false` to skip OpenCode Go fetching (default: `true`) |
| `UPDATE_INTERVAL` | Seconds between updates in loop mode (default: `1800`) |
| `QUOTE_LINK` | Optional NFC tap redirect URL for the Image API content |
| `QUOTE_BORDER` | Optional screen border color, `0` white or `1` black (default: `0`) |
| `QUOTE_DITHER_TYPE` | Optional dithering mode: `NONE`, `DIFFUSION`, or `ORDERED` (default: `NONE`) |
| `QUOTE_DITHER_KERNEL` | Optional dither kernel such as `FLOYD_STEINBERG` |
| `QUOTE_TASK_KEY` | Optional Image API task key when multiple Image API contents exist |
| `QUOTE_TASK_ALIAS` | Optional alias shown in the device task list |
| `CODEX_ACCESS_TOKEN` | Override Codex OAuth token (optional; default: read from `~/.codex/auth.json`) |
| `CODEX_REFRESH_TOKEN` | Codex refresh token, enables auto-renewal (optional) |
| `CODEX_ACCOUNT_ID` | Override Codex account ID (optional) |
| `CODEX_TOKEN_CACHE` | Path to cache refreshed Codex tokens (default: `~/.cache/token-usage-dash/codex_token.json`) |
| `OPENCODE_GO_API_KEY` | Override OpenCode Go API key (optional; default: read from `~/.local/share/opencode/auth.json`) |
| `CLAUDE_ACCESS_TOKEN` | Override Claude access token (optional; required for Docker) |
| `CLAUDE_REFRESH_TOKEN` | Claude refresh token, enables auto-renewal (optional) |
| `CLAUDE_EXPIRES_AT` | Claude access token expiry, epoch ms (optional) |
| `CLAUDE_TOKEN_CACHE` | Path to cache refreshed Claude tokens (default: `~/.cache/token-usage-dash/claude_token.json`) |

### 3. Claude auth

Claude credentials are read automatically from `~/.claude/.credentials.json` (created when you authenticate with [Claude Code](https://claude.ai/code)).

### 4. OpenAI Codex auth

Codex credentials are read automatically from `~/.codex/auth.json` (created when you authenticate with [Codex](https://github.com/openai/codex)). Run `codex` once to log in.

Alternatively, set `CODEX_ACCESS_TOKEN` in `.env` to supply the token directly.

### 5. OpenCode Go auth

OpenCode Go is a $10/month subscription for open coding models. Subscribe at [opencode.ai/auth](https://opencode.ai/auth), then run `/connect` → **OpenCode Go** in [OpenCode](https://opencode.ai) and paste your API key.

The key is read automatically from the `opencode-go` entry in `~/.local/share/opencode/auth.json`. Alternatively, set `OPENCODE_GO_API_KEY` in `.env` to supply it directly.

Usage covers three windows, each a percentage of the model's monthly dollar limit: 5-hour (20% of the limit), weekly (50%) and monthly (100%).

### 6. Add Image API content in Content Studio

In the dot.mindreset.tech app, add an **Image API** content slot to your device. The script targets this slot. If you have multiple Image API slots, set `QUOTE_TASK_KEY` to the task key for the slot you want to update.

If the API call succeeds but the device still shows an image placeholder, the Content Studio slot may be stale or misbound. Delete the existing Image API content slot, add a fresh Image API slot to the device's active layout or playlist, then run `uv run display.py --preview` again.

## Docker

The image runs with **environment variables only** — no host credential files need to be mounted.

### 1. Put your credentials in `.env`

```bash
cp .env.sample .env
```

```dotenv
QUOTE_API_KEY=dot_app_...
QUOTE_DEVICE_ID=XXXXXXXXXXXX

# Claude (optional — omit or set CLAUDE_ENABLED=false to skip)
CLAUDE_ACCESS_TOKEN=sk-ant-oat01-...
CLAUDE_REFRESH_TOKEN=sk-ant-ort01-...

# OpenAI Codex (optional — CODEX_REFRESH_TOKEN enables auto-renewal)
CODEX_ACCESS_TOKEN=...
CODEX_REFRESH_TOKEN=...
CODEX_ACCOUNT_ID=...

# OpenCode Go (optional)
OPENCODE_GO_API_KEY=sk-...
```

Where to find each value:

| Provider | Value | Where to get it |
|---|---|---|
| Claude | `CLAUDE_ACCESS_TOKEN`, `CLAUDE_REFRESH_TOKEN` | The `accessToken` / `refreshToken` fields in `~/.claude/.credentials.json` (created by `claude`) |
| Codex | `CODEX_ACCESS_TOKEN`, `CODEX_REFRESH_TOKEN`, `CODEX_ACCOUNT_ID` | The `tokens.access_token` / `tokens.refresh_token` / `tokens.account_id` fields in `~/.codex/auth.json` (created by `codex`) |
| OpenCode Go | `OPENCODE_GO_API_KEY` | The `opencode-go.key` field in `~/.local/share/opencode/auth.json` |

> Both Claude and Codex access tokens expire (Claude in hours, Codex in ~10 days). Supplying the matching refresh token lets the container renew them automatically. Renewed tokens are kept in files inside the container, so a running container only refreshes when needed; recreating the container just refreshes again from the refresh token. Without a refresh token you must update the access token manually when it expires.
>
> Codex rate-limits refreshes: the API returns `earliest_refresh_at`, and refreshing before then is rejected. The client honours this, so a token is never refreshed earlier than the server allows.

### 2. Run it

```bash
# Loop mode (default), restarting with the host
docker compose up -d

# Follow the logs
docker compose logs -f
```

Or without Compose:

```bash
docker build -t token-usage-dash .

# Loop (default CMD is --loop)
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  token-usage-dash

# One-shot update
docker run --rm --env-file .env token-usage-dash

# Print usage to the terminal
docker run --rm --env-file .env --entrypoint python token-usage-dash usage.py
```

No volumes are needed. Credentials come from the environment, and the only file the app writes is the in-container refreshed-token cache (and `/tmp/usage_preview.png` when using `--preview`).

### 3. Timezone and proxy

**Timezone.** The container ships `tzdata` and defaults to `TZ=Asia/Shanghai`, which controls the clock rendered in the image header. Override it per deployment:

```bash
docker run ... -e TZ=America/New_York token-usage-dash
```

With Compose, set `TZ` in your shell or `.env`; the compose file reads it with a default:

```yaml
TZ: "${TZ:-Asia/Shanghai}"
```

**Proxy.** `docker-compose.yml` already routes outbound requests through a proxy on the host, which is required when the Codex/Claude endpoints are not directly reachable:

```yaml
HTTP_PROXY: "${HTTP_PROXY_HOST:-http://host.docker.internal:7890}"
HTTPS_PROXY: "${HTTP_PROXY_HOST:-http://host.docker.internal:7890}"
NO_PROXY: "localhost,127.0.0.1,::1"
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Change the port/address with `HTTP_PROXY_HOST`, e.g. `HTTP_PROXY_HOST=http://192.168.1.10:7890 docker compose up -d`. The `extra_hosts` entry is what makes `host.docker.internal` resolve on Linux; Docker Desktop provides it automatically. If your container has direct access, the proxy settings are harmless.

For plain `docker run`, pass them explicitly:

```bash
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  -e TZ=Asia/Shanghai \
  -e HTTPS_PROXY=http://host.docker.internal:7890 \
  -e HTTP_PROXY=http://host.docker.internal:7890 \
  --add-host host.docker.internal:host-gateway \
  token-usage-dash --loop
```

### 4. Building and pushing an x86 image

To deploy on an amd64 server, build and push with `build.sh`:

```bash
# Set your registry once (or edit REGISTRY at the top of build.sh)
export REGISTRY=registry.example.com/your-namespace/your-image

./build.sh                 # build linux/amd64, push :latest
./build.sh --tag v1.0      # push an extra tag
./build.sh --no-push       # build into the local Docker only
```

`build.sh` ships with a placeholder registry and refuses to push until you replace it, either through the `REGISTRY` environment variable, the `--registry` flag, or by editing the file. Run `docker login <your-registry>` first. Then on the x86 server:

```bash
docker run -d --name token-usage-dash --restart unless-stopped \
  --env-file .env \
  "$REGISTRY:latest" --loop
```

Two things the script handles that a plain `docker buildx build` does not:

- **Cross-building from Apple Silicon.** `--platform linux/amd64` builds real x86_64 via emulation.
- **Registry manifest compatibility.** Some registries (for example Aliyun ACR) reject the OCI manifest list with provenance attestations that BuildKit emits by default (`unknown manifest class for application/vnd.oci.empty.v1+json`). The script emits Docker media types and disables attestations (`--provenance=false --sbom=false --output ...,oci-mediatypes=false`).

If you keep a machine-specific script with the real registry baked in, name it `build.local.sh` — `.gitignore` excludes `*.local.sh`, so it stays out of the repository.

## Usage

```bash
# One-shot update
uv run display.py

# Loop every 30 minutes
uv run display.py --loop

# Loop with custom interval and save preview PNG
uv run display.py --loop --interval 900 --preview

# Preview image without pushing to device
uv run render.py   # saves to /tmp/usage_preview.png

# Print usage to terminal only
uv run usage.py
uv run usage.py --claude-only
uv run usage.py --openai-only
uv run usage.py --opencode-only
```

## Files

| File | Purpose |
|------|---------|
| `usage.py` | Fetches Claude, OpenAI Codex and OpenCode Go usage data |
| `render.py` | Renders the 296×152 PNG image |
| `display.py` | Orchestrates fetch → render → push to device |
| `Dockerfile` | Container image (env-var driven, no credential mounts) |
| `docker-compose.yml` | Compose service definition (no volumes) |
| `build.sh` | Cross-builds linux/amd64 and pushes to your registry (placeholder address) |
