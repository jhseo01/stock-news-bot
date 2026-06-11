"""10분마다 GitHub Actions가 실행하는 메인 진입점.

순서: ① 텔레그램 명령 처리 → ② 브리핑 시간이면 전송 → ③ 속보 체크(주기 도래 시)
일시정지(/pause) 상태여도 명령 처리는 계속 동작해야 /resume을 받을 수 있다.
"""
import os
import sys
import time

import breaking
from briefing import send_if_due
from commands import process_commands
from settings import load_bot_state, load_settings, save_bot_state


def run() -> None:
    errors = []

    try:
        process_commands()
    except Exception as e:
        errors.append(f"명령 처리 실패: {e}")

    s = load_settings()
    if s.get("paused"):
        print("일시정지 상태 — 브리핑·속보를 건너뜁니다.")
    else:
        try:
            if send_if_due(force=bool(os.environ.get("FORCE_BRIEFING"))):
                print("브리핑 전송 완료")
        except Exception as e:
            errors.append(f"브리핑 실패: {e}")

        try:
            state = load_bot_state()
            period = s.get("breaking_period_minutes", 10)
            elapsed = time.time() - state.get("last_breaking_ts", 0)
            # 워크플로 실행이 몇 분 지연돼도 주기를 건너뛰지 않도록 1분 여유를 둔다
            if elapsed >= period * 60 - 60:
                breaking.main()
                state = load_bot_state()
                state["last_breaking_ts"] = time.time()
                save_bot_state(state)
            else:
                print(f"속보 체크 주기({period}분) 미도래 — 건너뜁니다.")
        except Exception as e:
            errors.append(f"속보 체크 실패: {e}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
