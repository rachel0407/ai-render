# ai-render

通用「上傳設計圖 → 自動去背 → AI 套到產品底圖」獨立工具。FastAPI + Gemini 影像合成。

User 匿名打開頁面 → 選一個產品資料夾 → 上傳設計 → 系統自動去背 → 拖拉/縮放定位 → AI 合成自然印製效果 → 下載。後台登入後可以管理產品資料夾、查所有渲染歷史。

整合：**Gemini API**（影像合成）、**Traefik**（reverse proxy + HTTPS）。

---

## 快速啟動

### 1. 啟動服務

```bash
docker compose up -d --build
```

不用先建 `.env`，**首次啟動會自動跳 Setup Wizard**。

### 2. 進 Setup Wizard 完成初始設定

開瀏覽器到 `https://<your-host>/`（或本機 `http://localhost:8000/`），會自動導到 setup wizard，填兩樣：

- **Gemini API key** — 到 [Google AI Studio](https://aistudio.google.com/apikey) → Create API key → 複製貼上
- **後台密碼** — 自己設一組（至少 6 字，之後在 `/admin` 用這組登入）

按「完成設定」後，後端會：
- 用 bcrypt 把密碼 hash 起來
- 自動產 32 字元的 session secret
- 把三樣寫到 `storage/config.json`
- in-memory 同步更新，不用重啟

### 3. 進後台建第一個產品資料夾

1. 點完成設定畫面的「進後台」（或開 `https://<your-host>/admin`）
2. 用剛設的密碼登入
3. 切到「資料夾管理」tab → 「+ 新增資料夾」（名稱限英數字 / 底線 / 連字號，1–64 字元）
4. 點剛建的卡片裡的「上傳底圖」，傳幾張產品照（單檔上限 50 MB）
   - 檔名含 `(正)` / `（正）` → 自動當預覽圖 + 正面
   - 檔名含 `(背)` / `（背）` → 雙面模式的背面
   - 可選：在資料夾裡放 `printable_area.json` 限定可印刷範圍（看下面「可印刷範圍」段）

### 4. 給 user 用

把 `https://<your-host>/` 分享給使用者就行了，匿名直接用，不用登入也不用 API key。

---

## 替代：用 `.env` 預先配置（適合自動化部署）

不想走 wizard 的話，可以複製 `.env.example` 為 `.env`、填入 `GEMINI_API_KEY` / `ADMIN_PASSWORD_HASH` / `ADMIN_SESSION_SECRET`：

```bash
cp .env.example .env
# 產 bcrypt hash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'你的密碼', bcrypt.gensalt()).decode())"
# 產 session secret
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 填進 .env，bcrypt hash 用單引號包起來
# ADMIN_PASSWORD_HASH='$2b$12$...'
docker compose up -d --build
```

⚠️ **bcrypt hash 不加單引號會被 docker-compose 變數展開破壞** — `$2b$12$...` 開頭的 salt 段會被當變數展開掉。

⚠️ 環境變數 / `.env` 優先於 `storage/config.json`，所以已經用 `.env` 配好的系統不會觸發 wizard。

---

## 重新設定 / 重置

刪掉 `storage/config.json` 並重啟，會回到 wizard 模式：

```bash
rm storage/config.json
docker compose restart   # 或 up -d
```

---

## 部署到 server

### 系統需求

- Linux server（任何 distro 都行；以下指令以 Ubuntu/Debian 為例）
- **Docker** 20.10+ 跟 **docker compose plugin**（不是舊的 `docker-compose` python 版）
  ```bash
  # 沒裝過的話一鍵裝
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER  # 讓非 root 可用 docker
  # 重新 login，或 newgrp docker
  ```
- 對外開放的 port：HTTPS 443（給 user）；HTTP 80（Let's Encrypt 驗證 + redirect）

### 部署步驟

```bash
# 1. 拉 repo
git clone <repo-url> ai-render
cd ai-render

# 2. （可選）把 docker-compose.yml 裡的 domain 改成你自己的
#    第 22 行跟第 29 行都有 upload.packigo.tw，全部換掉
sed -i 's/upload\.packigo\.tw/your-host.example.com/g' docker-compose.yml

# 3. 確認 DNS A record 已經把 your-host.example.com 指向這台 server 的公網 IP

# 4. 確認外部 traefik-net network 存在（看下面「Traefik 設定」段）

# 5. 起服務
docker compose up -d --build

# 6. 進瀏覽器到 https://your-host.example.com/，跟著 Setup Wizard 設定
```

### Traefik 設定（HTTPS 跟 reverse proxy）

`docker-compose.yml` 已經帶好 Traefik labels — 你只需要有一個 **跑在外部的 Traefik container** 監聽 80/443，並且有一個叫 `traefik-net` 的外部 docker network。

最小 Traefik 範例（如果你還沒有）：

```yaml
# traefik/docker-compose.yml
services:
  traefik:
    image: traefik:v3
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.myresolver.acme.email=you@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.myresolver.acme.httpchallenge=true"
      - "--certificatesresolvers.myresolver.acme.httpchallenge.entrypoint=web"
    networks:
      - traefik-net

networks:
  traefik-net:
    external: true
```

建 network 跟啟動：
```bash
docker network create traefik-net
cd traefik && docker compose up -d
cd ../ai-render && docker compose up -d
```

Let's Encrypt 證書會在第一次 HTTPS 請求時自動申請（DNS A record 必須先指過來）。

### 不用 Traefik 怎麼跑？

如果你的環境用 Nginx / Caddy / 雲端 LB，**改 `docker-compose.yml`** 把 Traefik 那段拿掉、改成暴露 port：

```yaml
services:
  api:
    build: .
    container_name: ai-render
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./storage:/app/storage
      - ./frontend:/app/frontend:ro
    ports:
      - "8000:8000"   # 暴露給本機或內網 reverse proxy
    # 拿掉 networks: / labels: 整段
```

然後你的 Nginx / Caddy 把 `your-host.example.com` 反代到 `localhost:8000` 即可。

**Caddy 範例**（Caddyfile）：
```
your-host.example.com {
    reverse_proxy localhost:8000
}
```

**Nginx 範例**（給已經有 certbot 的環境）：
```
server {
    listen 443 ssl http2;
    server_name your-host.example.com;
    ssl_certificate     /etc/letsencrypt/live/your-host.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-host.example.com/privkey.pem;

    client_max_body_size 60M;   # 後台上傳底圖上限是 50MB，多給 buffer

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 防火牆

只開 80/443，**不要對外開 8000**（如果用 Traefik 的話，8000 只在 docker 內部 traefik-net 流通）。

```bash
# ufw 範例
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 驗證部署成功

```bash
curl https://your-host.example.com/health
# 預期：{"status":"ok","configured":false}   ← 第一次部署，wizard 還沒填
# wizard 走完後：{"status":"ok","configured":true}
```

開瀏覽器到 `https://your-host.example.com/`，會自動 303 redirect 到 `/setup`。

### 升級 / 更新版本

```bash
cd ai-render
git pull
docker compose build api    # rembg 模型已在 image 內，rebuild 只重新 pip install
docker compose up -d
```

`storage/` 是 volume mount，所以**升級不會丟資料**（含 `config.json`、底圖、歷史紀錄全部留下）。

### 備份

只要備份這兩樣就夠了：
- `storage/`（含 config、底圖、使用者圖、結果、歷史）
- `docker-compose.yml`（如果你改過 domain / network）

```bash
tar czf ai-render-backup-$(date +%F).tar.gz storage/ docker-compose.yml
```

---

## 改了東西要怎麼重啟

| 改的東西 | 怎麼重啟 |
|---|---|
| `.env` | `docker compose up -d`（**不是 restart**！restart 不重讀 .env） |
| `app/*.py` | `docker compose build api && docker compose up -d`（app/ 是 COPY 進 image，不是 mount） |
| `frontend/*.html` | 自動生效（整個 frontend/ 資料夾 mount 進 container），瀏覽器 Cmd+Shift+R 清快取即可 |
| `Dockerfile` / `requirements.txt` | `docker compose build api && docker compose up -d` |
| 加新的 `source_image/{folder}/` 或丟新底圖 | 自動生效，不用重啟（不過建議走後台 UI） |

---

## 架構區塊說明

```
┌──────────────────────────────────────────────────────────────┐
│ 使用者瀏覽器                                                   │
│ ├─ /          frontend/customize.html  上傳→去背→拖拉→渲染→下載 │
│ ├─ /admin     frontend/admin.html      登入後查歷史 + 管理資料夾   │
│ └─ /setup     frontend/setup.html      首次啟動 Wizard           │
└──────────────────────────────────────────────────────────────┘
                          ↓ HTTPS
┌──────────────────────────────────────────────────────────────┐
│ Traefik (reverse proxy + Let's Encrypt)                       │
│   <your-host> → ai-render container                           │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ ai-render container (FastAPI + uvicorn)                       │
│                                                                │
│ app/main.py                                                   │
│  ├─ GET /              → frontend/customize.html（沒 configured 導 /setup）│
│  ├─ GET /admin         → frontend/admin.html  （沒 configured 導 /setup）│
│  ├─ GET /setup         → frontend/setup.html                  │
│  ├─ StaticFiles 掛載：/source /upload /result                 │
│  └─ lifespan 只負責建空目錄（沒有 background loop）             │
│                                                                │
│ app/api/routes.py                                              │
│  Setup wizard (未 configured 才開放)：                         │
│   ├─ GET  /api/v1/setup/status                                │
│   └─ POST /api/v1/setup                                       │
│  公開 (匿名 + IP rate-limit)：                                 │
│   ├─ GET  /api/v1/sources                                     │
│   ├─ POST /api/v1/remove-background                           │
│   ├─ POST /api/v1/render                                      │
│   └─ POST /api/v1/render-jobs + GET /api/v1/render-jobs/{id}  │
│  Admin (bcrypt 登入 + Bearer token)：                          │
│   ├─ POST /api/v1/admin/login                                 │
│   ├─ GET  /api/v1/admin/me                                    │
│   ├─ GET  /api/v1/admin/history?page=1&per_page=24            │
│   ├─ GET  /api/v1/admin/folders                               │
│   ├─ POST /api/v1/admin/folders                               │
│   ├─ DELETE /api/v1/admin/folders/{folder}                    │
│   ├─ POST /api/v1/admin/folders/{folder}/images               │
│   └─ DELETE /api/v1/admin/folders/{folder}/images/{filename}  │
│                                                                │
│ app/services/                                                  │
│  ├─ render/dispatcher.py  render provider 抽象層              │
│  ├─ render/gemini.py      Gemini API（render / composite）    │
│  ├─ image_service.py      source CRUD + upload/result + history│
│  ├─ background_service.py rembg/birefnet 去背                 │
│  ├─ setup_service.py      wizard 寫 storage/config.json       │
│  └─ admin_auth.py         bcrypt + HMAC token                  │
│                                                                │
│ storage/  (volume mount，docker 重啟不丟資料)                  │
│  ├─ source_image/{folder}/  產品底圖（後台維護；永久）          │
│  ├─ upload_image/           使用者原圖（永久）                  │
│  ├─ result_image/           AI 合成結果（永久）                 │
│  ├─ history.jsonl           渲染紀錄索引（永久）                │
│  └─ config.json             Setup wizard 寫入（gemini key + 密碼 hash）│
└──────────────────────────────────────────────────────────────┘
```

### 兩種 render 模式

- **Composite**（前端主要使用）：前端用 canvas 把底圖 + 設計合成一張 mockup 送一次給後端 → Gemini 一次 call，prompt 強調「保留所有幾何/位置/大小，只把浮貼變自然印製」。
- **Legacy 雙圖**（API 仍保留）：客戶端送原圖 + `overlay_position`（4 個百分比），後端對 `source_image/{folder}/` 內每張底圖各打 Gemini 一次。

### 雙面（正/背）

UI 切「雙面」會出現正/背 tab，每側獨立保存上傳檔與位置；渲染時並行跑兩 job。
- 正面底圖：folder 內檔名含 `(正)` / `（正）` 的；找不到 fallback 用第一張
- 背面底圖：folder 內檔名含 `(背)` / `（背）` 的；找不到 fallback 用 preview

### 可印刷範圍

在 `storage/source_image/{folder}/printable_area.json` 放：

```json
{
  "front": { "x_pct": 0.18, "y_pct": 0.32, "w_pct": 0.64, "h_pct": 0.36 },
  "back":  { "x_pct": 0.18, "y_pct": 0.32, "w_pct": 0.64, "h_pct": 0.36 }
}
```

前端會畫橙色虛線框、且限制拖拉/縮放都不能跑出框外。沒這個檔就 fallback 為整張可印。

---

## Storage 結構

| 資料夾 / 檔 | 內容 | 保留期 |
|---|---|---|
| `storage/source_image/{folder}/` | 產品底圖（後台維護） | 永久 |
| `storage/upload_image/` | 使用者原圖（composite 模式會附存原始設計圖） | 永久 |
| `storage/result_image/` | AI 合成結果 | 永久 |
| `storage/history.jsonl` | 索引：每行一筆 JSON（id / ts / source_folder / user_filename / result_filename） | 永久 |
| `storage/config.json` | Setup wizard 寫入的 `gemini_api_key` / `admin_password_hash` / `admin_session_secret`；環境變數沒設時當 fallback | 永久（重設刪掉它） |

**全部永久保留**，後台才查得到紀錄。空間不夠時手動清，或之後加 TTL。

---

## API 一覽（給程式串接用）

Setup wizard（只在未 configured 時可用）：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/setup/status` | 查目前是否已 configured（前端用來判斷該不該顯示 wizard） |
| POST | `/api/v1/setup` | `{gemini_api_key, admin_password}` 寫入 `storage/config.json` 並 in-memory 更新；已 configured 時回 409 |

公開（不用認證，只有 IP rate-limit；預設每分鐘 20 次／IP）：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/sources` | 列出所有 source folders（含 preview / files / printable_area） |
| POST | `/api/v1/remove-background` | `{image_base64}` → 透明 PNG base64 |
| POST | `/api/v1/render` | 同步渲染；成功時自動寫一筆 history |
| POST | `/api/v1/render-jobs` | 非同步渲染（建 job） |
| GET | `/api/v1/render-jobs/{job_id}` | 查 job 狀態 |

Admin（要 `Authorization: Bearer <token>`，token 從 `/api/v1/admin/login` 取）：

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/admin/login` | `{password}` → `{token, expires_at}` |
| GET | `/api/v1/admin/me` | 確認 token 還有效 |
| GET | `/api/v1/admin/history?page=1&per_page=24` | 渲染歷史（時間倒序） |
| GET | `/api/v1/admin/folders` | 列出所有 source folders + 內部圖檔 URL |
| POST | `/api/v1/admin/folders` | `{name}` 建空 folder（名稱限英數/底線/連字號，1–64 字） |
| DELETE | `/api/v1/admin/folders/{folder}` | 刪整個 folder 含所有底圖 |
| POST | `/api/v1/admin/folders/{folder}/images` | multipart `file` → 存底圖（單檔上限 50 MB） |
| DELETE | `/api/v1/admin/folders/{folder}/images/{filename}` | 刪一張底圖 |

---

## 文件入口

| 檔案 | 給誰看 | 內容 |
|---|---|---|
| `README.md`（這份） | 第一次看這 repo 的人 | 概觀 + 啟動 + 架構 + API |
| `CLAUDE.md` | Claude / 工程師 | 深度速查、地雷、debug 訣竅、常用指令 |
| `SECURITY.md` | 工程師 | 資安檢視 + 緊急操作備忘（改密碼、強制登出） |
| `OPERATIONS.md` / `OPERATIONS.html` | 管理員 / 客服 | 操作指南、客服 Q&A |
| `RENDER_DISPATCHER.md` | 工程師 | render provider 切換 / 加新 provider 的內部協議 |

新進工程師建議先讀 `CLAUDE.md`，特別是「⚠️ 關鍵地雷」段。

---

## License / 內部用

內部專案，未對外授權。
