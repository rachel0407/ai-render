# Render Dispatcher — Multi-Provider 合圖架構

ai-render 的合圖後端不再單一綁 Gemini，現在是一個 pluggable provider 架構，
支援自動 fallback。當主 provider 失敗，會自動切到備援 provider，使用者前端
不會看到失敗。

> 起因：2026-05-07 Gemini `gemini-2.5-flash-image` 嚴重過載，連續回 503，
> 前端使用者看到「合成失敗：Failed to fetch」。為了不再被單一供應商綁架，
> 加入 OpenClaw 透過 OAuth 訂閱呼叫 OpenAI `gpt-image-2` 作為備援。

---

## 架構

```
                   ┌──────────────────────────────────────────────┐
                   │  ai-render (Docker container)                │
                   │  /srv/ai-render — FastAPI                    │
                   │                                              │
                   │   POST /api/v1/render                        │
                   │       │                                      │
                   │       ▼                                      │
                   │   render.dispatcher                          │
                   │       │                                      │
                   │       ├── primary  ──┐                       │
                   │       │              │  fail (any exception) │
                   │       │              ▼                       │
                   │       └── fallback ──┘                       │
                   │           │      │                           │
                   │   ┌───────┘      └────────┐                  │
                   │   ▼                       ▼                  │
                   │ GeminiProvider      OpenClawProvider         │
                   │   │                       │                  │
                   └───┼───────────────────────┼──────────────────┘
                       │                       │ HTTP
                       │                       │ host.docker.internal:18790
                       ▼                       ▼ (Bearer token)
                ┌──────────────┐       ┌──────────────────────────────────┐
                │  Google      │       │  openclaw-bridge (systemd)       │
                │  Gemini API  │       │  /home/claude/openclaw-bridge    │
                └──────────────┘       │  bind 172.17.0.1:18790           │
                                       │     │                            │
                                       │     ▼ subprocess                 │
                                       │  /home/claude/.npm-global/bin/   │
                                       │     openclaw infer image edit    │
                                       │     │                            │
                                       │     ▼ OAuth (codex-responses)    │
                                       │  OpenAI gpt-image-2              │
                                       └──────────────────────────────────┘
```

### 為什麼這樣切

| 設計 | 理由 |
|---|---|
| Provider 抽象介面 (`RenderProvider`) | 之後加第三家（Replicate / fal / 本地 ComfyUI）不用動 dispatcher 跟 routes |
| Dispatcher 在 ai-render 內 | 切換邏輯靠近使用點，HTTP 層不必感知 |
| OpenClaw 包成 host 上的 systemd service | OpenClaw CLI 跟 OAuth 憑證都在 host 上，bridge 跟它同 user 邊界，不必把憑證搬進容器 |
| Bridge bind `172.17.0.1` 而非 `127.0.0.1` 或 `0.0.0.0` | Container 透過 `host.docker.internal` 可達，host 外網 NIC 不可達，不依賴 firewall |
| Bridge 加 Bearer token | 防 host 上其他容器/process 亂打 |

---

## 各組件位置

### 1. ai-render（Docker container, /srv/ai-render）

```
app/services/render/
├── __init__.py
├── base.py          # RenderProvider 抽象介面
├── gemini.py        # GeminiProvider (Google Gemini)
├── openclaw.py      # OpenClawProvider (HTTP → bridge)
└── dispatcher.py    # 主從邏輯
```

外部介面（`api/routes.py` 的 `/api/v1/render` endpoint）呼叫的是
`render_dispatcher.render(...)` / `render_composite(...)`，dispatcher
負責挑 provider、處理 fallback。

### 2. openclaw-bridge（host systemd service）

```
/home/claude/openclaw-bridge/
├── main.py                       # FastAPI app (~150 行)
├── run.sh                        # 啟動腳本（systemd ExecStart）
├── lib/                          # pip --target 隔離安裝的依賴
├── .env                          # token + bind 設定
├── openclaw-bridge.service       # systemd unit
└── install.sh                    # sudo 安裝腳本（已執行過）
```

