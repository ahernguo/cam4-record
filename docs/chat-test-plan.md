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
FFmpeg 須含 libx264、libass；本機驗證使用 Gyan essentials 發行包。

由使用者停止舊程序，再執行 `python watchdog.py`。不要同時啟動第二份錄影程序。

## 等一段錄影結束後查看

| 檔案 | 檢查內容 |
|---|---|
| `.capture` | 還在錄製；強制停止後可能殘留 |
| `.source` | 原始串流，保留供復原與重做 |
| `.mp4` | 已驗證的純影音版本 |
| `.chat.jsonl` | 是否有正確帳號、文字、elapsed、server_ms |
| `.chat-status.json` | messages 是否增加；failed／retrying 是否持續 |
| `.ass` | 有文字才產生的字幕 |
| `.chat.mp4` | 優先觀看的字幕燒錄(Burn-in)成品 |
| `.ffmpeg.log`／`.chat.ffmpeg.log` | 合成失敗或媒體警告 |

最終影片在錄影自然結束後產生；若以 Ctrl+C 停止整個程式，未完成轉檔留待下次啟動。

驗收項目：
1. 純影音 MP4 可播放、拖曳、聲音正常，開始與結尾沒有明顯損壞。
2. `.chat.mp4` 的底色透明、帳號黃字黑邊、文字白字黑邊。
3. 中文／英文可讀，長句不超出畫面；目前內容最多兩行，超長截斷是已知行為。
4. 比較開頭、中段、結尾的聊天與影片反應，記錄字幕快／慢幾秒，或是否逐漸偏移。
5. 無訊息房間應只有純影音，不能用零訊息判定功能失敗。
6. 確認有觀眾發言但 JSONL 空白時，提供狀態 JSON 與 capture.log 的 chat 相關錯誤，不需提供帳密。
7. 多房間觀察 CPU、記憶體與磁碟；每房間一個瀏覽器，離線合成一次處理一檔。

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

- 20 項測試全部通過，無跳過；Python 語法編譯檢查通過。
- 實際產生 MPEG-TS / MPEG-2 / MP2 合成影音，轉成 MP4 / H.264 / AAC 並通過 ffprobe。
- H.264 無音訊樣本重新封裝前後的解碼畫面雜湊相同。
- 實際 ASS 燒錄後畫面改變、區域外背景保留；另以截圖目視確認中英文、黃／白文字與黑描邊。
- Playwright 成功啟動本機無頭 Edge。
- Gyan FFmpeg 9.0.2 essentials ZIP 的 SHA-256 與發布者提供值相符：
  `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- 合成展示檔在本機 `.tools/chat-preview/demo.chat.mp4`，測試內容不是實際直播。
- 未啟動使用者的錄影程序，未實測 CAM4 直播連線；實際訊息取得率與同步仍需驗收。

## 重做單一檔案

若需調整時間，修改該錄影的 `.chat-options.json` 中 offset_seconds。
先將既有 `.chat.mp4` 移到備份位置（程式不覆寫既有正式成品），重啟後重新產生。
保留 `.source` 與 `.chat.jsonl`。請勿在仍在錄製時改名 `.capture`。
