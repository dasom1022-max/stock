# stock — Claude 주식 시황 브리핑

평일 07·11·14·18시(KST)에 국내외 증시를 분석해 텔레그램으로 보냅니다.

## 흐름
1. **Claude 예약 작업**(평일 06:50·10:50·13:50·17:50)이 시작되면 `Market Snapshot` 워크플로를 실행
2. **GitHub Actions**가 pykrx·yfinance로 지수·환율·금리·원자재·미국 빅테크·관심종목 시세를 수집 → `data/snapshot.md` 커밋
3. **Claude**가 스냅샷 + 웹 검색(뉴스)으로 `ANALYSIS_GUIDE.md` 형식에 맞춰 분석 → `reports/latest.md` 커밋 (지난 보고서는 `reports/archive/`)
4. `reports/latest.md`가 바뀌면 **`Send Report to Telegram`** 워크플로가 텔레그램으로 발송

## 파일
- `watchlist.json` — 관심종목·해외 지표 목록 (종목코드가 틀리거나 비어 있으면 pykrx로 이름 검색해 자동 보정)
- `market_data.py` — 시세 수집 (`python market_data.py` 로 화면 출력 테스트)
- `ANALYSIS_GUIDE.md` — 회차별 분석 지시와 보고서 형식 (여기만 고치면 분석 내용이 바뀜)
- `send_report.py` — 텔레그램 발송

## 필요한 Secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`(또는 `TELEGRAM_CHAT_ID`). `GEMINI_API_KEY`는 더 이상 쓰지 않습니다.