systemd unit 安裝在 `/etc/systemd/system/openclaw-bridge.service`，
以 `claude` user 跑（OpenClaw OAuth 憑證在 `/home/claude/.openclaw/`）。

### 3. OpenClaw CLI（host npm-global）

```
/home/claude/.npm-global/bin/openclaw      # CLI binary
/home/claude/.openclaw/                    # config + OAuth credentials
/home/claude/.openclaw/openclaw.json       # 主設定（auth.mode = oauth）
```

OAuth 是 ChatGPT/Codex 訂閱憑證，bridge 跑 `openclaw infer image edit`
時自動帶過去 — 用訂閱配額付費，不是 API key 計費。

---

## 設定

### ai-render `.env`

```ini
# Provider 選擇（dispatcher 用）
RENDER_PRIMARY=openclaw         # 主 provider: gemini | openclaw
RENDER_FALLBACK=gemini          # 備援: gemini | openclaw | (留白停 fallback)

# OpenClaw 透過 bridge
OPENCLAW_BRIDGE_URL=http://host.docker.internal:18790
OPENCLAW_BRIDGE_TOKEN=<256-bit hex>     # 必須跟 bridge 的 .env 一致
OPENCLAW_MODEL=openai/gpt-image-2
OPENCLAW_TIMEOUT_MS=120000
MAX_OPENCLAW_CONCURRENCY=1

# Gemini 維持原本設定
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-image
MAX_GEMINI_CONCURRENCY=2
```

### openclaw-bridge `.env`（/home/claude/openclaw-bridge/.env）

```ini
OPENCLAW_BRIDGE_TOKEN=<必須跟 ai-render 的同一個值>
OPENCLAW_BIN=/home/claude/.npm-global/bin/openclaw
BRIDGE_TMP_DIR=/tmp/openclaw-bridge
BRIDGE_MAX_CONCURRENCY=1            # OAuth 不適合並發，預設序列化
BRIDGE_BIND_HOST=172.17.0.1         # docker bridge IP，外網不可達
BRIDGE_PORT=18790
LOG_LEVEL=INFO
```

兩邊的 `OPENCLAW_BRIDGE_TOKEN` 必須一致，否則 ai-render 打 bridge 會收 403。

---

## 啟動 / 操作指令

### ai-render（Docker container）

```bash
cd /srv/ai-render

# 改了 code → 要 rebuild
docker compose up -d --build

# 改了 .env → 要 recreate 才會重讀（restart 不會！）
docker compose up -d

# 看 log
docker logs ai-render -f
docker logs ai-render --since=1h
```

### openclaw-bridge（systemd service）

```bash
# 狀態
systemctl status openclaw-bridge

# 啟動 / 停止 / 重啟
sudo systemctl start openclaw-bridge
sudo systemctl stop openclaw-bridge
sudo systemctl restart openclaw-bridge

# log（無 sudo 也能看自己 service 的 log）
journalctl -u openclaw-bridge -f
journalctl -u openclaw-bridge --since=1h
journalctl -u openclaw-bridge -p err           # 只看 error level
journalctl -u openclaw-bridge --since="2026-05-08 06:00"

# 健康檢查
curl http://172.17.0.1:18790/health
```

### OpenClaw 本身（gateway，bridge 用不到 gateway，這只是並存）

```bash
ps -ef | grep -i openclaw                       # 看 process
openclaw gateway health                         # gateway 健康
openclaw infer image providers --json           # 看支援哪些 image provider
```

### 主從切換

改 `.env` 兩行 + recreate：

```bash
# /srv/ai-render/.env
RENDER_PRIMARY=openclaw         # 或 gemini
RENDER_FALLBACK=gemini          # 或 openclaw / 留白

cd /srv/ai-render && docker compose up -d
```

驗證生效：

```bash
docker exec ai-render python -c "from app.config import settings; print(settings.render_primary, settings.render_fallback)"
```

### 確認當前實際在用哪個 provider

呼叫一次 render 後查 ai-render log：

