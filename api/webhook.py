import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from langchain_xai import ChatXAI
from langchain_core.messages import SystemMessage, HumanMessage
from system_prompt import create_system_prompt

# 환경변수 설정
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')

# LLM 초기화
llm = ChatXAI(
    model_name="grok-4-fast-non-reasoning",
    xai_api_key=XAI_API_KEY,
    xai_api_base="https://api.x.ai/v1",
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """시작 명령어 처리"""
    await update.message.reply_text('Hi! I am a Grok-powered bot.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 메시지 처리"""
    user_message = update.message.text
    try:
        messages = [
            SystemMessage(content=create_system_prompt(is_mobile=True, is_subjective=False)),
            HumanMessage(content=user_message)
        ]
        response = llm.invoke(messages)
        await update.message.reply_text(response.content)
    except Exception as e:
        await update.message.reply_text(f'Sorry, something went wrong: {str(e)}')

# Application 인스턴스 생성 (webhook용)
application = Application.builder().token(BOT_TOKEN).build()

# 핸들러 등록
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

async def handler(request):
    """Vercel 서버리스 함수 핸들러"""
    if request.method == 'POST':
        try:
            # Telegram의 webhook 데이터를 JSON으로 파싱
            update_data = await request.json()
            update = Update.de_json(update_data, application.bot)

            # Update 처리
            await application.process_update(update)

            return {
                'statusCode': 200,
                'body': json.dumps({'status': 'ok'})
            }

        except Exception as e:
            print(f"Error processing update: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
    else:
        return {
            'statusCode': 405,
            'body': json.dumps({'error': 'Method not allowed'})
        }
