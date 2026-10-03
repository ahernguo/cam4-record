# CAM4 聊天室錄製：實作與優先順序

## 本次範圍與分支

儲存庫實際預設分支為 `main`，依使用者確認取代原要求中的 master。
`main` 的 MP4 修正先獨立提交；`feature/chat` 繼承該修正，再加入聊天實作。
不更改使用者既有 `setting.json`，不重啟錄影程序。

## 已實作：P0 網頁通訊監聽與離線合成

1. 既有 Livestreamer 仍下載影音，寫入 `.capture`；正常收尾後改名 `.source`。
2. 背景單一轉檔工作檢查實際格式；相容且沒有字幕的 H.264/yuv420p、AAC 可重新封裝，其餘轉碼。
3. 以 `.chat.encoding.mp4` 寫入，ffprobe 驗證正數長度、MP4 封裝與編碼後才發布 `.chat.mp4`。
4. 每個錄影房間啟動一個獨立無頭瀏覽器(Headless Browser)，預設使用已安裝的 Microsoft Edge。
5. 正常開啟公開房間，監聽網頁已接收的 WebSocket 訊框；不自行取得權限、不發送聊天、不讀取私訊。
6. 解析公共聊天的 Firebase 更新，逐筆寫 `.chat.jsonl` 並 flush。只接受錄影開始後的來源時間。
7. 錄影收尾後產生進階字幕格式(Advanced SubStation Alpha, ASS)，輸出 `.chat.mp4`。
8. `.chat.mp4` 驗證成功後，刪除 `.source`、JSONL、ASS、狀態、設定與轉檔日誌；任何產出或清理錯誤都先保留 `.source`，供下次啟動重試。

聊天樣式：透明背景、帳號黃色、內容白色、黑色 2px 描邊，由左上向下排列。
內容最多兩行，過長部分以省略號截斷；帳號另佔一行。訊息持續顯示到影片結束或被擠出，當所有訊息區塊超過畫面上下安全邊界時，依序移除最舊訊息。
字型預設 Microsoft JhengHei；字級依畫面高度縮放。GIF、彩色 emoji 與站內貼圖不在本次完整支援範圍。
聊天文字先移除 HTML 標籤並解碼實體，ASS 控制字元替換為全形，防止訊息改寫位置／樣式。

## 已查證的協定線索（2026-09-28）

直接讀取 CAM4 公開前端資源，檢查 `watchMainChat`、`listenForMainChatMessages`、
`parseLightMessage` 與 `firebaseStructure`：

- 即時公共聊天訂閱 `c/{lowercase room}`，Firebase `value` 更新。
- 歷史訊息另在 `chatRooms/{room}/chatMessages`；本版不補抓歷史，以免把舊訊息當新訊息。
- 文字為 `m`；`p` 以 `$` 分隔，其中第 2 欄為帳號、第 3 欄為毫秒時間。
- 普通聊天以此壓縮格式表示；沒有 `p` 的小費、系統通知不當成普通訊息。
- `delete` 訊息不新增文字。已捕捉內容仍保留，本版不回溯套用刪除。
- Firebase WebSocket 可能以數字表示後續訊框數量，解析器先組合再處理。
- 僅處理精確 `/c/{room}` 路徑的完整更新及同路徑合併更新；子路徑或其他格式待實際樣本驗證。

來源：
- [CAM4 當日公開前端程式](https://static.cam4.com/web/v2/app/js/application-d53c1a55bb903622fc34.js)
- [Playwright WebSocket](https://playwright.dev/python/docs/api/class-websocket)
- [FFmpeg 濾鏡](https://ffmpeg.org/ffmpeg-filters.html#subtitles)
- [ASS 樣式](https://aegisub.org/docs/latest/ass_tags/)

這些是公開前端程式的觀察結果，不是官方穩定 API 合約，也不是已通過實際直播驗收。

## 時間同步與復原

JSONL 同時保留伺服器毫秒時間、接收端 UTC 秒數、單調時鐘(Monotonic Clock)相對時間。
字幕目前以接收相對時間加 offset 定位。錄影器開啟 HLS 串流後啟動聊天，瀏覽器載入期間可能漏訊息。
HLS 預讀、播放器延遲及缺片尚未建立時間映射，不能宣稱精準同步；來源時鐘偏差也可能影響舊訊息過濾。

`offset_seconds` 正數使字幕晚出現，負數使字幕提早；套用值在每次錄影開始時保存。
斷線由網頁 Firebase 自己重連；頁面載入／操作例外五秒後重試。登入、年齡確認或地區限制不會自動繞過。
每十秒刷新 `.chat-status.json`；零訊息可能代表房間安靜、頁面限制、長輪詢或協定不同，不能直接認定成功或失敗。
只依有內容且解析成功的 JSONL 產生聊天圖層；沒有訊息時仍以 `.chat.mp4` 作為純影音內容的唯一成品。
以時間／帳號／文字去重，記憶體最多保留一萬筆鍵值；超出視窗的重播不保證去重。

聊天室失敗不終止影音。轉檔失敗保留原始檔，每次啟動各檔重試一次；成功後只保留 `.chat.mp4`。
正常停止會終止轉檔並保留來源；強制終止可能留下 `.capture`，確認沒有活躍寫入後才能手動改名恢復。
不處理舊版偽裝成 `.mp4` 的歷史錄影。輸出驗證是格式／編碼檢查，不是逐幀完整性驗證。

## 後續方案（等待本次實錄結果再決定）

| 優先度 | 方案 | 啟用條件／代價 |
|---|---|---|
| P1 | 校準 HLS 片段時鐘與呈現時間戳記(Presentation Timestamp, PTS) | 實錄可抓聊天但時間不準；確認是否有 PROGRAM-DATE-TIME |
| P1 | 支援 Firebase 子路徑更新、長輪詢或登入工作階段 | 狀態有連線但持續抓不到已知聊天 |
| P2 | 文件物件模型(Document Object Model, DOM) 擷取 | 通訊協定不穩定；需實際確認元素與去重方式 |
| P2 | 瀏覽器共用、房間數上限 | 多房間造成資源壓力；目前每房間一瀏覽器 |
| P3 | Python 直接連聊天服務 | 協定與授權流程已驗證，再減少瀏覽器負擔 |
| P3 | 即時合成、完整貼圖／emoji | 離線驗收完成且確有需求，再承擔即時編碼成本 |

本次採離線合成，確保重試與樣式調整可獨立於錄影進行；聊天室故障不影響錄影可用性。

