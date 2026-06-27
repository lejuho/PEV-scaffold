#!/usr/bin/env python3
"""
Telegram Bot - Claude Auto Responder Log Checker
Usage: /check [number]
"""

import telebot
import os
from datetime import datetime

# 설정 (환경변수에서 읽음)
TOKEN = os.environ.get("HERMES_TELEGRAM_TOKEN", "")
CHAT_ID = int(os.environ.get("HERMES_CHAT_ID", "0") or "0")
LOG_FILE = "/home/pi/cairn/logs/claude-auto-responder.log"
DEFAULT_LINES = 5
MAX_LINES = 30

if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
    exit(1)

bot = telebot.TeleBot(TOKEN)


def get_recent_logs(n: int = DEFAULT_LINES) -> str:
    if not os.path.exists(LOG_FILE):
        return "❌ 로그 파일을 찾을 수 없습니다."

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        lines = [line.strip() for line in lines if line.strip()]
        recent = lines[-n:] if len(lines) >= n else lines

        if not recent:
            return "로그가 아직 없습니다."

        # 가장 최근 로그 시간 차이 계산
        latest_line = recent[-1]
        time_diff_str = ""
        warning = ""

        try:
            # 로그 형식: 2026-06-25 06:05:19 | INFO | ...
            timestamp_str = latest_line.split(" | ")[0]
            log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            diff_minutes = int((now - log_time).total_seconds() / 60)

            time_diff_str = f" (최근 활동: {diff_minutes}분 전)"

            if diff_minutes >= 20:
                warning = "\n⚠️ 완료 여부 확인 추천"
        except:
            pass

        result = f"📋 Claude Auto Responder 최근 {len(recent)}건{time_diff_str}\n\n"
        for line in recent:
            result += f"• {line}\n"

        if warning:
            result += warning

        return result

    except Exception as e:
        return f"❌ 로그 읽기 실패: {e}"


@bot.message_handler(commands=['check'])
def handle_check(message):
    if message.chat.id != CHAT_ID:
        return

    args = message.text.split()
    n = DEFAULT_LINES

    if len(args) > 1:
        try:
            n = int(args[1])
            n = max(1, min(n, MAX_LINES))
        except ValueError:
            n = DEFAULT_LINES

    response = get_recent_logs(n)
    bot.reply_to(message, response)

    # 타이머 리셋
    try:
        with open("/tmp/claude-last-activity", "w") as f:
            f.write(str(int(__import__("time").time())))
        if os.path.exists("/tmp/claude-notified"):
            os.remove("/tmp/claude-notified")
    except:
        pass


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.chat.id != CHAT_ID:
        return

    help_text = (
        "Claude Auto Responder 로그 확인 봇\n\n"
        "• /check - 최근 5건\n"
        "• /check 10 - 최근 10건 (최대 30)"
    )
    bot.reply_to(message, help_text)


if __name__ == "__main__":
    print(f"[{datetime.now()}] Claude Check Bot 시작")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
