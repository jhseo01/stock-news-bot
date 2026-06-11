"""텔레그램으로 받은 설정 명령을 처리한다.

봇은 상시 서버가 아니라 주기적으로 실행되므로, 그동안 쌓인 메시지를
getUpdates로 한꺼번에 가져와 처리하고 결과를 답장한다.
"""
import html
import os

import requests

from notify import send_message
from prices import get_price, lookup_code, price_arrow
from settings import load_bot_state, load_settings, save_bot_state, save_settings

MIN_PERIOD = 10  # GitHub Actions 무료 스케줄러의 최소 실행 주기(분)

HELP = """🤖 <b>사용 가능한 명령어</b>

/list — 현재 설정 보기
/price — 등록 종목 현재가 조회
/price 종목명 — 특정 종목 현재가 (예: /price 카카오)
/add 종목명 — 종목 추가 (예: /add 카카오)
/add 종목명 검색어 — 검색어 직접 지정
   (예: /add 카카오 카카오 OR 카카오페이)
/del 종목명 — 종목 삭제
/time 시간 — 브리핑 시간 변경, 24시 기준 (예: /time 8)
/period 분 — 속보 체크 주기 변경, 최소 10분 (예: /period 30)
/pause — 브리핑·속보 일시정지
/resume — 재개
/kw — 속보 키워드 보기
/kw_add 단어 — 속보 키워드 추가
/kw_del 단어 — 속보 키워드 삭제
/help — 이 도움말

⏱ 명령은 최대 10분 안에 처리됩니다."""


def price_line(name: str, code: str) -> tuple[str, str]:
    """(표시 줄, 체결 시각)을 반환한다."""
    try:
        p = get_price(code)
    except Exception:
        return f"➖ {html.escape(name)}: 시세 조회 실패", ""
    arrow = price_arrow(p["direction"])
    line = (
        f"{arrow} <b>{html.escape(p['name'])}</b> {p['price']}원 "
        f"({p['diff']}, {p['rate']}%)"
    )
    return line, p["traded_at"]


def build_price_report(s: dict, target: str | None) -> tuple[str, bool]:
    """(시세 메시지, 종목코드 캐시 변경 여부)를 반환한다."""
    codes = s.setdefault("codes", {})
    changed = False

    if target:  # 특정 종목 하나만 조회 (등록 안 된 종목도 가능)
        code, _ = lookup_code(target)
        if not code:
            return f"❌ '{html.escape(target)}' 종목을 찾지 못했습니다.", False
        line, _ = price_line(target, code)
        return f"💰 <b>현재가</b>\n{line}", False

    lines = ["💰 <b>현재가</b>"]
    traded_at = ""
    for name in s["stocks"]:
        code = codes.get(name)
        if not code:
            try:
                code, _ = lookup_code(name)
            except Exception:
                code = None
            if code:
                codes[name] = code
                changed = True
        if not code:
            lines.append(f"➖ {html.escape(name)}: 종목코드를 찾지 못함")
            continue
        line, ts = price_line(name, code)
        lines.append(line)
        if not traded_at:
            traded_at = ts

    if traded_at and len(traded_at) >= 16:
        lines.append("")
        lines.append(f"🕐 {traded_at[5:10]} {traded_at[11:16]} 기준")
    return "\n".join(lines), changed


def format_settings(s: dict) -> str:
    status = "⏸ 일시정지 중 (/resume 으로 재개)" if s.get("paused") else "▶️ 동작 중"
    lines = [
        "📋 <b>현재 설정</b>",
        "",
        f"상태: {status}",
        f"⏰ 브리핑: 매일 {s['briefing_hour']}시",
        f"🔄 속보 체크 주기: {s['breaking_period_minutes']}분",
        "",
        "📈 종목:",
    ]
    for name, query in s["stocks"].items():
        extra = f" (검색어: {html.escape(query)})" if query != name else ""
        lines.append(f" • {html.escape(name)}{extra}")
    lines.append("")
    lines.append(f"🚨 속보 키워드: {html.escape(', '.join(s['breaking_keywords']))}")
    return "\n".join(lines)


