"""Claude가 작성한 보고서(reports/latest.md)를 텔레그램으로 발송합니다.

사용법: python send_report.py reports/latest.md
환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS(콤마 구분) 또는 TELEGRAM_CHAT_ID
"""

import os
import sys

import requests

CHUNK_SIZE = 3900


def get_chat_ids() -> list[str]:
    raw = (os.environ.get("TELEGRAM_CHAT_IDS") or "") + "," + (os.environ.get("TELEGRAM_CHAT_ID") or "")
    ids: list[str] = []
    for part in raw.split(","):
        cid = part.strip()
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def split_message(message: str) -> list[str]:
    """줄 단위로 끊어 텔레그램 길이 제한(4096자) 안으로 나눕니다."""
    chunks, current = [], ""
    for line in message.splitlines(keepends=True):
        if len(current) + len(line) > CHUNK_SIZE and current:
            chunks.append(current)
            current = ""
        while len(line) > CHUNK_SIZE:
            chunks.append(line[:CHUNK_SIZE])
            line = line[CHUNK_SIZE:]
        current += line
    if current.strip():
        chunks.append(current)
    return chunks


def send_to_single_chat(token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_message(message):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code != 200:
            # HTML 태그 오류 시 일반 텍스트로 재발송
            payload.pop("parse_mode")
            resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "reports/latest.md"
    with open(path, encoding="utf-8") as f:
        message = f.read().strip()
    if not message:
        raise RuntimeError(f"{path} 이(가) 비어 있습니다.")

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_ids = get_chat_ids()
    if not token:
        raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN이 누락되었습니다.")
    if not chat_ids:
        raise RuntimeError("환경변수 TELEGRAM_CHAT_IDS 또는 TELEGRAM_CHAT_ID가 누락되었습니다.")

    errors = []
    for cid in chat_ids:
        try:
            send_to_single_chat(token, cid, message)
            print(f"텔레그램 발송 성공 -> chat_id: {cid}")
        except Exception as exc:  # noqa: BLE001
            print(f"텔레그램 발송 실패 -> chat_id: {cid}, 오류: {exc}")
            errors.append(f"{cid}: {exc}")
    if errors:
        raise RuntimeError("발송 실패: " + " | ".join(errors))


if __name__ == "__main__":
    main()
