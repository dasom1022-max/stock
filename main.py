import os
import sys
import time
from typing import Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError

# ==============================================================================
# 1. 과금 방지 및 안정성 설정 상수
# ==============================================================================
MODEL_NAME = "gemini-2.5-flash"  # 비용 효율이 높은 기본 모델
MAX_INPUT_CHARS = 15000          # 프롬프트로 넘길 시장 데이터 최대 글자 수
MAX_OUTPUT_TOKENS = 2500         # 리포트 최대 출력 토큰 상한선
THINKING_BUDGET = 0              # 사고(Thinking) 토큰 과금 차단 (정밀 추론 필요 시 512~1024 등으로 조정)
MAX_RETRIES = 3                  # 일시적 오류(429, 5xx) 최대 재시도 횟수
RETRY_DELAY_SECONDS = 15         # 재시도 대기 시간(초)

# 재시도하지 않고 즉시 중단할 클라이언트/결제/인증 오류 코드
FATAL_STATUS_CODES = {400, 401, 402, 403, 404}


# ==============================================================================
# 2. 데이터 수집 함수 (기존 로직에 맞게 구현/연결)
# ==============================================================================
def collect_market_data() -> str:
    """
    시장 지수, 수급, 뉴스 등의 데이터를 수집해 문자열로 반환합니다.
    데이터가 없거나 비어 있으면 빈 문자열을 반환해 불필요한 API 호출을 막습니다.
    """
    # TODO: 기존 main.py에 있던 시장 데이터 수집 코드를 여기에 연결하세요.
    # 예시:
    # market_data = fetch_naver_finance_and_news()
    market_data = os.getenv("SAMPLE_MARKET_DATA", "").strip()
    return market_data


# ==============================================================================
# 3. 과금 방지 로직이 적용된 Gemini 리포트 생성 함수
# ==============================================================================
def generate_stock_report(market_data: Optional[str] = None) -> str:
    if not market_data or not market_data.strip():
        raise ValueError("수집된 시장 데이터가 비어 있어 Gemini API 호출을 건너뜁니다.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 GEMINI_API_KEY가 설정되어 있지 않습니다.")

    client = genai.Client(api_key=api_key)

    # 입력 글자 수 제한 (비정상적인 대용량 텍스트 유입 시 과금 폭탄 방지)
    raw_text = market_data.strip()
    if len(raw_text) > MAX_INPUT_CHARS:
        print(
            f"[입력 제한] 시장 데이터가 {len(raw_text)}자입니다. "
            f"과금 방지를 위해 앞 {MAX_INPUT_CHARS}자만 사용합니다."
        )
        safe_market_data = raw_text[:MAX_INPUT_CHARS] + "\n...(이하 생략)..."
    else:
        safe_market_data = raw_text

    prompt = f"""
당신은 간결하고 핵심만 짚는 주식 시황 분석가입니다.
제공된 [시장 데이터]만을 근거로 오늘의 핵심 시황 리포트를 작성해 주세요.
불필요한 서론·미사여구는 줄이고, 주요 지수/수급/이슈/리스크 위주로 정리하세요.

[시장 데이터]
{safe_market_data}
""".strip()

    config = types.GenerateContentConfig(
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.3,
        thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )

            # 실제 소모된 토큰 수 로그 기록
            if response.usage_metadata:
                usage = response.usage_metadata
                print(
                    f"[토큰 사용량] 모델={MODEL_NAME} | "
                    f"입력={usage.prompt_token_count} | "
                    f"출력={usage.candidates_token_count} | "
                    f"합계={usage.total_token_count}"
                )

            report_text = (response.text or "").strip()
            if not report_text:
                raise RuntimeError("모델이 빈 응답을 반환했습니다.")

            return report_text

        except APIError as e:
            last_error = e
            status_code = getattr(e, "code", None)

            # 결제 크레딧 소진(402), 인증/권한 오류(401, 403), 잘못된 요청(400)은 재시도 없이 즉시 종료
            if status_code in FATAL_STATUS_CODES:
                print(
                    f"[즉시 중단] 재시도로 해결되지 않는 API 오류 발생 "
                    f"(HTTP {status_code}): {e.message}"
                )
                raise

            print(
                f"AI 서버 응답 지연/오류 감지 (시도 {attempt}/{MAX_RETRIES}, "
                f"코드 {status_code}): {e.message}"
            )
            if attempt < MAX_RETRIES:
                print(f"서버 안정화를 위해 {RETRY_DELAY_SECONDS}초 대기 후 재시도합니다...")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise

        except Exception as e:
            last_error = e
            print(f"리포트 생성 중 예외 발생 (시도 {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                print(f"서버 안정화를 위해 {RETRY_DELAY_SECONDS}초 대기 후 재시도합니다...")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise

    if last_error:
        raise last_error
    raise RuntimeError("알 수 없는 이유로 리포트 생성에 실패했습니다.")


# ==============================================================================
# 4. 결과 발송 함수 (기존 텔레그램/파일 저장 로직 연결)
# ==============================================================================
def send_report(report: str) -> None:
    """
    생성된 리포트를 텔레그램 또는 파일 등으로 출력/발송합니다.
    """
    print("\n================ [생성된 주식 시황 리포트] ================")
    print(report)
    print("===========================================================\n")

    # TODO: 기존 main.py의 텔레그램 발송 또는 파일 저장 코드를 여기에 연결하세요.


# ==============================================================================
# 5. 메인 실행 진입점
# ==============================================================================
def main() -> int:
    print("데이터 수집 및 AI 분석 시작...")

    try:
        market_data = collect_market_data()
        if not market_data:
            print("수집된 시장 데이터가 없어 AI 호출 없이 정상 종료합니다.")
            return 0

        report = generate_stock_report(market_data)
        send_report(report)
        print("작업이 정상적으로 완료되었습니다.")
        return 0

    except ValueError as e:
        print(f"[입력 검증 중단] {e}")
        return 0
    except APIError as e:
        print(f"[Gemini API 오류 종료] {e}")
        return 1
    except Exception as e:
        print(f"[실행 실패] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