def handle(text: str, s: dict) -> tuple[str | None, bool]:
    """명령 처리. (답장, 설정변경여부)를 반환한다."""
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]  # "/add@봇이름" 형태 지원
    args = parts[1:]

    if cmd in ("/start", "/help"):
        return HELP, False

    if cmd == "/list":
        return format_settings(s), False

    if cmd == "/price":
        return build_price_report(s, args[0] if args else None)

    if cmd == "/add":
        if not args:
            return "사용법: /add 종목명 (예: /add 카카오)", False
        name = args[0]
        query = " ".join(args[1:]) if len(args) > 1 else name
        s["stocks"][name] = query
        return f"✅ <b>{html.escape(name)}</b> 추가 완료 (총 {len(s['stocks'])}종목)", True

    if cmd == "/del":
        if not args:
            return "사용법: /del 종목명", False
        name = args[0]
        if name not in s["stocks"]:
            current = ", ".join(s["stocks"])
            return f"❌ '{html.escape(name)}' 종목이 없습니다.\n현재: {html.escape(current)}", False
        del s["stocks"][name]
        s.get("codes", {}).pop(name, None)
        return f"🗑 <b>{html.escape(name)}</b> 삭제 완료 (총 {len(s['stocks'])}종목)", True

    if cmd == "/time":
        if not args or not args[0].isdigit() or not 0 <= int(args[0]) <= 23:
            return "사용법: /time 시간 (0~23, 예: /time 8 → 매일 8시)", False
        s["briefing_hour"] = int(args[0])
        return f"⏰ 브리핑 시간을 매일 <b>{s['briefing_hour']}시</b>로 변경했습니다.", True

    if cmd in ("/period", "/priod"):  # 오타도 허용
        if not args or not args[0].isdigit() or int(args[0]) < 1:
            return f"사용법: /period 분 (최소 {MIN_PERIOD}분, 예: /period 30)", False
        minutes = int(args[0])
        note = ""
        if minutes < MIN_PERIOD:
            minutes = MIN_PERIOD
            note = f"\n(무료 스케줄러의 최소 주기인 {MIN_PERIOD}분으로 설정했습니다)"
        s["breaking_period_minutes"] = minutes
        return f"🔄 속보 체크 주기를 <b>{minutes}분</b>으로 변경했습니다.{note}", True

    if cmd == "/pause":
        if s.get("paused"):
            return "이미 일시정지 상태입니다. /resume 으로 재개할 수 있습니다.", False
        s["paused"] = True
        return "⏸ 일시정지했습니다. 브리핑과 속보 알림이 중단됩니다.\n/resume 을 보내면 재개됩니다.", True

    if cmd == "/resume":
        if not s.get("paused"):
            return "이미 동작 중입니다.", False
        s["paused"] = False
        return "▶️ 재개했습니다. 브리핑과 속보 알림이 다시 동작합니다.", True

    if cmd == "/kw":
        return f"🚨 속보 키워드: {html.escape(', '.join(s['breaking_keywords']))}", False

    if cmd == "/kw_add":
        if not args:
            return "사용법: /kw_add 단어", False
        word = args[0]
        if word not in s["breaking_keywords"]:
            s["breaking_keywords"].append(word)
        return f"✅ 키워드 추가: {html.escape(', '.join(s['breaking_keywords']))}", True

    if cmd == "/kw_del":
        if not args:
            return "사용법: /kw_del 단어", False
        word = args[0]
        if word not in s["breaking_keywords"]:
            return f"❌ '{html.escape(word)}' 키워드가 없습니다.", False
        s["breaking_keywords"].remove(word)
        return f"🗑 키워드 삭제: {html.escape(', '.join(s['breaking_keywords']))}", True

    if cmd.startswith("/"):
        return "알 수 없는 명령입니다. /help 를 입력해보세요.", False

    return None, False  # 일반 메시지는 무시


def process_commands() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("토큰이 없어 명령 처리를 건너뜁니다.")
        return

    state = load_bot_state()
    offset = state.get("last_update_id", 0) + 1
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset},
        timeout=30,
    )
    resp.raise_for_status()
    updates = resp.json().get("result", [])
    if not updates:
        print("새 명령 없음")
        return

    settings = load_settings()
    changed = False
    for update in updates:
        state["last_update_id"] = update["update_id"]
        msg = update.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue  # 등록된 사용자 외 무시
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        reply, did_change = handle(text, settings)
        changed = changed or did_change
        if reply:
            send_message(reply)
            print(f"명령 처리: {text}")

    if changed:
        save_settings(settings)
    save_bot_state(state)
