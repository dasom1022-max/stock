import os
import time
import datetime
import requests
import feedparser
import yfinance as yf
from bs4 import BeautifulSoup
from google import genai

# 환경 변수 불러오기
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def get_kst_now():
    """현재 한국 시간(KST)을 반환합니다."""
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return utc_now + datetime.timedelta(hours=9)

def get_market_data():
    """Yahoo Finance에서 글로벌 및 국내 주요 지수 데이터를 수집합니다."""
    tickers = {
        "S&P 500": "^GSPC",
        "Nasdaq": "^IXIC",
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "USD/KRW": "USDKRW=X"
    }
    data_str = "📊 **[주요 지수 현황]**\n"
    try:
        for name, ticker in tickers.items():
            t = yf.Ticker(ticker)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                close = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2]
                change = ((close - prev) / prev) * 100
                emoji = "🟢" if change >= 0 else "🔴"
                data_str += f"- {name}: `{close:,.2f}` ({emoji} {change:+.2f}%)\n"
        return data_str
    except Exception as e:
        return f"지수 데이터 수집 오류: {e}\n"

def get_naver_finance_news():
    """네이버 금융 주요 뉴스(실시간 속보) 헤드라인을 수집합니다."""
    url = "https://finance.naver.com/news/mainnews.naver"
    headers = {"User-Agent": "Mozilla/5.0"}
    news_list = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select(".mainNewsList .articleSubject a")
        for a in articles[:12]:
            title = a.get_text(strip=True)
            if title:
                news_list.append(f"- {title}")
        return "\n".join(news_list) if news_list else "수집된 국내 뉴스 없음"
    except Exception as e:
        return f"네이버 뉴스 수집 오류: {e}"

def get_google_us_news():
    """구글 뉴스(영문/미국 증시 및 경제) RSS에서 최신 뉴스를 수집합니다."""
    rss_url = "https://news.google.com/rss/search?q=US+stock+market+OR+Nasdaq+OR+Federal+Reserve+when:1d&hl=en-US&gl=US&ceid=US:en"
    news_list = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:12]:
            news_list.append(f"- {entry.title}")
        return "\n".join(news_list) if news_list else "수집된 국외 뉴스 없음"
    except Exception as e:
        return f"구글 뉴스 수집 오류: {e}"

def get_time_context(hour):
    """실행 시간대별 브리핑 컨셉을 설정합니다."""
    if 5 <= hour < 9:
        return "🌅 [오전 7시 모닝 브리핑] 간밤의 미국 증시 마감 결과와 오늘 국내 증시 개장 전 체크포인트"
    elif 9 <= hour < 13:
        return "📈 [오전 11시 오전장 브리핑] 국내 증시 개장 흐름, 장 초반 수급 및 주도 섹터 분석"
    elif 13 <= hour < 16:
        return "⚡ [오후 2시 오후장 브리핑] 장 후반부 시장 동향, 특징주 점검 및 장 마감 대응 전략"
    else:
        return "🌃 [오후 6시 장마감 & 야간 프리뷰] 오늘 국내 증시 마감 총평과 오늘 밤 미국 증시 주요 관전 포인트"

def generate_stock_report():
    """수집된 데이터를 바탕으로 Gemini가 시간대별 맞춤 리포트를 생성합니다. (503 에러 대비 자동 재시도 로직 포함)"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    kst_now = get_kst_now()
    time_theme = get_time_context(kst_now.hour)
    
    market_data = get_market_data()
    domestic_news = get_naver_finance_news()
    global_news = get_google_us_news()
    
    prompt = f"""
    너는 여의도 및 월스트리트 출신의 전문 주식 수석 애널리스트야.
    현재 시각은 한국 시간 {kst_now.strftime('%Y-%m-%d %H:%M')}이며, 이번 브리핑의 주제는 '{time_theme}'이야.
    
    아래 실시간 수집된 지수 데이터, 네이버 국내 금융 뉴스, 구글 국외 경제 뉴스를 종합 분석하여 텔레그램 단체방에 공유할 브리핑을 작성해줘.
    
    [1. 실시간 주요 지수]
    {market_data}
    
    [2. 국내 주요 뉴스 (네이버 금융)]
    {domestic_news}
    
    [3. 국외 주요 뉴스 (구글 뉴스)]
    {global_news}
    
    [작성 필수 가이드]
    1. 최상단에 '{time_theme}' 제목과 핵심 지수 요약을 깔끔하게 배치할 것.
    2. **국내외 핵심 뉴스 요약**: 수집된 뉴스 중 시장에 영향을 줄 핵심 이슈 3~4가지를 요약할 것.
    3. **유망 섹터 & 테마 분석**: 현재 뉴스와 수급 흐름상 가장 주목해야 할 섹터 2~3가지를 선정하고 이유를 설명할 것.
    4. **관심 종목 아이디어**: 선정된 섹터의 대장주 또는 수혜주(국내/미국 종목 모두 가능)와 투자 포인트를 제시할 것.
    5. **리스크 및 대응 전략**: 주의해야 할 변수나 매매 전략을 한 줄로 정리할 것.
    
    ※ 텔레그램 마크다운(`*굵게*`, `- 리스트` 등)을 사용하되, 특수문자 파싱 오류가 나지 않도록 깔끔하고 가독성 좋게 작성해줘.
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"AI 서버 과부하 감지 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)  # 5초 대기 후 재시도
            else:
                raise e

def send_telegram_message(message):
    """텔레그램 메시지 전송 (여러 그룹방 동시 전송 및 4096자 초과 시 분할 전송)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_length = 4000
    
    chat_ids = [cid.strip() for cid in CHAT_ID.split(",") if cid.strip()]
    
    for chat_id in chat_ids:
        for i in range(0, len(message), max_length):
            chunk = message[i:i + max_length]
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }
            res = requests.post(url, json=payload)
            if not res.json().get("ok"):
                payload.pop("parse_mode")
                requests.post(url, json=payload)

if __name__ == "__main__":
    print("데이터 수집 및 AI 분석 시작...")
    report = generate_stock_report()
    send_telegram_message(report)
    print("텔레그램 전송 완료!")
