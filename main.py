import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from google import genai
from google.genai import types

MODEL_ID = "gemini-3.8-flash"
KST = ZoneInfo("Asia/Seoul")


def detect_slot(now_kst: datetime) -> str:
    """현재 KST 시각에 맞춰 보고 회차(07, 11, 14, 18)를 판별합니다."""
    hour = now_kst.hour
    if hour < 9:
        return "07"
    elif hour < 13:
        return "11"
    elif hour < 16:
        return "14"
    else:
        return "18"


def build_prompt(slot: str, now_str: str) -> str:
    common_rules = (
        "당신은 한국 및 미국 주식시장을 분석하는 퀀트/시황 애널리스트입니다. "
        "불필요한 미사여구는 빼고 핵심 위주로 간결하게 작성하세요. "
        "텔레그램 가독성을 위해 이모지와 짧은 줄바꿈을 사용하고, "
        "복잡한 마크다운 표 대신 불릿(-)을 사용하세요. "
        "최신 시세와 뉴스는 Google 검색으로 확인하되, 꼭 필요한 핵심만 짧게 요약해 토큰 비용을 아끼세요.\n\n"
        "필수 포함 항목:\n"
        "1. [전체 시장 흐름]\n"
        "2. [유망 섹터] (2~3개, 핵심 모멘텀 요약)\n"
        "3. [데이트레이딩 3종목] (종목명/티커, 진입·손절/목표 관점 한 줄 요약)\n"
        "4. [위클리트레이딩 3종목] (종목명/티커, 수급/추세 관점 한 줄 요약)\n"
        "5. [리스크/체크포인트]\n"
        "※ 마지막에 '본 분석은 참고용이며 투자 판단과 책임은 투자자에게 있습니다.' 한 줄을 붙이세요."
    )

    if slot == "07":
        focus = (
            f"기준 시각: {now_str} (평일 07시 장전 브리핑)\n"
            "특별 지시: 방금 마감한 직전 미국 증시(특히 나스닥, S&P500, 주요 빅테크/반도체, 미 국채금리·원/달러 환율)의 "
            "마감 현황과 핵심 이슈를 반드시 먼저 분석한 뒤, 오늘 국내 증시(코스피·코스닥) 개장 전 체크할 흐름을 연결하세요."
        )
    elif slot == "11":
        focus = (
            f"기준 시각: {now_str} (평일 11시 오전장 브리핑)\n"
            "특별 지시: 오전장 초반 국내 증시(코스피·코스닥) 수급, 주도주 강도, 업종별 등락 흐름을 중심으로 분석하세요."
        )
    elif slot == "14":
        focus = (
            f"기준 시각: {now_str} (평일 14시 오후장 브리핑)\n"
            "특별 지시: 오후장 진입 후 수급 변화, 장중 고점/저점 변동성, 남은 장중 대응 포인트를 중심으로 분석하세요."
        )
    else:  # "18"
        focus = (
            f"기준 시각: {now_str} (평일 18시 마감 및 미 증시 분석 브리핑)\n"
            "특별 지시: 당일 국내 증시(코스피·코스닥) 마감 흐름을 짧게 정리한 뒤, "
            "이어질 미국 시장(나스닥 중심)의 예상 흐름, 주요 경제지표/이벤트, 프리마켓·선물 분위기 및 관전 포인트를 심층 분석하세요."
        )

    return f"{focus}\n\n{common_rules}"


def generate_briefing(slot: str, now_kst: datetime) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 GEMINI_API_KEY가 설정되지 않았습니다.")

    client = genai.Client(api_key=api_key)
    now_str = now_kst.strftime("%Y-%m-%d %H:%M KST")
    prompt = build_prompt(slot, now_str)

    # 비용 절감을 위해 출력 토큰 상한과 낮은 temperature 설정
    config = types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=1600,
        tools=[{"google_search": {}}],
    )

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=config,
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini로부터 빈 응답을 받았습니다.")

    slot_titles = {
        "07": "🌅 07:00 장전 & 직전 나스닥 브리핑",
        "11": "☀️ 11:00 오전장 시황 브리핑",
        "14": "🌤 14:00 오후장 시황 브리핑",
        "18": "🌙 18:00 국내 마감 & 미 증시 흐름 분석",
    }
    header = f"<b>{slot_titles.get(slot, '주식시장 브리핑')}</b>\n<code>{now_str}</code>\n\n"
    return header + text


def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 누락되었습니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunk_size = 3900
    for i in range(0, len(message), chunk_size):
        chunk = message[i : i + chunk_size]
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if i == 0:
            payload["parse_mode"] = "HTML"
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code != 200 and "parse_mode" in payload:
            payload.pop("parse_mode")
            resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()


def main() -> None:
    now_kst = datetime.now(KST)
    if now_kst.weekday() >= 5 and "--force" not in sys.argv:
        print("주말이므로 정기 보고를 건너뜁니다. (--force 옵션으로 강제 실행 가능)")
        return

    slot_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--slot="):
            slot_arg = arg.split("=", 1)[1].strip()

    slot = slot_arg if slot_arg in {"07", "11", "14", "18"} else detect_slot(now_kst)
    report = generate_briefing(slot, now_kst)
    send_telegram(report)
    print(f"[{now_kst.isoformat()}] {slot}시 보고서 발송 완료")


if __name__ == "__main__":
    main()
