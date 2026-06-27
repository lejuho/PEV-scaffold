#!/usr/bin/env python3
import subprocess
import time
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import requests

SESSION = os.environ.get("HERMES_CLAUDE_PANE", "cairn-claude:0")
CHECK_INTERVAL = int(os.environ.get("CLAUDE_AUTO_RESPONDER_INTERVAL", "120"))
LOG_DIR = os.environ.get("HERMES_LOG_DIR", "/home/pi/cairn/logs")
LOG_FILE = os.environ.get("CLAUDE_AUTO_RESPONDER_LOG", os.path.join(LOG_DIR, "claude-auto-responder.log"))
MAX_LOG_SIZE = 5 * 1024 * 1024
BACKUP_COUNT = 7
SIMILAR_KEYWORD = "similar commands"
PROMPT_TAIL_LINES = 45
PROMPT_MARKERS = (
    "Do you want to proceed?",
    "Do you want to allow",
    "Bash command",
    "Proceed?"
)
YES_OPTION_RE = re.compile(r"(?m)^\s*(?:❯\s*)?1[.)]\s*Yes\b")
DONT_ASK_OPTION_RE = re.compile(r"(?mi)^\s*2[.)]\s*Yes,?\s+and\s+(?:don[’']?t|do not)\s+ask\b")
NO_OPTION_RE = re.compile(r"(?m)^\s*\d+[.)]\s*No\b")
TELEGRAM_TOKEN = os.environ.get("HERMES_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("HERMES_CHAT_ID", "")

def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def capture_pane():
    try:
        result = subprocess.run(["tmux", "capture-pane", "-p", "-t", SESSION, "-S", "-100"], capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        logging.error(f"Pane capture 실패: {e}")
        return None

def is_confirmation_prompt(text):
    return confirmation_signature(text) is not None

def confirmation_window(text):
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines[-PROMPT_TAIL_LINES:])

def confirmation_signature(text):
    window = confirmation_window(text)
    has_prompt_marker = any(marker in window for marker in PROMPT_MARKERS)
    has_numbered_options = YES_OPTION_RE.search(window) and NO_OPTION_RE.search(window)
    if not (has_prompt_marker and has_numbered_options):
        return None
    compact = "\n".join(line.strip() for line in window.splitlines() if line.strip())
    return compact[-500:]

def detect_choice(text):
    window = confirmation_window(text)
    if SIMILAR_KEYWORD in window.lower() or DONT_ASK_OPTION_RE.search(window):
        return "2"
    return "enter"

def send_choice(choice):
    try:
        if choice != "enter":
            subprocess.run(["tmux", "send-keys", "-t", SESSION, str(choice)], timeout=5)
            time.sleep(0.3)
        subprocess.run(["tmux", "send-keys", "-t", SESSION, "Enter"], timeout=5)
        return True
    except Exception as e:
        logging.error(f"Choice 전송 실패: {e}")
        return False

def is_claude_idle(text):
    if not text:
        return False
    tail = text[-2500:]
    prompt_idx = tail.rfind("❯")
    current = tail[prompt_idx:] if prompt_idx >= 0 else tail[-800:]
    working = ["Perusing", "Running", "Working", "Waiting", "Esc to interrupt", "Bash("]
    if any(kw in current for kw in working):
        return False
    idle = ["accept edits on", "❯", "Tip: Use /btw", "? for shortcuts"]
    if any(indicator in current for indicator in idle):
        return True
    return False

def send_telegram_notification(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.info("Telegram config missing; idle notification skipped")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            logging.info("Telegram 알림 전송 완료")
        else:
            logging.error(f"Telegram 전송 실패: {response.text}")
    except Exception as e:
        logging.error(f"Telegram 알림 전송 중 에러: {e}")

def main():
    logger = setup_logging()
    logger.info("Claude Auto Responder 시작 (idle 즉시 알림 모드)")
    logger.info(f"세션: {SESSION}, 검사 주기: {CHECK_INTERVAL}초")
    logger.info("=" * 50)
    last_idle_state = None
    last_confirmation_sig = None
    while True:
        try:
            pane_text = capture_pane()
            if not pane_text:
                time.sleep(CHECK_INTERVAL)
                continue

            confirmation_sig = confirmation_signature(pane_text)
            if confirmation_sig:
                choice = detect_choice(pane_text)
                reason = "dont-ask/similar 옵션 감지" if choice == "2" else "일반 Yes/No 기본 선택"
                if confirmation_sig == last_confirmation_sig:
                    logger.info("동일 확인 프롬프트 이미 처리됨 → 재전송 생략")
                else:
                    success = send_choice(choice)
                    if success:
                        last_confirmation_sig = confirmation_sig
                        logger.info(f"프롬프트 감지 → {'Enter' if choice == 'enter' else choice + '번'} 전송 ({reason})")
                    else:
                        logger.warning(f"프롬프트 감지되었으나 전송 실패 (choice={choice})")
            else:
                last_confirmation_sig = None

            current_idle = is_claude_idle(pane_text)
            if current_idle and not last_idle_state:
                logger.info("Claude idle 상태 감지 → Telegram 알림 전송")
                send_telegram_notification("✅ Claude 작업이 종료되었습니다. 다음 지시를 받을 준비가 되었습니다.")
            last_idle_state = current_idle
        except KeyboardInterrupt:
            logger.info("사용자에 의해 종료됨")
            break
        except Exception as e:
            logger.error(f"예상치 못한 에러: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
