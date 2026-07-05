# 晨報｜每日金融市場資訊聚合網站

## 專案結構
```
finance-news/
├── main.py                  # FastAPI 後端主程式（API + 排程 + 服務前端頁面）
├── database.py               # SQLite 資料庫存取
├── requirements.txt
├── scraper/
│   ├── __init__.py
│   ├── news_scraper.py       # 新聞抓取（經濟日報、工商時報，RSS + 網頁解析備援）
│   └── market_data.py        # 市場數據抓取（yfinance：美股/台股/美債/匯率）
└── static/
    └── index.html            # 前端 Dashboard
```

## 安裝步驟

1. 打開終端機（命令提示字元 / Terminal），切換到 `finance-news` 資料夾：
```bash
cd finance-news
```

2. 安裝套件：
```bash
pip install -r requirements.txt
```
（Mac 若 `pip` 找不到指令，改用 `pip3 install -r requirements.txt`）

## 啟動網站

```bash
uvicorn main:app --reload
```

看到類似這樣的訊息代表啟動成功：
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

接著打開瀏覽器，輸入：
```
http://127.0.0.1:8000
```

就能看到儀表板畫面。

## 運作方式說明

- **第一次啟動**：伺服器啟動時會自動先跑一次抓取（不用等到隔天），所以打開網頁應該就能馬上看到資料
- **之後每天**：排程會在每天早上 **08:00** 自動重新抓取一次
- **想要立即更新**：按網頁右上角「↻ 立即更新」按鈕，或直接呼叫：
```bash
curl -X POST http://127.0.0.1:8000/api/refresh
```
- **資料庫**：所有資料存在 `finance_dashboard.db`（SQLite 檔案），第一次啟動時會自動建立，不需要手動設定

## 常見問題

**Q: 新聞抓取顯示某個來源是 0 則？**
代表該網站當下擋掉了我們的請求（例如 403），這是新聞網站常見的反爬蟲機制，並非程式錯誤導致當機。可以把終端機印出的 log 貼給 Claude，進一步調整 headers 或改用其他來源。

**Q: 市場數據某個標的顯示「資料暫時無法取得」？**
代表 yfinance 那個時間點抓取失敗（常見於美股非交易時段或該代碼暫時異常），下次排程或手動更新時通常會恢復正常。

**Q: 想部署到網路上讓別人也能看到，怎麼做？**
可以將整個 `finance-news` 資料夾上傳到 Render.com 或 Railway.app 這類平台，設定啟動指令為：
```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```
