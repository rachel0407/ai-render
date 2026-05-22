# ai-render — Claude 工作指南

> 通用「上傳設計圖 → 去背 → AI 套用到產品底圖」獨立工具。FastAPI + Gemini 影像合成。

---

## 系統概觀

User 端 (`/`)：匿名打開 → 選資料夾（後台維護的產品底圖類別）→ 上傳設計圖 → 自動去背 → 拖拉/縮放定位 → AI 合成 → 下載。

後台 (`/admin`)：bcrypt 密碼登入，兩個 tab：
1. **歷史紀錄** — 依時間倒序看每筆渲染的「使用者原圖 + 合成結果」
2. **資料夾管理** — 新增/刪除資料夾、上傳/刪除產品底圖

---

## 技術棧

| 層 | 套件 |
|---|---|
| Web | FastAPI + uvicorn |
| 容器 | Docker Compose + Traefik |
| AI | Google `genai` SDK，模型 `gemini-2.5-flash-image`；可選 OpenClaw fallback |
| 去背 | rembg / u2net（CPU；first-load ~5–8s, 之後 ~4–6s） |
| 認證 | bcrypt（cost 12）+ HMAC-SHA256 session token + slowapi rate-limit |
| 設定 | Pydantic Settings（讀 `.env`） |

---

## ⚠️ 關鍵地雷

### 1. `docker compose restart` 不會重讀 `.env`
- `restart` 只是停 / 啟同一個 container，環境變數在 **create 時** baked。
- ✅ 改 `.env` 後務必用 **`docker compose up -d`**（會偵測 `.env` 變動 → recreate）。

### 2. bcrypt hash 在 `.env` 必須**單引號**包起來
- docker-compose 會對 `.env` 的值做 `${VAR}` 變數展開。
- bcrypt salt 段（如 `$uCeUgov3...`）開頭剛好是字母 → docker-compose 把它當 `$uCeUgov3` 變數參考 → 找不到 → **整段被替換成空字串，hash 被破壞**。
- 症狀：`up -d` 印 `WARN[0000] The "XXX" variable is not set.`
- ✅ 一律寫成 `ADMIN_PASSWORD_HASH='$2b$12$...'`。

### 3. `app/` 是 COPY 進 image 的，不是 volume mount
- 改 `app/*.py` 後 **`restart` 沒用、`up -d` 也沒用**，必須 `docker compose build api && docker compose up -d`。
- 例外：`admin.html` 跟 `customize.html` 用 `:ro` mount 進 container，改完直接生效（要清瀏覽器快取）。

---

## 常用指令

```bash
# 改 app/*.py
docker compose build api && docker compose up -d

# 改 .env
docker compose up -d                   # ← 不是 restart！

# 改 admin.html / customize.html（mount 的）
# 自動生效，瀏覽器 Cmd+Shift+R 清快取

# 看 log
docker compose logs api --tail=100

# 進 container（沒裝 curl / vim，只有 python）
docker exec -it ai-render bash
```

---

## 程式碼地圖

```
app/
├── main.py                  # FastAPI app（lifespan 只負責建目錄；沒有 background loops）
├── config.py                # Pydantic Settings — Gemini + render prompt + storage + admin
├── api/
│   ├── routes.py            # 公開: /render, /render-jobs, /remove-background, /sources
│   │                        # Admin: /admin/login, /admin/me, /admin/history,
│   │                        #        /admin/folders（CRUD）, /admin/folders/{f}/images（CRUD）
│   └── deps.py              # verify_admin_token（公開 endpoints 不再需要 API key）
├── schemas/render.py        # 所有 Pydantic 模型
└── services/
    ├── image_service.py     # source folder CRUD + upload/result + history（JSONL）
    ├── background_service.py# rembg 去背
    ├── admin_auth.py        # bcrypt verify + HMAC token
    └── render/
        ├── dispatcher.py    # primary/fallback 路由
        ├── gemini.py        # Gemini 實作（render / render_composite）
        └── openclaw.py      # OpenClaw 實作（optional fallback）

customize.html               # User 端（mount :ro 進 container，由 / endpoint 出）
admin.html                   # 後台前端（mount :ro 進 container，由 /admin endpoint 出）
docker-compose.yml           # api service + Traefik labels
.env                         # 所有 secret（**不進 git**）
```

