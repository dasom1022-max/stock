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
    """수집된 데이터를 바탕으로 Gemini가 데일리/위클리 트레이딩 종목을 포함한 리포트를 생성합니다."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    kst_now = get_kst_now()
    time_theme = get_time_context(kst_now.hour)
    
    market_data = get_market_data()
    domestic_news = get_naver_finance_news()
    global_news = get_google_us_news()
    
    prompt = f"""
    너는 여의도 및 월스트리트 최정예 수석 애널리스트이자 단기/스윙 트레이딩 전문가야.
    현재 시각은 한국 시간 {kst_now.strftime('%Y-%m-%d %H:%M')}이며, 이번 브리핑의 주제는 '{time_theme}'이야.
    
    아래 실시간 수집된 지수 데이터, 네이버 국내 금융 뉴스, 구글 국외 경제 뉴스를 철저히 분석하여 텔레그램 단체방에 공유할 종합 투자 브리핑을 작성해줘.
    
    [1. 실시간 주요 지수]
    {market_data}
    
    [2. 국내 주요 뉴스 (네이버 금융)]
    {domestic_news}
    
    [3. 국외 주요 뉴스 (구글 뉴스)]
    {global_news}
    
    [작성 필수 가이드 (마크다운 형식 준수)]
    1. **{time_theme} 요약 및 글로벌 마감/장중 시황**: 핵심 지수와 시장 분위기 한 줄 평.
    2. **국내외 핵심 이슈 및 뉴스 분석**: 시장에 파장을 미칠 주요 뉴스 3~4가지 요약.
    3. **⚡ [스캘핑용 데일리 트레이딩 종목]**:
       - 오늘 하루 강한 변동성이나 거래대금이 집중될 것으로 예상되는 **초단기 매매(스캘핑/데이토레이딩) 종목 1~2개** 추천.
       - 각 종목별 **핵심 모멘텀** 및 **진입/대응 참고 포인트**(간단하게) 제시.
    4. **🔥 [위클리(주간 스윙) 추천 종목 및 섹터]**:
       - 이번 주 수급과 테마 흐름상 우위가 예상되는 **중기/스윙 관점의 위클리 유망 종목 및 섹터 2개** 선정 이유와 함께 제시.
    5. **⚠️ 리스크 관리 및 대응 전략**: 오늘 장 주의해야 할 변수나 리스크 통제 방안.
    
    ※ 텔레그램에서 깨지지 않도록 너무 복잡한 표 형태는 피하고 이모지와 리스트를 활용해 가독성 높게 작성해줘.
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
            print(f"AI 서버 응답 지연/오류 감지 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print("서버 안정화를 위해 15초 대기 후 재시도합니다...")
                time.sleep(15)
            else:
                raise e

def send_telegram_message(message):
    """텔레그램 메시지 전송 (설정된 여러 개의 그룹방으로 동시 전송 및 4096자 초과 시 분할 전송)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_length = 4000
    
    # 쉼표(,)로 구분된 여러 개의 Chat ID를 파싱
    chat_ids = [cid.strip() for cid in CHAT_ID.split(",") if cid.strip()]
    print(f"발송 대상 Chat ID 목록: {chat_ids}")
    
    for chat_id in chat_ids:
        for i in range(0, len(message), max_length):
            chunk = message[i:i + max_length]
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }
            res = requests.post(url, json=payload)
            print(f"방 ID [{chat_id}] 전송 응답: {res.json()}")
            
            # 마크다운 파싱 오류 시 일반 텍스트로 재시도
            if not res.json().get("ok"):
                payload.pop("parse_mode")
                res_retry = requests.post(url, json=payload)
                print(f"방 ID [{chat_id}] 재시도 응답: {res_retry.json()}")

if __name__ == "__main__":
    print("데이터 수집 및 AI 분석 시작...")
    report = generate_stock_report()
    send_telegram_message(report)
    print("텔레그램 전송 완료!")
