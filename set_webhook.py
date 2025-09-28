#!/usr/bin/env python3
"""
Telegram 봇의 webhook을 설정하는 스크립트
Vercel 배포 후 이 스크립트를 실행하여 webhook URL을 설정하세요.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
VERCEL_URL = os.getenv('VERCEL_URL')  # Vercel에서 자동으로 설정됨

def set_webhook():
    """Telegram 봇에 webhook URL 설정"""
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        return False

    if not VERCEL_URL:
        print("VERCEL_URL이 설정되지 않았습니다. Vercel에 배포한 후 확인하세요.")
        return False

    webhook_url = f"https://{VERCEL_URL}/api/webhook"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    data = {
        'url': webhook_url,
        'allowed_updates': ['message']
    }

    try:
        response = requests.post(url, json=data)
        result = response.json()

        if result.get('ok'):
            print(f"✅ Webhook 설정 성공: {webhook_url}")
            return True
        else:
            print(f"❌ Webhook 설정 실패: {result}")
            return False

    except Exception as e:
        print(f"❌ Webhook 설정 중 오류 발생: {e}")
        return False

def get_webhook_info():
    """현재 webhook 정보 확인"""
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"

    try:
        response = requests.get(url)
        result = response.json()

        if result.get('ok'):
            webhook_info = result.get('result', {})
            print("현재 webhook 정보:")
            print(f"  URL: {webhook_info.get('url', '설정되지 않음')}")
            print(f"  Pending updates: {webhook_info.get('pending_update_count', 0)}")
            if webhook_info.get('last_error_message'):
                print(f"  마지막 오류: {webhook_info['last_error_message']}")
        else:
            print(f"Webhook 정보 조회 실패: {result}")

    except Exception as e:
        print(f"Webhook 정보 조회 중 오류 발생: {e}")

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'info':
        get_webhook_info()
    else:
        print("Telegram 봇 webhook 설정 중...")
        success = set_webhook()
        if success:
            print("\nWebhook 설정이 완료되었습니다!")
            print("이제 Telegram 봇이 Vercel 서버리스에서 작동합니다.")
        else:
            print("\nWebhook 설정에 실패했습니다.")
            print("환경변수를 확인하고 다시 시도하세요.")
