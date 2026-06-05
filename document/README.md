# ai-render

通用「上傳設計圖 → 自動去背 → AI 套到產品底圖」獨立工具。FastAPI + Gemini 影像合成。

User 匿名打開頁面 → 選一個產品資料夾 → 上傳設計 → 系統自動去背 → 拖拉/縮放定位 → AI 合成自然印製效果 → 下載。後台登入後可以管理產品資料夾、查所有渲染歷史。

整合：**Gemini API**（影像合成）、**Traefik**（reverse proxy + HTTPS）。

## 部署模型（給「想開放任何商家使用」的人）

本專案是**單租戶**的：一台 instance = 一個商家。要讓多個商家各自使用，做法是
**每個商家各自部署一份**，各自帶自己的 Gemini key、各自的產品庫與歷史，互不相干：

```
商家 A 的網站  ──<iframe>──►  商家A自己的 ai-render（自己的 key / 產品 / 歷史）
商家 B 的網站  ──<iframe>──►  商家B自己的 ai-render（自己的 key / 產品 / 歷史）
```

商家有兩種使用方式：
1. **整頁分享** — 直接把 `https://<他的-host>/` 給客人用（最簡單）。
2. **嵌入商品頁** — 在自己網站貼一個 iframe，指向他自己那台 instance（見下面「嵌入到商家網站」）。

> 這個模型下你（原作者）零營運成本、不碰商家資料，但商家需要一台能跑 Docker 的 server
> ＋一個網域＋一把 Gemini key（偏技術型商家）。若想讓商家零部署，需另做多租戶 SaaS（不在本專案範圍）。

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

## 嵌入到商家網站（Embed widget）

商家可以把客製化介面用一個 iframe 嵌進**自己的商品頁**，`src` 指向**他自己那台** instance。
iframe 內頁面與後端同源，所以沒有 CORS 問題。

```html
<iframe
  src="https://<your-host>/?embed=1&folder=tshirt"
  style="width:100%; height:820px; border:0;"></iframe>
```

| Query 參數 | 作用 |
|---|---|
| `embed=1` | 進入嵌入模式（白底、去掉多餘留白）。 |
| `folder=<名稱>` | 預先選定並**鎖定**單一產品（藏掉左側產品挑選，使用者一進來就在「上傳設計圖」）。名稱打錯會 fallback 回完整挑選清單。 |

進階：iframe 會用 `postMessage` 對母網頁廣播 `ready / resize / render-start / render-complete / render-error`
事件（每則帶 `source: 'ai-render'`）。`render-complete` 會附上 `resultUrl`，商家可接到「加入購物車」流程。
完整事件契約、購物車整合範例、可直接開的測試母網頁，見 **`EMBED.md`** 與 **`embed-demo.html`**。

> ⚠️ 目前未限制誰能嵌入此 instance（無 `frame-ancestors`），別人複製 iframe 碼貼到別站＝燒**商家自己的**
> Gemini 額度。對外開放前建議把 `RATE_LIMIT_PER_MIN` 設保守，未來可加網域白名單限制嵌入來源。

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
- 對外開放的 port：
  - 模式 A（port 對外）：開你選的 port（預設 `8000`），或只開給前面的反向代理。
  - 模式 B（Traefik）：HTTPS `443`（給 user）＋ HTTP `80`（Let's Encrypt 驗證 + redirect）。

### 部署步驟

```bash
# 1. 拉 repo
git clone <repo-url> ai-render
cd ai-render

# 2. 從範本建自己的 docker-compose.yml
cp docker-compose.yml.example docker-compose.yml

# 3. 編輯 docker-compose.yml，擇一部署模式（範本檔頂部有完整說明）：
#    【模式 A】Port 直接對外（預設）— 適合本機 / 內網 / 前面已有自己的 Nginx・Caddy・雲端 LB。
#              這份不處理 HTTPS，要 HTTPS 自己在前面接反向代理（見「不用 Traefik 怎麼跑？」）。
#    【模式 B】Traefik + 網域 + 自動 HTTPS — 換上你的網域、設定憑證簽發器（見「Traefik 設定」）。

# 4. 起服務
docker compose up -d --build

# 5. 進瀏覽器到你的網址（模式 A：http://<server-ip>:8000/；模式 B：https://你的網域/），
#    跟著 Setup Wizard 完成設定
```

> `docker-compose.yml` 是各自部署時才從 `.example` 複製產生的（含自己的網域 / 模式選擇），
> 已經列入 `.gitignore` 不進版控；版控裡只留 `docker-compose.yml.example` 範本。

### Traefik 設定（HTTPS 跟 reverse proxy）

