> This project is for practice purposes only.
> do not distribute the video footage! 
> Violators shall bear their own legal responsibilities

# Summary

This project is use to recording CAM4 videos behind the screen.
No live image will be displayed

# Usage

1. install [python3](https://www.python.org/downloads/)
    * Python 3.10 or newer is required for the reliability/watchdog workflow.
2. download this repo. or use `git clone https://github.com/ahernguo/cam4-record.git`
3. `cd cam4-record` to this repo directory
4. install requirements

    `pip install -r requirements.txt`

5. edit `setting.json`. for example

    ```json
    "out_dir": "E:\\Cam4" /* the directory to save video */,
    "wanted": [
       "person_1",
       "person_2"
    ] /* list of cam4's username that want to record */
    ```

6. start monitoring

   `python main.py`

7. done.

    > you may create a windows schedule for execute it when computer starts.

## 長時間執行與自動復原（Windows）

先停止舊的 `main.py`，再使用安裝了 `requirements.txt` 的同一個 Python 環境啟動：

```powershell
python watchdog.py
```

看門狗(Watchdog)會啟動獨立錄影程序。預設日誌位於專案的 `logs` 目錄，
與 `setting.json` 的影片輸出目錄分開；也可用 `--log-dir D:\Cam4Logs` 指定。
同一日誌目錄只允許一個看門狗。不要同時直接啟動另一份 `main.py`。

- `capture.log`：每日輪替，保留七份，包括啟動、例外與每十秒的心跳(Heartbeat)。
- `health.json`：程序 ID、監控進度、最後完整掃描時間、各錄影寫入量、剩餘磁碟空間。
- `stacks.log`：掃描或任一錄影超過 180 秒沒有進度時，保存所有執行緒堆疊。
- `watchdog.log`：重啟原因及結束代碼，限制單檔 2 MB、保留三份。
- `console.log`：包含啟動／匯入失敗與標準錯誤輸出；重啟時若超過 10 MB，保留上一份。

主迴圈或任一錄影超過 180 秒沒有進度，或心跳超過 180 秒未更新，
看門狗會要求停止，最多等候 80 秒後強制結束，再以 5～60 秒退避重啟。
健康檢查可能因底層完全卡死而無法輸出堆疊，但外部看門狗仍能偵測心跳失聯。
重啟會影響當下所有錄影；強制結束可能遺失尚未寫入磁碟的尾端資料。
Ctrl+C 可停止看門狗與子程序，清理時可能需要等待約 80 秒。

直接執行 `python main.py` 也有心跳及例外紀錄，但沒有外部自動重啟。
直接執行的日誌預設仍在 `E:\Cam4\logs`，可用 `CAM4_LOG_DIR` 環境變數覆寫。
本次沒有自動刪除影片、建立排程或更動個人設定。

## 驗證

```powershell
python -m unittest discover -s tests -v
python -m py_compile main.py watchdog.py
```

測試使用模擬串流及暫存檔案，不連線到錄影網站。

## MP4 輸出

需要 FFmpeg（含 libx264）與 ffprobe，可放入 PATH，或設定 CAM4_FFMPEG、CAM4_FFPROBE 為執行檔完整路徑。
錄影中寫入 `.capture`，正常收尾後改成 `.source`，背景工作以 ffprobe 辨識實際格式。
H.264/yuv420p 與 AAC 可直接重新封裝；其他編碼轉為 H.264/yuv420p 與 AAC。
先寫 `.encoding.mp4`，驗證封裝、編碼與正數長度後才發布 `.mp4`，並啟用 faststart。
原始 `.source` 保留，會額外使用磁碟空間；失敗詳情見 `.ffmpeg.log` 與 capture.log，重啟後重試。
強制終止留下的 `.capture` 不會自動處理：確認原程序已停止後，才能手動改成 `.source` 以恢復。
舊版產生的 `.mp4` 不會自動修改。轉檔在錄影結束後開始；長時間直播尚未結束時只有 `.capture` 是正常情況。

## 聊天室實驗版（feature/chat）

預設同步監聽公開聊天室，錄影結束後另產生 `.chat.mp4`：透明底、黃帳號／白內容、黑描邊。
重啟前請在原本的 Python 環境執行 `python -m pip install -r requirements.txt`；預設使用已安裝的 Edge。
沒有抓到訊息時僅產生純影音 `.mp4`，詳情見同名 `.chat-status.json`。
時間同步目前使用接收時間，尚待實錄校準。

- [實作與優先順序](docs/chat-implementation.md)
- [啟動方式、輸出檔與驗收流程](docs/chat-test-plan.md)
