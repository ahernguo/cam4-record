# 執行與驗收

## 重啟前

使用原本跑 watchdog 的 Python 環境更新依賴：

請保留原本可錄影的 Python 環境。額外相容性檢查發現：既有 Livestreamer 1.12.2 使用 `imp`，
在本次測試用 Python 3.12 無法匯入；本次不遷移串流套件，請勿為此功能改用 Python 3.12 以上。
原 README 的「3.10 或更新」對這個舊套件不完全適用。

```powershell
python -m pip install -r requirements.txt
```

預設使用 Microsoft Edge 的無頭模式，不會顯示視窗。若沒有 Edge，可在 setting.json 增加：

```json
"chat": {"enabled": true, "browser_channel": "chrome", "offset_seconds": 0}
```

也可用 `browser_channel: null` 搭配 `python -m playwright install chromium`。
不設定 chat 區塊時預設啟用，無須修改現有 wanted 清單。若先只驗證 MP4，可設定 enabled 為 false。

FFmpeg 與 ffprobe 必須可執行：PATH、環境變數 `CAM4_FFMPEG`／`CAM4_FFPROBE`，
或本機 `.tools/ffmpeg*/bin/`。`.tools` 不進版控，不會跟著分支下載到另一台電腦。
FFmpeg 須含 libx265、libass；本機驗證使用 Gyan essentials 發行包。

由使用者停止舊程序，再執行 `python watchdog.py`。不要同時啟動第二份錄影程序。

## 等一段錄影結束後查看

| 檔案 | 檢查內容 |
|---|---|
| `.capture` | 還在錄製；強制停止後可能殘留 |
| `.chat.mp4` | 驗證完成的唯一成品；有訊息時包含字幕燒錄(Burn-in) |
| `.source`、`.chat.jsonl`、`.chat-status.json`、`.ass`、日誌 | 只在錄影中、轉檔中或失敗時存在，供復原與診斷；成功後自動刪除 |

最終影片在錄影自然結束後產生；若以 Ctrl+C 停止整個程式，未完成轉檔留待下次啟動。

驗收項目：
1. `.chat.mp4` 可播放、拖曳、聲音正常，開始與結尾沒有明顯損壞。
2. 聊天底色透明、帳號黃字黑邊、文字白字黑邊。
3. 中文／英文可讀，長句不超出畫面；內容最多兩行，超長以省略號表示。
4. 比較開頭、中段、結尾的聊天與影片反應，記錄字幕快／慢幾秒，或是否逐漸偏移。
5. 訊息持續顯示；累計高度超過畫面時，最舊訊息消失，較新的訊息仍保留。
6. 無訊息房間的 `.chat.mp4` 應為純影音內容，不能用零訊息判定功能失敗。
7. 確認有觀眾發言但無字幕時，在轉檔完成前保留狀態 JSON 與 capture.log 的 chat 相關錯誤，不需提供帳密。
8. 多房間觀察 CPU、記憶體與磁碟；每房間一個瀏覽器，離線合成一次處理一檔。

## 自動測試

```powershell
python -m unittest discover -s tests -v
python -m py_compile main.py media_output.py chat_capture.py chat_subtitles.py watchdog.py
```

測試涵蓋：EOF／寫入失敗清理、看門狗、錯誤容器拒絕、轉檔失敗保留來源、
Firebase 分框／跨房間過濾、系統事件排除、ASS 控制字元處理、偏移與顏色、空聊天。
協定測試使用依公開前端欄位製作的合成資料，不冒充實際直播擷取結果。
實際直播、平台存取限制、長時間重連、HLS 精準同步尚待使用者實錄驗收。

## 本次驗證結果（2026-09-28）

- 27 項測試全部通過，無跳過；Python 語法編譯檢查通過。
- 實際產生 MPEG-TS / MPEG-2 / MP2 合成影音，轉成 MP4 / H.265 / AAC 並通過 ffprobe。
- H.264 無音訊樣本會轉成 H.265/HEVC，並以 `hvc1` 標記封裝於 MP4。
- 實際 ASS 燒錄後，第 13 秒仍可看到第 0 秒加入的訊息，區域外背景保留；另以截圖目視確認中英文、黃／白文字與黑描邊。
- 以 2026-10-03 的七則實錄聊天資料產生新版 ASS；最後一則加入後，七則都持續到影片結束。
- 全範圍 `yuvj420p` 實例會轉成標準 `yuv420p`；MPEG-TS 誤報 90,000 fps 時，以封包數與時長推算並校準為常見幀率，避免產生不合理的輸出幀率。
- Playwright 成功啟動本機無頭 Edge。
- Gyan FFmpeg 9.0.2 essentials ZIP 的 SHA-256 與發布者提供值相符：
  `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- 合成展示檔在本機 `.tools/chat-preview/demo.chat.mp4`，測試內容不是實際直播。
- 未啟動使用者的錄影程序，未實測 CAM4 直播連線；實際訊息取得率與同步仍需驗收。

## 重做單一檔案

成功後只保留 `.chat.mp4`，因此無法再調整該次錄影的時間或樣式；如需保留重做能力，後續應另增可設定的封存選項。
舊版留下的 `.source` 與聊天紀錄會以持續堆疊版面重建 `.chat.mp4`，成功後一併清理。請勿在仍在錄製時改名 `.capture`。