```bash
docker logs ai-render --since=5m 2>&1 | grep render_composite
# 範例：
#   [render] render_composite via primary=openclaw
# 若 primary 失敗會看到：
#   [render] primary=gemini failed (...); trying fallback=openclaw
```

或看 bridge log（每次 OpenClaw 跑都會記）：

```bash
journalctl -u openclaw-bridge --since=5m | grep "openclaw start\|openclaw ok\|openclaw failed"
```

---

## 故障 Q&A

### Q1. 前端使用者看到「合成失敗：Failed to fetch」

**原因**：fetch 連線中斷（不是 server 回 error code）。常見：
- ai-render container 在處理請求中途重啟
- Cloudflare / Traefik 把長連線砍掉（Gemini 慢、OpenClaw 30–40s 都可能撞到）

**檢查**：

```bash
docker ps | grep ai-render                                # Status 是不是 Up
docker logs ai-render --since=5m | grep -E "Shut|Start"   # 有沒有重啟事件
journalctl -u traefik-traefik-1 --since=5m | grep timeout # traefik 有沒有 timeout
```

### Q2. 前端使用者看到「合成失敗：HTTP 502 — composite render failed: ...」

代表 ai-render 收到請求 → 跑 dispatcher → primary + fallback 都失敗。
看 `: ...` 後面的訊息：

```bash
docker logs ai-render --since=10m | grep "render_composite\|both render providers failed"
```

訊息裡會看到兩個 provider 各自的 error。常見組合：

| primary 訊息 | fallback 訊息 | 原因 |
|---|---|---|
| Gemini `503 UNAVAILABLE` | bridge 連不上 | bridge 沒跑 → 看 Q4 |
| Gemini `503 UNAVAILABLE` | bridge 回 `subprocess timed out` | OpenAI 慢或 OAuth 問題 → 看 Q6 |
| Gemini `safety-filtered` | OpenAI `invalid_request_error` | 設計圖內容違規 → 換圖 |

### Q3. 一直看到 `503 UNAVAILABLE`（Gemini 過載）

如果你已經切成 `RENDER_PRIMARY=openclaw`，**這不是錯誤** — Gemini 本來就在
過載狀態，但 OpenClaw 是 primary，前端使用者不會受影響。

如果想完全停 Gemini（連 fallback 都不用）：

```ini
RENDER_FALLBACK=
```

### Q4. bridge 連不上（ai-render 看到 `Connection refused` 或 timeout）

```bash
# 1. service 還活著嗎
systemctl status openclaw-bridge

# 2. 還在 listen 嗎
ss -tlnp | grep 18790

# 3. host 自己打得到嗎
curl http://172.17.0.1:18790/health

# 4. 容器內打得到嗎
docker exec ai-render python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:18790/health',timeout=5).read())"
```

最常見原因：
- service crashed → `journalctl -u openclaw-bridge -n 50` 看 stack trace
- ai-render container 沒有 `extra_hosts` → 檢查 `docker-compose.yml`
  有 `host.docker.internal:host-gateway` 那行
- 防火牆擋 docker bridge → `iptables -L FORWARD` 看（罕見）

### Q5. bridge 401 / 403（token 問題）

```bash
# 比對兩邊 token 是否一致
grep OPENCLAW_BRIDGE_TOKEN /srv/ai-render/.env
grep OPENCLAW_BRIDGE_TOKEN /home/claude/openclaw-bridge/.env
```

不一致 → 改成一致 → 重啟對應 service：

```bash
# 改了 ai-render .env
cd /srv/ai-render && docker compose up -d

# 改了 bridge .env
sudo systemctl restart openclaw-bridge
```

### Q6. bridge 回 `success: false`（OpenClaw subprocess 跑了但失敗）

看 bridge 回的 `error` 欄位 + journalctl：

```bash
journalctl -u openclaw-bridge --since=10m | grep "openclaw failed"
```

常見：
- **OAuth expired**：訊息含 `unauthorized` / `auth required` / `token expired`
  → host 上以 `claude` user 跑：

  ```bash
  openclaw configure          # 互動式重新登入 OpenAI/Codex OAuth
  ```

