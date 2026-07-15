import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from app.database import db
from app.handlers import register_handlers
from app.config import BOT_TOKEN, PUBLIC_URL

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Настраиваем статику и админку
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# /static → папка app/static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# /admin → админка (импортируем после создания app чтобы избежать циклического импорта)
from app.web_admin import app as admin_app
app.mount("/admin", admin_app)

application: Application = None

async def _build_application() -> Application:
    """Создаёт Application и регистрирует хэндлеры"""
    logger.info("🔄 Building application...")
    
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Регистрация всех хэндлеров
    logger.info("🔄 Registering handlers...")
    register_handlers(app_)
    logger.info("✅ Handlers registered")
    
    # Установка вебхука
    if PUBLIC_URL:
        url = f"{PUBLIC_URL.rstrip('/')}/telegram"
        await app_.bot.set_webhook(url)
        logger.info(f"🌐 Webhook set to: {url}")
    else:
        logger.warning("⚠️ PUBLIC_URL is empty - using polling")
    
    logger.info("✅ Application built successfully")
    return app_
    
@app.on_event("startup")
async def on_startup():
    global application
    try:
        # Подключаем базу данных
        await db.connect()
        logger.info("✅ Database connected successfully")
        
        # Инициализация таблиц базы данных
        logger.info("🔄 Initializing database tables...")
        
        # Инициализация таблицы ролей (создание/апдейт 4 стандартных ролей и их прав)
        from app.services.role_service import RoleService
        await RoleService.initialize_roles()
        logger.info("✅ Roles table initialized")

        # Создание первого супер-админа при пустой таблице admin_users —
        # уже сделано внутри db.connect() -> Database.init_tables() выше,
        # с корректным поиском роли "Супер-администратор". Второй, ранее
        # дублирующий сценарий (AdminService.initialize_admin_user) убран:
        # он искал роль по несуществующему имени 'super_admin' и в редких
        # условиях создавал админа без роли вообще.

        # Создаем приложение (Main Bot)
        application = await _build_application()
        await application.initialize()
        await application.start()
        logger.info("✅ Bot started successfully")
        
        # Запуск Admin Bot (если сконфигурирован)
        from app.admin_bot import start_admin_bot, get_admin_bot_app
        await start_admin_bot()
        
        # Установка вебхука для Admin Bot
        admin_bot = get_admin_bot_app()
        if admin_bot and PUBLIC_URL:
            admin_url = f"{PUBLIC_URL.rstrip('/')}/telegram_admin"
            await admin_bot.bot.set_webhook(admin_url)
            logger.info(f"🌐 Admin Bot Webhook set to: {admin_url}")
        
        # Проверяем состояние бота
        bot_info = await application.bot.get_me()
        logger.info(f"🤖 Bot @{bot_info.username} is ready!")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    if application:
        await application.stop()
        await application.shutdown()
        
    # Остановка Admin Bot
    from app.admin_bot import stop_admin_bot
    await stop_admin_bot()
    
    logger.info("Bot stopped")

@app.post("/telegram")
async def telegram(request: Request):
    """Обработка входящих webhook запросов от Telegram (Основной бот)"""
    try:
        data = await request.json()
        # logger.info(f"📨 Received webhook update: {data}")
        
        update = Update.de_json(data, application.bot)
        
        # Обрабатываем апдейт
        await application.process_update(update)
        
    except Exception as e:
        logger.error(f"❌ Error processing update: {e}")
    
    return Response(status_code=200)

@app.post("/telegram_admin")
async def telegram_admin(request: Request):
    """Обработка входящих webhook запросов от Telegram (Админ бот)"""
    try:
        from app.admin_bot import get_admin_bot_app
        admin_bot = get_admin_bot_app()
        if not admin_bot:
            return Response(status_code=500)

        data = await request.json()
        # logger.info(f"📨 Received admin webhook update: {data}")
        
        update = Update.de_json(data, admin_bot.bot)
        
        # Обрабатываем апдейт
        await admin_bot.process_update(update)
        
    except Exception as e:
        logger.error(f"❌ Error processing admin update: {e}")
    
    return Response(status_code=200)

@app.get("/health")
async def health():
    return {"status": "ok", "database": "connected"}

# Лендинг (собранная Vite-статика) → "/".
# Это должно быть последним, что регистрируется в приложении: Starlette проверяет
# маршруты в порядке регистрации, и mount на "/" — это catch-all, который иначе
# перехватил бы /admin, /telegram, /telegram_admin, /health, /static.
STATIC_LANDING_DIR = os.path.join(BASE_DIR, "static_landing")
if os.path.isdir(STATIC_LANDING_DIR):
    app.mount("/", StaticFiles(directory=STATIC_LANDING_DIR, html=True), name="landing")
else:
    logger.warning(
        "app/static_landing не найдена — лендинг не смонтирован. "
        "Соберите его: `npm run build` в landing/ и скопируйте landing/dist сюда "
        "(в Docker-сборке это делается автоматически)."
    )

    @app.get("/")
    async def root_fallback():
        return {"status": "ok", "message": "SEABLUU service running (landing not built)"}

