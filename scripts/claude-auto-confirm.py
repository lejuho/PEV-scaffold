#!/usr/bin/env python3
"""
Claude Code 자동 확인 스크립트
- "similar commands" 문구가 있으면 2번 (Yes, don't ask again)
- 없으면 1번 (Yes)
"""

import subprocess
import sys
import re

SESSION = "cairn-claude:0"
SIMILAR_KEYWORD = "similar commands"


def capture_pane():
    """tmux pane 내용 캡처"""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", SESSION],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout
    except Exception as e:
        print(f"Error capturing pane: {e}")
        return ""


def detect_option_type(pane_text: str) -> int:
    """
    옵션 타입 판별
    - "similar commands" 포함 → 2번
    - 아니면 1번
    """
    text_lower = pane_text.lower()

    if SIMILAR_KEYWORD in text_lower:
        print("→ 'similar commands' 감지 → 2번 선택")
        return 2
    else:
        print("→ 일반 Yes/No → 1번 선택")
        return 1


def send_to_tmux(choice: int):
    """tmux에 숫자 + Enter 전송"""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", SESSION, str(choice), "Enter"],
            check=True,
            timeout=5
        )
        print(f"✓ {choice}번 전송 완료")
    except subprocess.CalledProcessError as e:
        print(f"Error sending to tmux: {e}")
        sys.exit(1)


def main():
    print("Claude 자동 확인 스크립트 실행...")

    pane_text = capture_pane()
    if not pane_text:
        print("Pane 내용을 가져올 수 없습니다.")
        sys.exit(1)

    choice = detect_option_type(pane_text)
    send_to_tmux(choice)


if __name__ == "__main__":
    main()