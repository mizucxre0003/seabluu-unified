import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from app.utils.helpers import reply_animated, reply_markdown_animated
from app.utils.keyboards import MAIN_KB, BACK_KB
from app.services.user_service import AddressService, SubscriptionService
from app.services.order_service import OrderService
from app.utils.validators import extract_order_id, normalize_phone, validate_postcode
from app.models import Address

logger = logging.getLogger(__name__)

# Текст кнопок для идентификации
CLIENT_ALIASES = {
    "track": {"🔍 отследить разбор", "отследить разбор"},
    "addrs": {"🏠 мой адрес", "мой адрес", "мои адреса"}, 
    "subs": {"🔔 мои подписки", "мои подписки"},
    "help": {"❓ помощь", "помощь"},
    "back": {"⬅️ назад", "назад", "back"},
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    hello = (
        "✨ Привет! Я *SEABLUU* Helper — помогу отследить разборы, адреса и подписки.\n\n"
        "*Что умею:*\n"
        "• 🔍 Отследить разбор — статус вашего заказа.\n"
        "Для того чтобы чтобы найти ваш разбор, используйте CN(кит разбор) и KR(кор разбор).\n"
        "Пример:\n"
        "CN-(номер вашего разбора)\n"
        "KR-(номер вашего разбора)\n\n"
        "Пишите только по 1 запросу!\n\n"
        "• 🔔 Подписки — уведомлю, когда статус заказа изменится.\n"
        "• 🏠 Мои адреса — сохраню/обновлю адрес для доставки.\n\n"
        "Если что-то пошло не так — нажми «Помощь»"
    )
    await reply_markdown_animated(update, context, hello, reply_markup=MAIN_KB)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    await reply_animated(
        update, context,
        "📘 Помощь:\n"
        "• 🔍 Отследить разбор — статус по номеру\n"
        "• 🏠 Мои адреса — добавить/изменить адрес\n"
        "• 🔔 Мои подписки — список подписок\n"
    )

async def admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о веб-админке"""
    message = (
        "🛠 *Веб-админка SEABLUU*\n\n"
        "Для управления заказами используйте веб-интерфейс:\n"
        "Там вы можете:\n"
        "• Добавлять и редактировать заказы\n"
        "• Управлять статусами\n"
        "• Просматривать участников\n"
        "• Делать массовые операции\n"
        "• Выгружать отчеты"
    )
    await reply_markdown_animated(update, context, message)

def _is_text(text: str, group: set[str]) -> bool:
    """Проверка соответствия текста группе алиасов"""
    return text.strip().lower() in {x.lower() for x in group}

async def handle_client_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений от пользователей"""
    user_id = update.effective_user.id
    raw_text = (update.message.text or "").strip()
    text = raw_text.lower()
    
    logger.info(f"👤 Клиентский обработчик: сообщение от {user_id}: {raw_text}")

    # Обработка кнопок
    if _is_text(text, CLIENT_ALIASES["help"]):
        await show_help_info(update, context)
        return

    if _is_text(text, CLIENT_ALIASES["back"]):
        context.user_data.clear()
        await reply_animated(update, context, "Вернулись в главное меню. Что дальше? 🙂", reply_markup=MAIN_KB)
        return
    
    if _is_text(text, CLIENT_ALIASES["track"]):
        context.user_data["mode"] = "track"
        await reply_animated(update, context, "🔎 Отправьте номер заказа (например: CN-12345):", reply_markup=BACK_KB)
        return

    if _is_text(text, CLIENT_ALIASES["addrs"]):
        context.user_data["mode"] = None
        await show_addresses(update, context)
        return

    if _is_text(text, CLIENT_ALIASES["subs"]):
        context.user_data["mode"] = None
        await show_subscriptions(update, context)
        return

    # Обработка режимов
    mode = context.user_data.get("mode")
    if mode == "track":
        await query_status(update, context, raw_text)
        return

    # Мастер добавления адреса
    if mode == "add_address_fullname":
        context.user_data["full_name"] = raw_text
        await reply_animated(update, context, "📞 Телефон (пример: 87001234567):", reply_markup=BACK_KB)
        context.user_data["mode"] = "add_address_phone"
        return

    if mode == "add_address_phone":
        normalized = normalize_phone(raw_text)
        if not normalized:
            await reply_animated(update, context, "Нужно 11 цифр и обязательно с 8. Пример: 87001234567\nВведи номер ещё раз или нажми «Назад».", reply_markup=BACK_KB)
            return
        context.user_data["phone"] = normalized
        await reply_animated(update, context, "🏙 Город (пример: Астана):", reply_markup=BACK_KB)
        context.user_data["mode"] = "add_address_city"
        return

    if mode == "add_address_city":
        context.user_data["city"] = raw_text
        await reply_animated(update, context, "🏠 Адрес (свободный формат):", reply_markup=BACK_KB)
        context.user_data["mode"] = "add_address_address"
        return

    if mode == "add_address_address":
        context.user_data["address"] = raw_text
        await reply_animated(update, context, "📮 Почтовый индекс (пример: 010000):", reply_markup=BACK_KB)
        context.user_data["mode"] = "add_address_postcode"
        return

    if mode == "add_address_postcode":
        if not validate_postcode(raw_text):
            await reply_animated(update, context, "Индекс выглядит странно. Пример: 010000\nВведи индекс ещё раз или нажми «Назад».", reply_markup=BACK_KB)
            return
        context.user_data["postcode"] = raw_text
        await save_address(update, context)
        return

    # Если ничего не подошло
    logger.info(f"❓ Клиентский обработчик: не распознано сообщение от {user_id}: {raw_text}")
    await reply_animated(
        update, context,
        "Хмм, не понял. Выберите кнопку ниже или введите номер заказа. Если что — «Помощь».",
        reply_markup=MAIN_KB,
    )

async def query_status(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    """Запрос статуса заказа"""
    order_id = extract_order_id(order_id) or order_id
    order = await OrderService.get_order(order_id)
    
    if not order:
        await reply_animated(update, context, "🙈 Такой заказ не найден. Проверьте номер или повторите позже.")
        return
    
    status = order.status or "статус не указан"
    origin = order.origin or ""
    txt = f"📦 Заказ *{order_id}*\nСтатус: *{status}*"
    if origin:
        txt += f"\nСтрана/источник: {origin}"

    # Проверка подписки
    is_subscribed = await SubscriptionService.is_subscribed(update.effective_user.id, order_id)
    if is_subscribed:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔕 Отписаться", callback_data=f"unsub:{order_id}")]])
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Подписаться на обновления", callback_data=f"sub:{order_id}")]])
    
    await reply_markdown_animated(update, context, txt, reply_markup=kb)
    context.user_data["mode"] = None

async def show_addresses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать адрес пользователя"""
    user_id = update.effective_user.id
    addrs = await AddressService.list_addresses(user_id)
    
    if not addrs:
        await reply_animated(
            update, context,
            "У вас пока нет адреса. Добавим?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить адрес", callback_data="addr:add")]]),
        )
        return
    
    lines = []
    for a in addrs:
        lines.append(f"• {a.full_name} — {a.phone}\n{a.city}, {a.address}, {a.postcode}")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить адрес", callback_data="addr:add")],
        [InlineKeyboardButton("🗑 Удалить адрес", callback_data="addr:del")],
    ])
    
    await reply_animated(update, context, "📍 Ваш адрес доставки:\n" + "\n\n".join(lines), reply_markup=kb)

async def save_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранить адрес пользователя"""
    u = update.effective_user
    
    address = Address(
        user_id=u.id,
        username=u.username or "",
        full_name=context.user_data.get("full_name", ""),
        phone=context.user_data.get("phone", ""),
        city=context.user_data.get("city", ""),
        address=context.user_data.get("address", ""),
        postcode=context.user_data.get("postcode", ""),
    )
    
    success = await AddressService.upsert_address(address)
    
    if success:
        context.user_data.clear()
        msg = (
            "✅ Адрес сохранён!\n\n"
            f"👤 ФИО: {address.full_name}\n"
            f"📞 Телефон: {address.phone}\n"
            f"🏙 Город: {address.city}\n"
            f"🏠 Адрес: {address.address}\n"
            f"📮 Индекс: {address.postcode}"
        )
        await reply_animated(update, context, msg, reply_markup=MAIN_KB)
    else:
        await reply_animated(update, context, "❌ Ошибка сохранения адреса. Попробуйте ещё раз.")

async def show_help_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать информацию помощи"""
    help_text = (
        "📘 *Помощь по боту SEABLUU Helper*\n\n"
        "*Основные функции:*\n"
        "• 🔍 *Отследить разбор* — проверяет статус заказа по номеру (например, CN-12345)\n"
        "• 🏠 *Мой адрес* — управление адресом доставки\n"
        "• 🔔 *Мои подписки* — список отслеживаемых заказов\n\n"
        "*Как использовать:*\n"
        "1. Нажмите кнопку 🔍 Отследить разбор\n"
        "2. Введите номер заказа\n"
        "3. Для подписки на обновления нажмите кнопку под статусом\n\n"
        "*Полезные ссылки:*\n"
        "• Телеграм-канал: @seabluushop\n"
        "• Техническая поддержка: @sb_bot_manager\n"
    )
    await reply_markdown_animated(update, context, help_text, reply_markup=MAIN_KB)

async def show_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать подписки пользователя"""
    user_id = update.effective_user.id
    subs = await SubscriptionService.list_subscriptions(user_id)
    
    if not subs:
        await reply_animated(update, context, "Пока нет подписок. Отследите заказ и нажмите «Подписаться».", reply_markup=MAIN_KB)
        return
    
    txt_lines = []
    kb_rows = []
    
    for s in subs:
        order_id = s.order_id
        # Получаем актуальный статус заказа из базы данных
        order = await OrderService.get_order(order_id)
        if order:
            current_status = order.status or "—"
        else:
            current_status = "—"
        
        txt_lines.append(f"• {order_id} — последний статус: {current_status}")
        kb_rows.append([InlineKeyboardButton(f"🗑 Отписаться от {order_id}", callback_data=f"unsub:{order_id}")])
    
    # Добавляем кнопку назад в главное меню
    kb_rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    
    await reply_animated(update, context, "🔔 Ваши подписки:\n" + "\n".join(txt_lines), 
                        reply_markup=InlineKeyboardMarkup(kb_rows))

def register(application):
    """Регистрация клиентских хэндлеров"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("admin", admin_info))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_client_text))
    logger.info("✅ Клиентские хэндлеры зарегистрированы")
