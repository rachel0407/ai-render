# ai-render

通用「上傳設計圖 → 自動去背 → AI 套到產品底圖」獨立工具。FastAPI + Gemini 影像合成。

User 匿名打開頁面 → 選一個產品資料夾 → 上傳設計 → 系統自動去背 → 拖拉/縮放定位 → AI 合成自然印製效果 → 下載。後台登入後可以管理產品資料夾、查所有渲染歷史。

整合：**Gemini API**（影像合成）、**Traefik**（reverse proxy + HTTPS）。Optional：**OpenClaw**（fallback render provider）。

---

## 快速啟動

### 1. 建 `.env`

```bash
cp .env.example .env
```

填入：
- `GEMINI_API_KEY` — Google AI Studio 拿
- `ADMIN_PASSWORD_HASH` — 用下面這行產，**結果用單引號包起來**：
  ```bash
  python3 -c "import bcrypt; print(bcrypt.hashpw(b'你的密碼', bcrypt.gensalt()).decode())"
  ```
  然後 `.env` 寫成 `ADMIN_PASSWORD_HASH='$2b$12$...'`
- `ADMIN_SESSION_SECRET` — `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

⚠️ **bcrypt hash 不加單引號會被 docker-compose 變數展開破壞**，看 `SECURITY.md` 詳細解釋。

### 2. 啟動服務

```bash
docker compose up -d --build
```

### 3. 驗證

```bash
curl https://<your-host>/health
# {"status":"ok"}
```

### 4. 進後台建第一個產品資料夾

1. 開瀏覽器到 `https://<your-host>/admin`
2. 用 `.env` 設的密碼登入
3. 切到「資料夾管理」tab → 「+ 新增資料夾」（名稱限英數字 / 底線 / 連字號，1–64 字元）
4. 點剛建的卡片裡的「上傳底圖」，傳幾張產品照（單檔上限 50 MB）
   - 檔名含 `(正)` / `（正）` → 自動當預覽圖 + 正面
   - 檔名含 `(背)` / `（背）` → 雙面模式的背面
   - 可選：在資料夾裡放 `printable_area.json` 限定可印刷範圍（看下面「可印刷範圍」段）

### 5. 給 user 用

把 `https://<your-host>/` 分享給使用者就行了，匿名直接用，不用登入也不用 API key。

---

## 改了東西要怎麼重啟

| 改的東西 | 怎麼重啟 |
|---|---|
| `.env` | `docker compose up -d`（**不是 restart**！restart 不重讀 .env） |
| `app/*.py` | `docker compose build api && docker compose up -d`（app/ 是 COPY 進 image，不是 mount） |
| `admin.html` / `customize.html` | 自動生效（mount 進 container），瀏覽器 Cmd+Shift+R 清快取即可 |
| `Dockerfile` / `requirements.txt` | `docker compose build api && docker compose up -d` |
| 加新的 `source_image/{folder}/` 或丟新底圖 | 自動生效，不用重啟（不過建議走後台 UI） |

---

## 架構區塊說明

```
┌──────────────────────────────────────────────────────────────┐
│ 使用者瀏覽器                                                   │
│ ├─ /          customize.html  上傳→去背→拖拉→渲染→下載          │
│ └─ /admin     admin.html      登入後查歷史 + 管理資料夾           │
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
│  ├─ GET /              → customize.html                       │
│  ├─ GET /admin         → admin.html                           │
│  ├─ StaticFiles 掛載：/source /upload /result                 │
│  └─ lifespan 只負責建空目錄（沒有 background loop）             │
│                                                                │
│ app/api/routes.py                                              │
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
│  ├─ render/dispatcher.py  primary/fallback 路由               │
│  ├─ render/gemini.py      Gemini API（render / composite）    │
│  ├─ render/openclaw.py    OpenClaw（optional fallback）        │
│  ├─ image_service.py      source CRUD + upload/result + history│
│  ├─ background_service.py rembg/u2net 去背                    │
│  └─ admin_auth.py         bcrypt + HMAC token                  │
│                                                                │
│ storage/  (volume mount，docker 重啟不丟資料)                  │
│  ├─ source_image/{folder}/  產品底圖（後台維護；永久）          │
│  ├─ upload_image/           使用者原圖（永久）                  │
│  ├─ result_image/           AI 合成結果（永久）                 │
│  └─ history.jsonl           渲染紀錄索引（永久）                │
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

**全部永久保留**，後台才查得到紀錄。空間不夠時手動清，或之後加 TTL。

---

## API 一覽（給程式串接用）

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
