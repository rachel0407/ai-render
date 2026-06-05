# 嵌入 ai-render 到商家網站（Embed）

讓任何商家把「上傳設計 → 去背 → 定位 → AI 合成」介面，用一個 iframe 嵌進自己的商品頁。
每個商家各自部署一份 ai-render、各自帶自己的 Gemini key，所以**不需要多租戶**——
這份只負責「把單一 instance 的客製化介面嵌進別的網站」。

> 階段 1（本文件）：iframe 嵌入模式 + 產品鎖定 + postMessage 事件。
> 階段 2（未做）：`embed.js` loader——自動建 iframe、自動調高度、把結果接到購物車。

---

## 最快：純 iframe

```html
<iframe
  src="https://<你的-ai-render-網域>/?embed=1&folder=tshirt"
  style="width:100%; height:820px; border:0;"
  allow="clipboard-write"></iframe>
```

| Query 參數 | 作用 |
|---|---|
| `embed=1` | 進入嵌入模式：套用 `body.embed` 樣式（白底，去掉多餘留白）。 |
| `folder=<名稱>` | 預先選定並**鎖定**單一產品（藏掉左側「產品」挑選分頁，使用者一進來就在「上傳設計圖」）。名稱 = 後台建立的資料夾名。 |

- iframe 內的頁面是從 ai-render 自己的網域送出的，所以裡面所有 API 呼叫都是**同源**，沒有 CORS 問題。
- `folder` 名稱若打錯（資料夾不存在）→ 不會上鎖，會 fallback 顯示完整產品挑選清單。
- 不給 `folder` → 顯示完整產品挑選清單（適合一個 iframe 涵蓋多個產品）。

---

## 進階：監聽事件，把結果接到購物車

iframe 內的頁面會用 `postMessage` 對母網頁廣播事件。母網頁這樣監聽：

```html
<iframe id="airender"
        src="https://<你的-ai-render-網域>/?embed=1&folder=tshirt"
        style="width:100%; height:820px; border:0;"></iframe>

<script>
  window.addEventListener('message', (e) => {
    const msg = e.data;
    if (!msg || msg.source !== 'ai-render') return;

    switch (msg.type) {
      case 'ready':
        // 介面已載入。msg.embed / msg.lockedFolder 可參考
        break;

      case 'resize':
        // 內容高度變了，可用來自動調 iframe 高度（手機版特別有用）
        document.getElementById('airender').style.height = msg.height + 'px';
        break;

      case 'render-start':
        // 開始 AI 合成（約 15–30 秒）。可顯示 loading
        break;

      case 'render-complete':
        // 渲染完成。msg.results = [{ side, resultFilename, resultUrl, sourceFilename }]
        // resultUrl 是可直接引用的圖片網址 → 丟進「加入購物車」的隱藏欄位/訂單備註
        console.log('客人做好的圖：', msg.results.map(r => r.resultUrl));
        break;

      case 'render-error':
        // 合成失敗。msg.message 為錯誤訊息
        break;
    }
  });
</script>
```

### 事件契約（postMessage payload）

每則訊息都帶 `source: 'ai-render'`，請務必用它過濾（同頁可能有其他來源的 message）。

| `type` | 額外欄位 | 何時送 |
|---|---|---|
| `ready` | `embed`(bool), `lockedFolder`(string\|null) | 介面初始化完成 |
| `resize` | `height`(number, px) | 內容高度改變時 |
| `render-start` | `folder`(string) | 按下「開始渲染」 |
| `render-complete` | `folder`(string), `results`(array) | 渲染成功 |
| `render-error` | `folder`(string), `message`(string) | 渲染失敗 |

`render-complete` 的 `results` 每筆：

```js
{
  side: 'front' | 'back' | null,        // 雙面模式才有 front/back
  resultFilename: 'xxxxx.png',          // 存在 instance 的 storage/result_image/
  resultUrl: 'https://<網域>/result/xxxxx.png',  // 可直接 <img src> 或存進訂單
  sourceFilename: '...'
}
```

> ⚠️ 結果圖長期保存在該 instance 的 `storage/result_image/`（目前無 TTL）。
> 商家若要把圖綁進訂單，建議**自己另存一份**到自己的儲存空間，別長期依賴這個 URL。

---

## 安全提醒（部署前務必看）

目前 ai-render **沒有限制誰能用 iframe 嵌入它**，也沒限制 `frame-ancestors`。代表：
任何人複製商家的 iframe 程式碼貼到別的網站，就是在**燒商家自己的 Gemini 額度**。

階段 3 會加一個 `ALLOWED_EMBED_ORIGINS` 設定，用 CSP `frame-ancestors` 限定只有商家自己的
網域能嵌。在那之前，建議至少：
- 後台 `RATE_LIMIT_PER_MIN` 設保守一點（預設 20/分/IP）。
- 不要把高價值的 Gemini key 放在對外、無防護的 instance。

---

## 本機測試

`document/embed-demo.html` 是一個可直接用瀏覽器打開的「母網頁」範例，
把 iframe `src` 改成你的 instance 網域即可看到嵌入 + 事件 log。
