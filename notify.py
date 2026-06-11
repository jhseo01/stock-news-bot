"""텔레그램 메시지 전송. 토큰이 없으면 콘솔에 출력한다(로컬 테스트용)."""
import os

import requests

MAX_LEN = 4000  # 텔레그램 한 메시지 한도(4096)보다 약간 여유 있게


def send_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[DRY-RUN] 텔레그램 토큰이 없어 콘솔에 출력합니다:\n")
        print(text)
        print("-" * 40)
        return

    for chunk in _split(text):
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()


def _split(text: str) -> list[str]:
    """4096자 제한을 넘으면 줄 단위로 나눈다."""
    if len(text) <= MAX_LEN:
        return [text]

    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks
