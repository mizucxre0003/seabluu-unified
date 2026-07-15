import logging
import re
from datetime import datetime
from typing import List
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler

from app.config import ADMIN_BOT_TOKEN, BOT_TOKEN, CHANNEL_USERNAME, ADMIN_GROUP_ID
from app.services.order_service import OrderService, ParticipantService
from app.models import Order
from app.database import db

# Scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Regex patterns
PAYMENT_HEADER = "❄️ | PAYMENT SEABLUU"
ORDER_ID_REGEX = r"#([A-Z]+)\s*#(\d+)"  # #KR #1525
PARTICIPANT_REGEX = r"(@\w+)"

admin_bot_app: Application = None
scheduler = AsyncIOScheduler()

# Expose app for webhook
def get_admin_bot_app():
    return admin_bot_app

async def start_admin_bot():
    """Инициализация и запуск админ-бота"""
    global admin_bot_app
    if not ADMIN_BOT_TOKEN:
        logger.warning("ADMIN_BOT_TOKEN not set. Admin bot will not start.")
        return

    admin_bot_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()

    # Handlers
    # Channel post handler
    # Note: Bot must be admin in the channel to see messages, or use userbot. 
    # Validating "❄️ | PAYMENT SEABLUU" in text.
    # We must support both TEXT (text-only posts) and CAPTION (photo+text posts)
    admin_bot_app.add_handler(MessageHandler(filters.Chat(username=CHANNEL_USERNAME) & (filters.TEXT | filters.CAPTION), handle_channel_post))
    
    # Debug handler to see raw updates from the channel (optional, helps debugging)
    # admin_bot_app.add_handler(MessageHandler(filters.Chat(username=CHANNEL_USERNAME), log_channel_post), group=1)
    
    # Callback for "Create" button
    admin_bot_app.add_handler(CallbackQueryHandler(handle_create_order_callback, pattern=r"^create_order:"))

    # Initialize scheduler
    setup_scheduler()
    scheduler.start()

    await admin_bot_app.initialize()
    await admin_bot_app.start()
    
    # NO POLLING HERE - will use webhook in webhook.py
    logger.info("Admin Bot initialized (ready for webhook)")

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Парсинг поста из канала"""
    if not update.channel_post:
        return
        
    # Get text from message text or caption
    text = update.channel_post.text or update.channel_post.caption
    
    # Log raw text for debugging
    logger.info(f"Received channel post: {text[:20] if text else 'None'}")
    
    # Validating "PAYMENT SEABLUU" in text.
    # Header format: "[Emoji] | PAYMENT SEABLUU"
    # Example: "❄️ | PAYMENT SEABLUU" or "🌸 | PAYMENT SEABLUU"
    if not text or "PAYMENT SEABLUU" not in text:
        logger.info("Post ignored: Payment header not found")
        return

    logger.info(f"Processing new payment post: {text[:50]}...")

    # Extract Note (Emoji) from Header
    lines = text.split('\n')
    admin_note = ""
    for line in lines:
        if "PAYMENT SEABLUU" in line:
            parts = line.split("|")
            if len(parts) > 1:
                admin_note = parts[0].strip()
            break

    # Extract Order ID
    match = re.search(ORDER_ID_REGEX, text)
    if not match:
        logger.warning("Could not extract order ID from post")
        return
        
    # KR-1525
    order_id = f"{match.group(1)}-{match.group(2)}"
    
    # Extract participants
    # Find all lines with @
    participants = []
    for line in lines:
        if '@' in line:
            # Extract all usernames from line
            users = re.findall(PARTICIPANT_REGEX, line)
            participants.extend(users)
            
    # Remove duplicates
    participants = list(set(participants))
    
    # Filter ignored bots
    IGNORED_USERS = ['@seabluu_helper_bot', '@sbadmins_bot']
    # Also filter ignore bots without @ just in case regex captured differently, though regex has @.
    # Case insensitive check
    filtered_participants = []
    for p in participants:
        if p.lower() not in IGNORED_USERS:
            filtered_participants.append(p)
    participants = filtered_participants
    
    # Send to Admin Group
    if not ADMIN_GROUP_ID:
        logger.warning("ADMIN_GROUP_ID not set")
        return

    msg_text = (
        f"🆕 <b>Новый разбор для создания:</b>\n"
        f"🆔 ID: <code>{order_id}</code>\n"
        f"📝 Метка: {admin_note}\n"
        f"👥 Участники ({len(participants)}): {', '.join(participants)}\n"
        f"📊 Статус: 🛒 выкуплен"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Создать заказ", callback_data=f"create_order:{order_id}")]
    ])
    
    # Check bot_data size / cleanup old entries if needed?
    # For now simplicity.
    context.bot_data[f"pending_{order_id}"] = {
        "participants": participants,
        "note": admin_note,
        "text": text
    }

    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=msg_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def handle_create_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    # create_order:KR-1525
    order_id = data.split(":")[1]
    
    pending_data = context.bot_data.get(f"pending_{order_id}")
    if not pending_data:
        await query.edit_message_text(f"❌ Данные для заказа {order_id} не найдены (возможно, бот был перезагружен).")
        return
        
    participants = pending_data["participants"]
    admin_note = pending_data.get("note", "")
    
    # Process participants first to get client_name
    # Process participants first to get client_name
    IGNORED_USERS = ['seabluu_helper_bot', 'sbadmins_bot']
    clean_participants = [] # for DB storage (usually without @)
    display_participants = [] # for client_name (with @)

    for p in participants:
        # p has @ usually from regex
        clean = p.replace("@", "").lower()
        if clean not in IGNORED_USERS:
            clean_participants.append(clean)
            display_participants.append(p) # Keep original with @
            
    # Client name is list of users with @
    client_name_str = " ".join(display_participants)
    # Truncate if too long
    if len(client_name_str) > 250:
        client_name_str = client_name_str[:247] + "..."
    
    # Create Order using Service
    try:
        # Check if exists
        existing = await OrderService.get_order(order_id)
        if existing:
            await query.edit_message_text(f"⚠️ Заказ {order_id} уже существует!")
            return

        order = Order(
            order_id=order_id,
            client_name=client_name_str,
            status="🛒 выкуплен",
            country=order_id.split('-')[0], # KR or CN
            note=admin_note,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        await OrderService.add_order(order)
        
        await ParticipantService.ensure_participants(order_id, clean_participants)
        
        # Notify participants via MAIN bot
        # We need main bot instance.
        from telegram import Bot
        main_bot = Bot(token=BOT_TOKEN)
        
        notified_count = 0
        for username in clean_participants:
            # Need to find chat_id for username.
            # ParticipantService doesn't have chat_id, AddressService probably has user_id (chat_id) mapped to username?
            # Address model: user_id: int, username: str.
            # So if we have address, we have user_id (chat_id).
            
            # Need a method to get user_id by username
            # We can query addresses table.
            user_id = await get_user_id_by_username(username)
            if user_id:
                try:
                    # Create Subscribe Button
                    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                    sub_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔔 Подписаться на обновления", callback_data=f"sub:{order_id}")]
                    ])
                    
                    await main_bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Создан новый заказ {order_id}, где вы участник!",
                        reply_markup=sub_kb
                    )
                    notified_count += 1
                except Exception as e:
                    logger.error(f"Failed to send notification to {username}: {e}")
        
        await query.edit_message_text(
            f"✅ <b>Заказ {order_id} успешно создан!</b>\n"
            f"📝 Клиенты: {client_name_str}\n"
            f"🔔 Оповещено: {notified_count}",
            parse_mode="HTML"
        )
        
        # Clean up
        del context.bot_data[f"pending_{order_id}"]
        
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        await query.edit_message_text(f"❌ Ошибка при создании заказа: {e}")

async def get_user_id_by_username(username: str):
    """Helper to find user_id by username from addresses"""
    # Simple query
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM addresses WHERE username = $1", username)
        if row:
            return row['user_id']
    return None

def setup_scheduler():
    # Saturday 16:00
    scheduler.add_job(
        send_weekly_reminder,
        CronTrigger(day_of_week='sat', hour=16, minute=0),
        id='weekly_reminder',
        replace_existing=True
    )
    
    # Daily check (e.g. at 10:00)
    scheduler.add_job(
        check_stale_orders,
        CronTrigger(hour=10, minute=0),
        id='daily_check',
        replace_existing=True
    )

async def send_weekly_reminder():
    if not ADMIN_GROUP_ID or not admin_bot_app:
        return
        
    await admin_bot_app.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text="📅 <b>Напоминание</b>\nПроверьте и обновите статусы активных разборов.",
        parse_mode="HTML"
    )

async def check_stale_orders():
    if not ADMIN_GROUP_ID or not admin_bot_app:
        return
        
    # Find orders not "received" and updated > 14 days ago
    # SQL query
    import datetime
    two_weeks_ago = datetime.datetime.now() - datetime.timedelta(days=14)
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT order_id, status, updated_at 
            FROM orders 
            WHERE status != '✅ получен заказчиком' 
            AND updated_at < $1
        """, two_weeks_ago)
        
    if not rows:
        return
        
    msg = "⚠️ <b>Заказы без обновлений более 14 дней:</b>\n"
    for row in rows[:20]: # Limit to avoid spam
        msg += f"- {row['order_id']} ({row['status']})\n"
        
    if len(rows) > 20:
        msg += f"...и еще {len(rows)-20}"
        
    await admin_bot_app.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=msg,
        parse_mode="HTML"
    )

async def stop_admin_bot():
    if admin_bot_app:
        await admin_bot_app.stop()
        await admin_bot_app.shutdown()
    if scheduler.running:
        scheduler.shutdown()