- **OpenAI subscription quota 用完**：訊息含 `rate_limit` / `quota`
  → 等到下個帳期重置，或暫時切回 `RENDER_PRIMARY=gemini`

- **input image 太大或格式錯**：訊息含 `invalid_value` / `image data`
  → 確認前端送的是合法 PNG/JPEG/WebP，且檔案 < 4MB

### Q7. 改了 `.env` 為什麼沒生效

`docker compose restart` **不會**重新讀 `env_file`。要用 `up -d`：

```bash
# ❌ 不夠
docker compose restart api

# ✅ 對
docker compose up -d
```

bridge 改了 `.env` 用：

```bash
sudo systemctl restart openclaw-bridge
```

### Q8. 想暫停 fallback / 想單獨測某個 provider

```ini
# 停 fallback：primary 失敗就 raise 給前端
RENDER_FALLBACK=

# 強制全走 OpenClaw
RENDER_PRIMARY=openclaw
RENDER_FALLBACK=

# 強制全走 Gemini
RENDER_PRIMARY=gemini
RENDER_FALLBACK=
```

改完 `docker compose up -d`。

### Q9. systemd service 啟不起來（`systemctl status` 顯示 failed）

```bash
journalctl -u openclaw-bridge -n 50 --no-pager
```

常見原因：
- Port 18790 被別人佔（之前手動跑的 process 沒 kill）
  → `ss -tlnp | grep 18790` 找出 PID → `kill <pid>`
- `lib/` 目錄消失（被誤刪）
  → `cd /home/claude/openclaw-bridge && pip3 install --target=./lib --break-system-packages -r requirements.txt`
- `run.sh` 沒執行權限
  → `chmod +x /home/claude/openclaw-bridge/run.sh`
- `.env` 語法錯（有空白、引號錯）
  → 直接 `bash -n /home/claude/openclaw-bridge/.env` 檢查

### Q10. OpenClaw 訂閱方案的 image gen 額度怎麼看

OpenClaw CLI 沒提供額度查詢，要去 OpenAI 後台：
- ChatGPT Plus/Pro：到 https://chatgpt.com → 個人設定看 image gen 限制
- Codex 訂閱：到 https://platform.openai.com/usage 看（如果有掛 dashboard）

實務上：如果 OpenClaw 開始大量回 `rate_limit_exceeded` 但你確認 OAuth
有效，幾乎一定是訂閱方案的 image gen 配額快用完。

### Q11. 想加第三個 provider（例如 Replicate / fal）

1. 在 `app/services/render/` 新增 `replicate.py`，繼承 `RenderProvider`，
   實作 `render` 跟 `render_composite`。
2. 在 `app/services/render/dispatcher.py` 的 `_PROVIDER_CLASSES` 註冊：

   ```python
   _PROVIDER_CLASSES = {
       "gemini": GeminiProvider,
       "openclaw": OpenClawProvider,
       "replicate": ReplicateProvider,   # 新增
   }
   ```

3. `.env` 加新 provider 的設定 + 改 `RENDER_PRIMARY` / `RENDER_FALLBACK`。
4. `docker compose up -d --build`。

dispatcher 目前只支援 1+1（primary + 1 個 fallback）。如果要 chain 多層
fallback，要改 `dispatcher._dispatch` 的邏輯。

---

## 緊急回滾（跑出問題、想退回單一 Gemini 模式）

```bash
# 1. 切回 Gemini-only
sed -i 's/^RENDER_PRIMARY=.*/RENDER_PRIMARY=gemini/' /srv/ai-render/.env
sed -i 's/^RENDER_FALLBACK=.*/RENDER_FALLBACK=/' /srv/ai-render/.env

# 2. 套用
cd /srv/ai-render && docker compose up -d

# 3. （選）停 bridge service，省 host 資源
sudo systemctl stop openclaw-bridge
```

要再啟用 OpenClaw：把 `RENDER_FALLBACK=openclaw` 加回去 +
`sudo systemctl start openclaw-bridge` + `docker compose up -d`。