選**模式 B** 時，`docker-compose.yml.example` 的 Traefik labels 已經備好（解開註解即可），你只需要有一個
**跑在外部的 Traefik container** 監聽 80/443，並且有一個叫 `traefik_network` 的外部 docker network。

> 🔑 **鐵則：憑證簽發器（certresolver）的名字，你的 `docker-compose.yml` 與 Traefik 兩邊必須完全一致。**
> 範本模式 B 預設寫的是 `certresolver=myresolver`，所以你的 Traefik 裡也必須定義一個叫 `myresolver`
> 的簽發器。名字對不上 → Traefik 簽不出憑證 → 網站 HTTPS 連不上（瀏覽器拿到憑證錯誤或自簽憑證）。

下面兩種 Traefik 範例擇一：**範例 A** 的簽發器叫 `myresolver`，正好對上範本預設、compose 不用改；
**範例 B** 用 Cloudflare DNS、簽發器叫 `cloudflare`，那就要把你 compose 裡的 `certresolver=myresolver`
改成 `certresolver=cloudflare`。

### 範例 A：HTTP challenge（任何 DNS 商都適用，最簡單，推薦新商家用）

不需要 DNS 商的 API token，只要網域的 A record 指到這台、且 80 port 對外開放即可。

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
      - traefik_network

networks:
  traefik_network:
    external: true
```

> ✅ 用這份的話簽發器叫 `myresolver`，正好對上範本模式 B 的預設，**你的 `docker-compose.yml` 不用改**。

### 範例 B：Cloudflare DNS challenge（網域託管在 Cloudflare、想用 DNS 驗證時）

DNS-01 驗證，不需要對外開 80 也能簽（適合只想開 443、或要 wildcard 憑證）。
需要一把 Cloudflare API token（在 Cloudflare → My Profile → API Tokens 建，權限給 `Zone:DNS:Edit`），
用環境變數 `CF_DNS_API_TOKEN` 餵給 Traefik。

> ⚠️ 簽發器叫 `cloudflare`，所以要把你 `docker-compose.yml` 裡的 `certresolver=myresolver`
> 改成 `certresolver=cloudflare`，否則名字對不上。

```yaml
# traefik/docker-compose.yml
services:
  traefik:
    image: traefik:v3
    restart: unless-stopped
    environment:
      - CF_DNS_API_TOKEN=${CF_DNS_API_TOKEN}   # 放在 traefik 旁的 .env，別 commit
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
      - "--certificatesresolvers.cloudflare.acme.email=you@example.com"
      - "--certificatesresolvers.cloudflare.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.cloudflare.acme.dnschallenge=true"
      - "--certificatesresolvers.cloudflare.acme.dnschallenge.provider=cloudflare"
    networks:
      - traefik_network

networks:
  traefik_network:
    external: true
```

建 network 跟啟動：
```bash
docker network create traefik_network
cd traefik && docker compose up -d
cd ../ai-render && docker compose up -d
```

Let's Encrypt 證書會在第一次請求 / DNS 驗證通過後自動申請（A record 必須先指過來）。

### 不用 Traefik 怎麼跑？

用 `docker-compose.yml.example` 的**模式 A（預設）**即可——它已經是 `ports: 8000:8000`、不帶 Traefik：

```bash
cp docker-compose.yml.example docker-compose.yml   # 預設就是模式 A，不用改
docker compose up -d --build
```

然後你的 Nginx / Caddy / 雲端 LB 把 `your-host.example.com` 反代到 `localhost:8000` 即可。

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

只開 80/443，**不要對外開 8000**（如果用 Traefik 的話，8000 只在 docker 內部 traefik_network 流通）。

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
| `EMBED.md` | 商家 / 前端工程師 | 把客製化介面用 iframe 嵌入商家網站 + postMessage 事件契約 |
| `embed-demo.html` | 商家 / 前端工程師 | 可用瀏覽器直接開的嵌入測試母網頁（含事件 log） |
| `CLAUDE.md` | Claude / 工程師 | 深度速查、地雷、debug 訣竅、常用指令 |
| `SECURITY.md` | 工程師 | 資安檢視 + 緊急操作備忘（改密碼、強制登出） |
| `OPERATIONS.md` / `OPERATIONS.html` | 管理員 / 客服 | 操作指南、客服 Q&A |
| `RENDER_DISPATCHER.md` | 工程師 | render provider 切換 / 加新 provider 的內部協議 |

新進工程師建議先讀 `CLAUDE.md`，特別是「⚠️ 關鍵地雷」段。

---

## License / 內部用

內部專案，未對外授權。