---

## Storage 結構

| 資料夾 | 內容 | TTL |
|---|---|---|
| `storage/source_image/` | 產品底圖（後台維護；一個 folder = 一個產品） | 永久 |
| `storage/upload_image/` | 使用者原圖（composite 模式下會附存原始設計圖） | 永久 |
| `storage/result_image/` | AI 合成結果 | 永久 |
| `storage/history.jsonl` | 渲染紀錄索引（每行一筆 JSON：id/ts/source_folder/user_filename/result_filename） | 永久 |

**全部永久保留**，後台才查得到紀錄。空間不夠時手動清。

---

## 兩種 render 模式

### Composite mode（前端主要使用）
1. 前端 `composeOffscreen()` 把底圖 + user 圖（按拖拉位置）畫到一張 canvas → base64
2. POST `/render-jobs` 帶 `is_composite: true` + `user_image_base64`
3. 後端跳過 source folder 迭代，**單次** Gemini call：「保留所有幾何/位置/大小，只把浮貼變自然印製」
4. 寫一筆 history，回 1 筆結果

### Legacy 雙圖 mode（保留 API 相容性，前端目前不走這條）
1. 客戶端送原圖 + `overlay_position`（4 個百分比）
2. 後端對 source folder 內**每張底圖**個別 Gemini call
3. 每張寫一筆 history，回 N 筆結果

---

## Admin 後台

- URL: `https://<your-host>/admin`
- 認證：bcrypt password + HMAC token（8 小時 TTL）
- API:
  - `POST /api/v1/admin/login` `{password}` → `{token, expires_at}`
  - `GET  /api/v1/admin/me`
  - `GET  /api/v1/admin/history?page=1&per_page=24`
  - `GET  /api/v1/admin/folders`
  - `POST /api/v1/admin/folders` `{name}`（名稱限 1~64 字元，word chars + hyphen）
  - `DELETE /api/v1/admin/folders/{folder}`
  - `POST /api/v1/admin/folders/{folder}/images`（multipart `file`，單檔 50 MB）
  - `DELETE /api/v1/admin/folders/{folder}/images/{filename}`
- 想立即登出全員：換 `ADMIN_SESSION_SECRET` + `up -d`

---

## User 端流程細節

- **去背**：上傳即打 `/api/v1/remove-background`（rembg）；失敗或 timeout 時 fallback 使用原圖（不再下載瀏覽器 WASM 模型，省 ~20 MB 流量）
- **裁邊**：去背後跑 `trimTransparentEdges()` 自動裁透明邊 + 近白邊
- **印刷區提示**：`source_image/{folder}/printable_area.json` 若存在會畫橙色虛線框並限制拖拉範圍
- **正/背雙面**：UI radio 切「雙面」會顯示正/背 tab；每側獨立保存 file + overlayRect；render 時並行跑兩個 job
  - 正面用 folder 內 `(正)` 標記檔；背面用 `(背)` 標記檔（fallback：preview）

---

## 開發 / Debug 訣竅

- **container 內沒 curl / vim** → 用 `python3 -c "import urllib.request; ..."` 打 API
- **Gemini 文字回應而非圖片** → `_extract` 會 retry 一次，看 log `Gemini text-only response`
- **新 source folder** → 後台「資料夾管理」→ 新增，或把圖直接丟進 `storage/source_image/{folder_name}/`，立即可用，不用重啟
- **history.jsonl 損壞** → JSONL，每行獨立；損壞那行會被 `list_history` 跳過

---

## 還沒做的事

- 收緊 CORS `allow_origins`（目前 `*`）
- `/upload`、`/result`、`/source` StaticFiles 加 auth（目前任何人知道 filename 可看圖）
- history 加搜尋 / folder filter
- 前端 admin token 從 sessionStorage 改 HttpOnly cookie

---

## 文件入口

- `CLAUDE.md` ← 你在看
- `SECURITY.md` — 資安檢視 + 緊急操作備忘（改密碼、強制登出等）
- `OPERATIONS.md` / `OPERATIONS.html` — 給管理員 / 客服的操作指南
