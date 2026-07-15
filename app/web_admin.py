import logging
import os
import uuid
from fastapi import UploadFile, File
from PIL import Image
from fastapi import FastAPI, Depends, HTTPException, Request, Form, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import ValidationError
import json
import io

from app.database import db
from app.services.order_service import OrderService, ParticipantService
from app.services.group_service import GroupService
from app.services.user_service import AddressService, SubscriptionService
from app.services.admin_service import AdminService
from app.services.admin_chat_service import AdminChatService
from app.services.role_service import RoleService
from app.models import Order, AdminUser, AdminUserCreate, AdminUserUpdate, AdminChatMessageCreate
from app.config import STATUSES
from app.utils.security import verify_password, create_access_token, verify_token, generate_avatar_url
from app.utils.session import get_current_admin
from app.utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)

app = FastAPI(title="SEABLUU Admin", docs_url=None, redoc_url=None)

# Определяем базовые пути для статики и шаблонов
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def serialize_model(model):
    """Сериализация Pydantic модели в словарь с обработкой разных версий Pydantic"""
    try:
        # Пробуем Pydantic v2
        return model.model_dump()
    except AttributeError:
        try:
            # Пробуем Pydantic v1
            return model.dict()
        except AttributeError:
            # Если не Pydantic модель, используем __dict__
            return model.__dict__

# Вспомогательная функция для проверки разрешений
def check_permission(current_admin: dict, required_permission: str):
    """Проверка разрешений пользователя"""
    from app.services.role_service import RoleService
    from app.utils.permissions import PermissionChecker
    
    # Дебаг логирование
    logger.info(f"Checking permission for user {current_admin.get('username')} with role '{current_admin.get('role')}'")
    logger.info(f"Required permission: {required_permission}")
    
    # Супер-админы имеют все права
    if current_admin.get("role") == PermissionChecker.SUPER_ADMIN_ROLE:
        logger.info("User is super admin - access granted")
        return True
    
    # Проверка разрешений
    user_permissions = current_admin.get("permissions", [])
    logger.info(f"User permissions: {user_permissions}")
    
    if RoleService.check_permission(user_permissions, required_permission):
        logger.info("Permission granted")
        return True
    
    logger.warning(f"Permission denied for {required_permission}")
    raise HTTPException(status_code=403, detail=f"Недостаточно прав: {required_permission}")

def check_super_admin(current_admin: dict):
    """Проверка что пользователь супер-админ"""
    from app.utils.permissions import PermissionChecker
    return current_admin.get("role") == PermissionChecker.SUPER_ADMIN_ROLE

# Страница входа
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request
    })

@app.post("/login")
async def login(request: Request, response: Response):
    """Аутентификация администратора"""
    try:
        form_data = await request.form()
        username = form_data.get("username")
        password = form_data.get("password")
        
        if not username or not password:
            raise HTTPException(400, "Необходимо указать имя пользователя и пароль")
        
        # Проверяем учетные данные
        admin_user = await AdminService.authenticate_user(username, password)
        if not admin_user:
            raise HTTPException(401, "Неверное имя пользователя или пароль")
        
        logger.info(f"Authenticated user: {admin_user.username}")

        # Получаем название роли из базы данных
        from app.services.role_service import RoleService
        from app.utils.permissions import PermissionChecker

        role_name = PermissionChecker.ADMIN_ROLE
        if admin_user.role_id:
            role = await RoleService.get_role_by_id(admin_user.role_id)
            if role:
                role_name = role.get('name', PermissionChecker.ADMIN_ROLE)
            else:
                logger.warning(f"Role with id {admin_user.role_id} not found for user {username}")
        else:
            logger.warning(f"User {username} has no role_id assigned")

        # Создаем токен с правильной ролью
        access_token = create_access_token(
            data={"sub": admin_user.username, "user_id": admin_user.id, "role": role_name}
        )
        
        # Устанавливаем cookie
        response = RedirectResponse(url="/admin/", status_code=302)
        from app.config import PUBLIC_URL
        response.set_cookie(
            key="admin_token",
            value=access_token,
            httponly=True,
            max_age=60 * 60 * 24 * 7,  # 7 дней
            secure=PUBLIC_URL.startswith("https"),  # Secure всегда на проде (Koyeb отдаёт HTTPS)
            samesite="lax"
        )
        
        # Обновляем время последнего входа
        await AdminService.update_last_login(admin_user.id)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.get("/logout")
async def logout(response: Response):
    """Выход из системы"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response

# Защищенные страницы
@app.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "dashboard",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("orders.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "orders",
        "statuses": STATUSES,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/orders/new", response_class=HTMLResponse)
async def new_order_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("order_form.html", {
        "request": request,
        "current_admin": current_admin,
        "statuses": STATUSES,
        "current_page": "orders",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/orders/{order_id}/edit", response_class=HTMLResponse)
async def edit_order_page(request: Request, order_id: str, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    order = await OrderService.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return templates.TemplateResponse("order_form.html", {
        "request": request,
        "current_admin": current_admin,
        "statuses": STATUSES,
        "current_page": "orders",
        "order": order,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/orders/{order_id}", response_class=HTMLResponse)
async def view_order_page(request: Request, order_id: str, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    order = await OrderService.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    participants = await ParticipantService.get_participants(order_id)
    
    return templates.TemplateResponse("order_view.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "orders",
        "order": order,
        "participants": participants,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/participants", response_class=HTMLResponse)
async def participants_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("participants.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "participants",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "reports",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("broadcast.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "broadcast",
        "statuses": STATUSES,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "settings",
        "statuses": STATUSES,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

# Новые страницы для управления администраторами
@app.get("/admin-users", response_class=HTMLResponse)
async def admin_users_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    # Проверяем права доступа
    check_permission(current_admin, "admin_users.view")
    
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "admin_users",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

# Страница управления ролями
@app.get("/roles", response_class=HTMLResponse)
async def roles_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    # Проверяем права доступа
    check_permission(current_admin, "roles.view")
    
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("roles.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "roles",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/admin-users/new", response_class=HTMLResponse)
async def new_admin_user_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    # Проверяем права доступа
    check_permission(current_admin, "admin_users.create")
    
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("admin_user_form.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "admin_users",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/admin-users/{user_id}/edit", response_class=HTMLResponse)
async def edit_admin_user_page(request: Request, user_id: int, current_admin: dict = Depends(get_current_admin)):
    # Проверяем права доступа
    check_permission(current_admin, "admin_users.edit")
    
    from app.utils.permissions import PermissionChecker
    user = await AdminService.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    
    return templates.TemplateResponse("admin_user_form.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "admin_users",
        "user": user,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/addresses", response_class=HTMLResponse)
async def addresses_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("addresses.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "addresses",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/admin-chat", response_class=HTMLResponse)
async def admin_chat_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("admin_chat.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "admin_chat",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "profile",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

# API endpoints для администраторов
@app.get("/api/admin/users")
async def get_admin_users(current_admin: dict = Depends(get_current_admin)):
    """Получение списка администраторов"""
    try:
        check_permission(current_admin, "admin_users.view")
        users = await AdminService.get_all_users()
        return {"users": users}
    except Exception as e:
        logger.error(f"Error fetching admin users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/admin/users")
async def create_admin_user(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Создание нового администратора"""
    try:
        check_permission(current_admin, "admin_users.create")
        data = await request.json()

        # Роль (в т.ч. супер-админа) может назначить только супер-админ.
        # У остальных, даже с правом admin_users.create, новый админ всегда
        # получает роль по умолчанию (см. AdminService.create_user).
        role_id = None
        if check_super_admin(current_admin):
            role_id = data.get('role_id')
            if role_id is None and data.get('role'):
                role = await RoleService.get_role_by_name(data['role'])
                if role:
                    role_id = role['id']

        # Собираем модель только из ожидаемых полей — формы на фронте иногда
        # присылают лишнее (id, is_active и т.п.), а модель это не разрешает.
        try:
            user_data = AdminUserCreate(
                username=data.get('username'),
                email=data.get('email'),
                password=data.get('password'),
                role_id=role_id,
            )
        except ValidationError as e:
            raise HTTPException(400, f"Некорректные данные: {e}")

        existing = await AdminService.get_user_by_username(user_data.username)
        if existing:
            raise HTTPException(400, "Пользователь с таким именем уже существует")

        user = await AdminService.create_user(user_data)
        return {"success": True, "user": user, "message": "Администратор создан"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating admin user: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.put("/api/admin/users/{user_id}")
async def update_admin_user(user_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    """Обновление администратора"""
    try:
        check_permission(current_admin, "admin_users.edit")
        data = await request.json()

        update_fields = {}
        if data.get('email') is not None:
            update_fields['email'] = data['email']
        if data.get('avatar_url') is not None:
            update_fields['avatar_url'] = data['avatar_url']
        if data.get('is_active') is not None:
            update_fields['is_active'] = data['is_active']
        # Пароль трогаем, только если реально прислали непустую строку —
        # иначе пустое поле в форме молча стирало бы текущий пароль.
        if data.get('password'):
            update_fields['password'] = data['password']

        # Роль другого пользователя (в т.ч. выдать/снять супер-админа) может
        # менять только супер-админ.
        if check_super_admin(current_admin):
            role_id = data.get('role_id')
            if role_id is None and data.get('role'):
                role = await RoleService.get_role_by_name(data['role'])
                if role:
                    role_id = role['id']
            if role_id is not None:
                update_fields['role_id'] = role_id

        try:
            user_data = AdminUserUpdate(**update_fields)
        except ValidationError as e:
            raise HTTPException(400, f"Некорректные данные: {e}")

        user = await AdminService.update_user(user_id, user_data)
        if not user:
            raise HTTPException(404, "Пользователь не найден")

        return {"success": True, "user": user, "message": "Администратор обновлен"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating admin user: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.delete("/api/admin/users/{user_id}")
async def delete_admin_user(user_id: int, current_admin: dict = Depends(get_current_admin)):
    """Удаление администратора"""
    try:
        check_permission(current_admin, "admin_users.delete")
        if user_id == current_admin["user_id"]:
            raise HTTPException(400, "Нельзя удалить самого себя")
        
        success = await AdminService.delete_user(user_id)
        if not success:
            raise HTTPException(404, "Пользователь не найден")
        
        return {"success": True, "message": "Администратор удален"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting admin user: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

# API для чата администраторов
@app.get("/api/admin/chat/messages")
async def get_chat_messages(current_admin: dict = Depends(get_current_admin)):
    """Получение сообщений чата"""
    try:
        messages = await AdminChatService.get_recent_messages(50)
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Error fetching chat messages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/admin/chat/messages")
async def create_chat_message(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Создание сообщения в чате"""
    try:
        data = await request.json()
        message_data = AdminChatMessageCreate(**data)
        
        message = await AdminChatService.create_message(
            current_admin["user_id"], 
            message_data.message
        )
        
        return {"success": True, "message": message}
        
    except Exception as e:
        logger.error(f"Error creating chat message: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

# API для профиля
@app.put("/api/admin/profile")
async def update_profile(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Обновление профиля текущего пользователя"""
    try:
        data = await request.json()
        
        # Преобразуем данные для обновления
        update_data = {}
        
        if "email" in data:
            update_data["email"] = data["email"]
        
        if "avatar_url" in data:
            update_data["avatar_url"] = data["avatar_url"]
        
        # Только супер-админ может менять роль
        if "role_id" in data and current_admin["role"] == "Супер-администратор":
            update_data["role_id"] = data["role_id"]
        
        user_data = AdminUserUpdate(**update_data)
        user = await AdminService.update_user(current_admin["user_id"], user_data)
        
        return {"success": True, "user": user, "message": "Профиль обновлен"}
        
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.put("/api/admin/profile/password")
async def change_password(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Смена пароля"""
    try:
        data = await request.json()
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        
        if not current_password or not new_password:
            raise HTTPException(400, "Необходимо указать текущий и новый пароль")
        
        success = await AdminService.change_password(
            current_admin["user_id"], 
            current_password, 
            new_password
        )
        
        if not success:
            raise HTTPException(400, "Неверный текущий пароль")
        
        return {"success": True, "message": "Пароль изменен"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

# API endpoints для управления ролями
@app.get("/api/roles")
async def get_roles(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Получить список всех ролей"""
    try:
        check_permission(current_admin, "roles.view")
        roles = await RoleService.get_all_roles()
        return {"roles": roles}
    except Exception as e:
        logger.error(f"Error fetching roles: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/roles/permissions")
async def get_permissions_list(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Получить список всех разрешений"""
    try:
        if not check_super_admin(current_admin):
            raise HTTPException(status_code=403, detail="Недостаточно прав: только супер-администратор")
        permissions = await RoleService.get_permissions_list()
        return {"permissions": permissions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching permissions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/roles")
async def create_role(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Создать новую роль"""
    try:
        check_permission(current_admin, "roles.create")
        data = await request.json()
        
        # Проверяем существование роли с таким именем
        existing = await RoleService.get_role_by_name(data['name'])
        if existing:
            raise HTTPException(400, "Роль с таким именем уже существует")
        
        role = await RoleService.create_role(
            name=data['name'],
            description=data.get('description'),
            permissions=data.get('permissions', []),
            is_default=data.get('is_default', False)
        )
        
        if not role:
            raise HTTPException(500, "Ошибка при создании роли")
        
        return {"success": True, "role": role, "message": "Роль создана"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating role: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.put("/api/roles/{role_id}")
async def update_role(role_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    """Обновление роли"""
    try:
        check_permission(current_admin, "roles.edit")
        data = await request.json()
        
        # Проверяем существование роли
        existing_role = await RoleService.get_role_by_id(role_id)
        if not existing_role:
            raise HTTPException(404, "Роль не найдена")
        
        # Если это стандартная роль, нельзя менять is_default
        if existing_role.get('is_default'):
            data['is_default'] = True
        
        role = await RoleService.update_role(
            role_id=role_id,
            name=data.get('name'),
            description=data.get('description'),
            permissions=data.get('permissions'),
            is_default=data.get('is_default')
        )
        
        if not role:
            raise HTTPException(500, "Ошибка при обновлении роли")
        
        return {"success": True, "role": role, "message": "Роль обновлена"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating role: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.delete("/api/roles/{role_id}")
async def delete_role(role_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    """Удаление роли"""
    try:
        check_permission(current_admin, "roles.delete")
        
        success = await RoleService.delete_role(role_id)
        if not success:
            raise HTTPException(400, "Нельзя удалить роль, которая используется администраторами")
        
        return {"success": True, "message": "Роль удалена"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting role: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.get("/api/stats")
async def get_stats(current_admin: dict = Depends(get_current_admin)):
    """Статистика для дашборда и шапки списка заказов"""
    final_status = STATUSES[-1]  # "✅ получен заказчиком"
    try:
        async with db.pool.acquire() as conn:
            total_orders = await conn.fetchval("SELECT COUNT(*) FROM orders") or 0

            completed_orders = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE status = $1", final_status
            ) or 0

            # "Требуют действий" — заказы, где есть хотя бы один неоплативший
            # участник. Реальная, уже существующая колонка (participants.paid),
            # никаких изменений в схеме БД для этого не нужно.
            needs_attention = await conn.fetchval(
                "SELECT COUNT(DISTINCT order_id) FROM participants WHERE paid = FALSE"
            ) or 0

            unique_participants = await conn.fetchval(
                "SELECT COUNT(DISTINCT username) FROM participants"
            ) or 0

            total_subscriptions = await conn.fetchval("SELECT COUNT(*) FROM subscriptions") or 0

        return {
            "total_orders": total_orders,
            "active_orders": max(total_orders - completed_orders, 0),
            "completed_orders": completed_orders,
            "needs_attention": needs_attention,
            "total_participants": unique_participants,
            "total_subscriptions": total_subscriptions
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return {
            "total_orders": 0,
            "active_orders": 0,
            "completed_orders": 0,
            "needs_attention": 0,
            "total_participants": 0,
            "total_subscriptions": 0
        }
        
# Middleware для проверки аутентификации
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Пропускаем страницу логина и статические файлы
    if request.url.path in ["/admin/login", "/admin/logout"] or request.url.path.startswith("/admin/static"):
        return await call_next(request)
    
    # Проверяем токен для защищенных страниц
    token = request.cookies.get("admin_token")
    if not token:
        return RedirectResponse(url="/admin/login")
    
    payload = verify_token(token)
    if not payload:
        response = RedirectResponse(url="/admin/login")
        response.delete_cookie("admin_token")
        return response
    
    response = await call_next(request)
    return response

# Существующие API endpoints с новой аутентификацией
@app.get("/api/orders")
async def get_orders(
    status: Optional[str] = None,
    country: Optional[str] = None,
    note: Optional[str] = None,
    search: Optional[str] = None,
    group_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_admin: dict = Depends(get_current_admin)):
    """API для получения списка заказов с пагинацией и фильтрацией по меткам"""
    try:
        # Получаем заказы с фильтрацией по меткам
        if note:
            orders = await OrderService.list_orders_by_note(note)
        elif status:
            orders = await OrderService.list_orders_by_status([status])
        else:
            # Получаем все заказы для правильного подсчета total
            orders = await OrderService.list_recent_orders(10000)
            
        # Фильтрация по группе
        if group_id:
            group_order_ids = await GroupService.get_group_order_ids(group_id)
            orders = [o for o in orders if o.order_id in group_order_ids]

        # Фильтрация по стране
        if country:
            orders = [o for o in orders if o.country == country.upper()]
        
        # Фильтрация по поиску
        if search:
            search_lower = search.lower()
            orders = [o for o in orders if 
                     search_lower in o.order_id.lower() or 
                     search_lower in o.client_name.lower() or
                     (o.note and search_lower in o.note.lower())]
        
        # Общее количество заказов (после фильтрации)
        total_orders = len(orders)
        
        # Пагинация
        paginated_orders = orders[offset:offset + limit]
        
        # Convert orders to dict for JSON serialization
        orders_data = []
        for order in paginated_orders:
            order_data = serialize_model(order)
            # Ensure datetime fields are serializable
            if order_data.get('created_at') and isinstance(order_data['created_at'], datetime):
                order_data['created_at'] = order_data['created_at'].isoformat()
            if order_data.get('updated_at') and isinstance(order_data['updated_at'], datetime):
                order_data['updated_at'] = order_data['updated_at'].isoformat()
            orders_data.append(order_data)
        
        return {
            "orders": orders_data,
            "total": total_orders,
            "has_more": total_orders > offset + limit,
            "offset": offset,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/orders/unique-notes")
async def get_unique_notes(current_admin: dict = Depends(get_current_admin)):
    """API для получения уникальных меток из заказов"""
    try:
        notes = await OrderService.get_unique_notes()
        return {"notes": notes}
    except Exception as e:
        logger.error(f"Error fetching unique notes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/orders/{order_id}")
async def get_order(order_id: str, current_admin: dict = Depends(get_current_admin)):
    """API для получения информации о заказе"""
    try:
        order = await OrderService.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        participants = await ParticipantService.get_participants(order_id)
        # Получаем подписки только для данного заказа и список username подписчиков
        subscriptions = await SubscriptionService.get_subscriptions_by_order(order_id)
        order_subs = subscriptions

        # Получаем username по user_id через AddressService
        try:
            all_addresses = await AddressService.get_all_addresses()
            user_map = {a.user_id: a.username for a in all_addresses}
            subscribers_usernames = [user_map.get(s.user_id) for s in order_subs if user_map.get(s.user_id)]
        except Exception:
            subscribers_usernames = []
        
        # Convert to dict for JSON serialization
        order_data = serialize_model(order)
        if order_data.get('created_at') and isinstance(order_data['created_at'], datetime):
            order_data['created_at'] = order_data['created_at'].isoformat()
        if order_data.get('updated_at') and isinstance(order_data['updated_at'], datetime):
            order_data['updated_at'] = order_data['updated_at'].isoformat()
        
        participants_data = []
        for participant in participants:
            participant_data = serialize_model(participant)
            if participant_data.get('created_at') and isinstance(participant_data['created_at'], datetime):
                participant_data['created_at'] = participant_data['created_at'].isoformat()
            if participant_data.get('updated_at') and isinstance(participant_data['updated_at'], datetime):
                participant_data['updated_at'] = participant_data['updated_at'].isoformat()
            participants_data.append(participant_data)
        
        return {
            "order": order_data,
            "participants": participants_data,
            "subscribers": len(order_subs),
            "subscribers_list": subscribers_usernames
        }
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/orders/create")
async def create_order_api(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Создание нового заказа"""
    try:
        data = await request.json()
        
        # Проверяем существование заказа
        existing = await OrderService.get_order(data['order_id'])
        if existing:
            raise HTTPException(400, "Заказ с таким ID уже существует")
        
        order = Order(
            order_id=data['order_id'],
            client_name=data['client_name'],
            country=data['country'].upper(),
            status=data['status'],
            note=data.get('note', '')
        )
        
        success = await OrderService.add_order(order)
        if not success:
            raise HTTPException(500, "Ошибка при создании заказа")
        
        # Добавляем участников
        from app.utils.validators import extract_usernames
        usernames = extract_usernames(data['client_name'])
        if usernames:
            await ParticipantService.ensure_participants(data['order_id'], usernames)
        
        # Отправляем уведомление клиенту
        await send_order_created_notification(order, usernames)
        
        return {"success": True, "message": "Заказ успешно создан"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.put("/api/orders/{order_id}")
async def update_order_api(
    order_id: str,
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Обновление заказа"""
    try:
        order = await OrderService.get_order(order_id)
        if not order:
            return JSONResponse(status_code=404, content={"success": False, "detail": "Заказ не найден"})

        data = await request.json()

        # Валидация входных данных от администратора
        errors = {}
        update_data = {}

        # Проверка возможного изменения order_id
        if 'order_id' in data:
            new_order_id = (data.get('order_id') or '').strip()
            if not new_order_id:
                errors['order_id'] = 'Order ID не может быть пустым'
            else:
                # Проверяем, не создаст ли это конфликт
                existing = await OrderService.get_order(new_order_id)
                if existing and new_order_id != order.order_id:
                    errors['order_id'] = 'Заказ с таким Order ID уже существует'
                else:
                    update_data['order_id'] = new_order_id

        if 'client_name' in data:
            client_name = (data.get('client_name') or '').strip()
            if not client_name:
                errors['client_name'] = 'Имя клиента не может быть пустым'
            else:
                update_data['client_name'] = client_name

        if 'country' in data:
            country = (data.get('country') or '').strip().upper()
            if not country or not country.isalpha() or len(country) not in (2, 3):
                errors['country'] = 'Неверный код страны (например: CN, KR, JP)'
            else:
                update_data['country'] = country

        if 'status' in data:
            status = data.get('status')
            from app.config import STATUSES as VALID_STATUSES
            if status not in VALID_STATUSES:
                errors['status'] = 'Неверный статус заказа'
            else:
                update_data['status'] = status

        if 'note' in data:
            note = (data.get('note') or '').strip()
            if len(note) > 1000:
                errors['note'] = 'Метка слишком длинная (макс. 1000 символов)'
            else:
                update_data['note'] = note

        if errors:
            return JSONResponse(status_code=400, content={"success": False, "errors": errors})

        if update_data:
            success = await OrderService.update_order(order_id, update_data)
            if not success:
                return JSONResponse(status_code=500, content={"success": False, "detail": "Ошибка при обновлении заказа"})

            # Если при обновлении поменялось поле client_name — уведомляем только добавленных пользователей
            try:
                from app.utils.validators import extract_usernames

                new_client_name = update_data.get('client_name')
                # определяем реальный order_id после возможного переименования
                current_order_id = update_data.get('order_id', order_id)

                if new_client_name:
                    new_usernames = extract_usernames(new_client_name) or []
                    if new_usernames:
                        # текущие участники (после обновления лучше взять актуальные данные)
                        try:
                            existing_participants = await ParticipantService.get_participants(current_order_id)
                            existing_usernames = [p.username for p in existing_participants]
                        except Exception:
                            existing_usernames = []

                        # только добавленные пользователи
                        added_usernames = [u for u in new_usernames if u not in existing_usernames]
                        if added_usernames:
                            # Регистрируем новых участников и отправляем им уведомления
                            try:
                                await ParticipantService.ensure_participants(current_order_id, added_usernames)
                            except Exception as e:
                                logger.error(f"Error ensuring participants for {current_order_id}: {e}")

                            try:
                                updated_order = await OrderService.get_order(current_order_id)
                                if updated_order:
                                    await send_order_created_notification(updated_order, added_usernames)
                            except Exception as e:
                                logger.error(f"Error sending notifications to added participants for {current_order_id}: {e}")
            except Exception as e:
                logger.error(f"Post-update participant notification error for {order_id}: {e}")

        return {"success": True, "message": "Заказ обновлен"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.delete("/api/orders/{order_id}")
async def delete_order_api(
    order_id: str,
    current_admin: dict = Depends(get_current_admin)):
    """Удаление заказа"""
    try:
        # Проверяем существование заказа
        order = await OrderService.get_order(order_id)
        if not order:
            raise HTTPException(404, "Заказ не найден")
        
        success = await OrderService.delete_order(order_id)
        if not success:
            raise HTTPException(500, "Ошибка при удалении заказа")
        
        return {"success": True, "message": "Заказ удален"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting order: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.get("/api/participants")
async def get_participants(
    order_id: Optional[str] = None,
    paid: Optional[bool] = None,
    search: Optional[str] = None,
    group_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_admin: dict = Depends(get_current_admin)):
    """API для получения списка участников с оптимизированной пагинацией"""
    try:
        order_ids = None
        if group_id:
            order_ids = await GroupService.get_group_order_ids(group_id)

        # Используем новый метод для получения участников с пагинацией на уровне БД
        result = await ParticipantService.get_participants_paginated(
            order_id=order_id,
            paid=paid,
            search=search,
            order_ids=order_ids,
            limit=limit,
            offset=offset
        )
        
        # Convert to dict for JSON serialization
        participants_data = []
        for participant in result["participants"]:
            participant_data = serialize_model(participant)
            if participant_data.get('created_at') and isinstance(participant_data['created_at'], datetime):
                participant_data['created_at'] = participant_data['created_at'].isoformat()
            if participant_data.get('updated_at') and isinstance(participant_data['updated_at'], datetime):
                participant_data['updated_at'] = participant_data['updated_at'].isoformat()
            participants_data.append(participant_data)
        
        return {
            "participants": participants_data,
            "total": result["total"],
            "has_more": result["has_more"],
            "offset": offset,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error fetching participants: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/participants/{order_id}/{username}/paid")
async def update_participant_paid(
    order_id: str,
    username: str,
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Изменение статуса оплаты участника"""
    try:
        # Используем toggle метод вместо получения данных из тела
        success = await ParticipantService.toggle_participant_paid(order_id, username)
        if not success:
            raise HTTPException(400, "Не удалось обновить статус оплаты")
        
        return {"success": True, "message": "Статус оплаты обновлен"}
        
    except Exception as e:
        logger.error(f"Error updating participant payment: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.post("/api/broadcast/unpaid")
async def broadcast_unpaid(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Рассылка уведомлений неплательщикам"""
    try:
        # Проверяем, что тело запроса не пустое
        body = await request.body()
        if not body:
            raise HTTPException(400, "Empty request body")
        
        try:
            data = await request.json()
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            raise HTTPException(400, "Invalid JSON format")
            
        message = data.get('message', '')
        
        if not message:
            raise HTTPException(400, "Сообщение не может быть пустым")
        
        # Получаем всех неплательщиков
        from app.services.order_service import ParticipantService
        unpaid_grouped = await ParticipantService.get_all_unpaid_grouped()
        
        if not unpaid_grouped:
            return {
                "success": True, 
                "message": "Нет неплательщиков для рассылки",
                "result": {
                    "sent": 0,
                    "failed": 0, 
                    "total": 0
                }
            }
        
        # Собираем все username
        all_usernames = []
        for usernames in unpaid_grouped.values():
            all_usernames.extend(usernames)
        
        # Получаем user_id по username
        user_ids = []
        for username in all_usernames:
            address = await AddressService.get_address_by_username(username)
            if address:
                user_ids.append(address.user_id)
        
        sent_count = 0
        failed_count = 0
        
        # Отправляем сообщения через Telegram бота
        from app.webhook import application
        if application and application.bot:
            for user_id in user_ids:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")
                    failed_count += 1
        
        return {
            "success": True,
            "message": "Рассылка завершена",
            "result": {
                "sent": sent_count,
                "failed": failed_count,
                "total": len(user_ids)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error broadcasting to unpaid: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.post("/api/broadcast/reminder")
async def send_reminder(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Отправка напоминания конкретному пользователю"""
    try:
        data = await request.json()
        message = data.get('message', '')
        usernames = data.get('usernames', [])
        
        if not message or not usernames:
            raise HTTPException(400, "Сообщение и список пользователей обязательны")
        
        # Получаем user_id по username
        user_ids = []
        for username in usernames:
            address = await AddressService.get_address_by_username(username)
            if address:
                user_ids.append(address.user_id)
        
        if not user_ids:
            return {
                "success": False,
                "message": "Пользователи не найдены"
            }
        
        sent_count = 0
        failed_count = 0
        
        # Отправляем сообщения через Telegram бота
        from app.webhook import application
        if application and application.bot:
            for user_id in user_ids:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending reminder to {user_id}: {e}")
                    failed_count += 1
        
        return {
            "success": True,
            "message": f"Напоминания отправлены ({sent_count}/{len(user_ids)})",
            "result": {
                "sent": sent_count,
                "failed": failed_count,
                "total": len(user_ids)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending reminders: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.post("/api/broadcast/all")
async def broadcast_all(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Рассылка сообщения всем пользователям"""
    try:
        body = await request.body()
        if not body:
            raise HTTPException(400, "Empty request body")
        
        try:
            data = await request.json()
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            raise HTTPException(400, "Invalid JSON format")
            
        message = data.get('message', '')
        
        if not message:
            raise HTTPException(400, "Сообщение не может быть пустым")
        
        # Получаем всех пользователей с адресами
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT user_id FROM addresses")
            user_ids = [row['user_id'] for row in rows]
        
        sent_count = 0
        failed_count = 0
        
        # Отправляем сообщения через Telegram бота
        for user_id in user_ids:
            try:
                from app.webhook import application
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML'
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                failed_count += 1
        
        return {
            "success": True, 
            "message": "Рассылка завершена",
            "result": {
                "sent": sent_count,
                "failed": failed_count,
                "total": len(user_ids)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error broadcasting to all users: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.get("/api/statuses")
async def get_statuses(current_admin: dict = Depends(get_current_admin)):
    """API для получения списка статусов"""
    return {"statuses": STATUSES}

@app.get("/api/telegram/posts")
async def get_telegram_posts(
    limit: int = Query(5, ge=1, le=10),
    current_admin: dict = Depends(get_current_admin)):
    """API для получения постов из Telegram канала"""
    try:
        from app.services.telegram_service import telegram_service
        posts = await telegram_service.get_channel_posts(limit)
        return {"posts": posts}
    except Exception as e:
        logger.error(f"Error fetching Telegram posts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/import")
async def import_orders_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    """Страница импорта заказов"""
    return templates.TemplateResponse("import_orders.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "orders",
        "statuses": STATUSES
    })

@app.post("/api/orders/bulk")
async def bulk_create_orders(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Массовое создание заказов"""
    try:
        data = await request.json()
        orders_data = data.get('orders', [])
        
        if not orders_data:
            raise HTTPException(400, "Нет данных для импорта")
        
        results = {
            "total": len(orders_data),
            "success": 0,
            "errors": 0,
            "duplicates": 0,
            "errorList": []
        }
        
        for order_data in orders_data:
            try:
                # Проверяем существование заказа
                existing = await OrderService.get_order(order_data['order_id'])
                if existing:
                    results["duplicates"] += 1
                    results["errorList"].append({
                        "order_id": order_data['order_id'],
                        "message": "Заказ уже существует"
                    })
                    continue
                
                # Создаем заказ
                order = Order(
                    order_id=order_data['order_id'],
                    client_name=order_data['client_name'],
                    country=order_data.get('country', 'RU').upper(),
                    status=order_data.get('status', 'В обработке'),
                    note=order_data.get('note', '')
                )
                
                success = await OrderService.add_order(order)
                if success:
                    # Добавляем участников
                    from app.utils.validators import extract_usernames
                    usernames = extract_usernames(order_data['client_name'])
                    if usernames:
                        await ParticipantService.ensure_participants(order_data['order_id'], usernames)
                    
                    # Отправляем уведомление клиенту
                    await send_order_created_notification(order, usernames)
                    
                    results["success"] += 1
                else:
                    raise Exception("Ошибка при создании заказа")
                    
            except Exception as e:
                results["errors"] += 1
                results["errorList"].append({
                    "order_id": order_data.get('order_id', 'Unknown'),
                    "message": str(e)
                })
        
        return results
        
    except Exception as e:
        logger.error(f"Error in bulk order creation: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.post("/api/orders/parse-excel")
async def parse_excel_file(
    file: UploadFile = File(...),
    current_admin: dict = Depends(get_current_admin)):
    """Парсинг Excel файла с заказами"""
    try:
        # Проверяем расширение файла
        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            raise HTTPException(400, "Формат файла не поддерживается. Используйте .xlsx или .xls")
        
        # Читаем файл
        contents = await file.read()
        
        # Парсим Excel
        import pandas as pd
        df = pd.read_excel(io.BytesIO(contents))
        
        # Логируем заголовки столбцов для отладки
        logger.info(f"Excel columns: {list(df.columns)}")
        
        # Преобразуем в JSON
        orders = []
        for index, row in df.iterrows():
            # Пробуем разные варианты названий столбцов
            order_number = str(row.get('order_number', row.get('order_id', ''))).strip()
            client_name = str(row.get('client_name', row.get('client', ''))).strip()
            country = str(row.get('country', 'CN')).strip().upper()
            status = str(row.get('status', 'В обработке')).strip()
            note = str(row.get('note', '')).strip()
            
            # Если номер заказа пустой, пропускаем
            if not order_number:
                continue
                
            # Формируем полный ID заказа
            if country == 'CN':
                order_id = f"CN-{order_number}"
            elif country == 'KR':
                order_id = f"KR-{order_number}"
            else:
                order_id = f"{country}-{order_number}"
            
            # Проверяем обязательные поля
            if order_number and client_name:
                order_data = {
                    "order_id": order_id,
                    "client_name": client_name,
                    "country": country,
                    "status": status,
                    "note": note
                }
                orders.append(order_data)
                logger.info(f"Parsed order {index}: {order_data}")
        
        logger.info(f"Successfully parsed {len(orders)} orders from Excel file")
        
        return {
            "success": True,
            "orders": orders,
            "total": len(orders)
        }
        
    except Exception as e:
        logger.error(f"Error parsing Excel file: {e}")
        raise HTTPException(500, f"Ошибка при обработке файла: {str(e)}")

async def send_order_created_notification(order, usernames):
    """Отправка уведомления о создании заказа"""
    try:
        logger.info(f"Sending order notification for order {order.order_id} to usernames: {usernames}")
        
        if not usernames:
            logger.info("No usernames to notify")
            return
        
        # Получаем user_id по username
        user_ids = await AddressService.get_user_ids_by_usernames(usernames)
        logger.info(f"Found user IDs: {user_ids} for usernames: {usernames}")
        
        message = f"""
📦 <b>Новый заказ создан!</b>

🆔 <b>Order ID:</b> {order.order_id}
👤 <b>Клиент:</b> {order.client_name}
🌍 <b>Страна:</b> {order.country}
📊 <b>Статус:</b> {order.status}

Следите за обновлениями статуса заказа!
"""
        
        # Создаем инлайн-клавиатуру с кнопкой подписки
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Подписаться на обновления", callback_data=f"sub:{order.order_id}")]
        ])
        
        # Отправляем сообщения через Telegram бота
        for user_id in user_ids:
            try:
                from app.webhook import application
                logger.info(f"Sending notification to user {user_id}")
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                logger.info(f"Notification sent successfully to user {user_id}")
            except Exception as e:
                logger.error(f"Error sending order notification to {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error in send_order_created_notification: {e}")

# Добавляем новые API endpoints для массовых операций
@app.post("/api/orders/bulk-update-status")
async def bulk_update_status(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Массовое обновление статусов заказов"""
    try:
        data = await request.json()
        order_ids = data.get('order_ids', [])
        status = data.get('status')
        
        if not order_ids or not status:
            raise HTTPException(400, "Необходимо указать список заказов и статус")
        
        updated_count = 0
        error_count = 0
        
        for order_id in order_ids:
            try:
                success = await OrderService.update_order(order_id, {"status": status})
                if success:
                    updated_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Error updating order {order_id}: {e}")
                error_count += 1
        
        return {
            "success": True,
            "message": f"Обновлено {updated_count} из {len(order_ids)} заказов",
            "updated": updated_count,
            "errors": error_count
        }
        
    except Exception as e:
        logger.error(f"Error in bulk update status: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

@app.post("/api/orders/bulk-delete")
async def bulk_delete_orders(
    request: Request,
    current_admin: dict = Depends(get_current_admin)):
    """Массовое удаление заказов"""
    try:
        data = await request.json()
        order_ids = data.get('order_ids', [])
        
        if not order_ids:
            raise HTTPException(400, "Необходимо указать список заказов")
        
        deleted_count = 0
        error_count = 0
        
        for order_id in order_ids:
            try:
                success = await OrderService.delete_order(order_id)
                if success:
                    deleted_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Error deleting order {order_id}: {e}")
                error_count += 1
        
        return {
            "success": True,
            "message": f"Удалено {deleted_count} из {len(order_ids)} заказов",
            "deleted": deleted_count,
            "errors": error_count
        }
        
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}")
        raise HTTPException(500, "Внутренняя ошибка сервера")

# Новые API endpoints для адресов и отчетов
@app.get("/api/addresses")
async def get_addresses(
    search_name: Optional[str] = None,
    search_username: Optional[str] = None,
    city: Optional[str] = None,
    current_admin: dict = Depends(get_current_admin)
):
    """API для получения списка адресов"""
    try:
        addresses = await AddressService.get_all_addresses()
        
        # Фильтрация по имени
        if search_name:
            addresses = [a for a in addresses if search_name.lower() in a.get('full_name', '').lower()]
        
        # Фильтрация по username
        if search_username:
            addresses = [a for a in addresses if search_username.lower() in a.get('username', '').lower()]
        
        # Фильтрация по городу
        if city:
            addresses = [a for a in addresses if a.get('city') == city]
        
        return {"addresses": addresses}
    except Exception as e:
        logger.error(f"Error fetching addresses: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/addresses/export/xlsx")
async def export_addresses_xlsx(current_admin: dict = Depends(get_current_admin)):
    """Экспорт адресов в XLSX"""
    try:
        addresses = await AddressService.get_all_addresses()
        
        # Преобразуем объекты Address в словари
        addresses_data = []
        for address in addresses:
            address_dict = {
                'user_id': address.user_id,
                'username': address.username,
                'full_name': address.full_name,
                'phone': address.phone,
                'city': address.city,
                'address': address.address,
                'postcode': address.postcode,
                'created_at': address.created_at.isoformat() if address.created_at else '',
                'updated_at': address.updated_at.isoformat() if address.updated_at else ''
            }
            addresses_data.append(address_dict)
        
        # Создаем DataFrame
        import pandas as pd
        df = pd.DataFrame(addresses_data)
        
        # Создаем Excel файл
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Addresses', index=False)
        
        output.seek(0)
        
        # Возвращаем файл
        filename = f"addresses_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error exporting addresses: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/reports/analytics")
async def get_reports_analytics(current_admin: dict = Depends(get_current_admin)):
    """API для получения аналитики отчетов"""
    try:
        # Получаем все заказы
        orders = await OrderService.list_recent_orders(10000)
        
        # Базовая статистика
        total_orders = len(orders)
        completed_orders = len([o for o in orders if "доставлен" in o.status.lower() or "получен" in o.status.lower()])
        
        # Статистика по статусам
        status_stats = {}
        for order in orders:
            status = order.status
            status_stats[status] = status_stats.get(status, 0) + 1
        
        # Статистика по странам
        country_stats = {}
        for order in orders:
            country = order.country
            country_stats[country] = country_stats.get(country, 0) + 1
        
        # Статистика платежей
        all_participants = []
        for order in orders:
            participants = await ParticipantService.get_participants(order.order_id)
            all_participants.extend(participants)
        
        paid_participants = [p for p in all_participants if p.paid]
        unpaid_participants = [p for p in all_participants if not p.paid]
        
        return {
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "unique_participants": len(set(p.username for p in all_participants)),
            "status_stats": status_stats,
            "country_stats": country_stats,
            "payment_stats": {
                "total": len(all_participants),
                "paid": len(paid_participants),
                "unpaid": len(unpaid_participants)
            }
        }
    except Exception as e:
        logger.error(f"Error fetching reports analytics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/reports/export/{report_type}")
async def export_report(
    report_type: str,
    current_admin: dict = Depends(get_current_admin)):
    """Экспорт отчетов в XLSX"""
    try:
        if report_type == "orders":
            orders = await OrderService.list_recent_orders(10000)
            
            # Преобразуем объекты Order в словари
            orders_data = []
            for order in orders:
                order_dict = {
                    'order_id': order.order_id,
                    'client_name': order.client_name,
                    'country': order.country,
                    'status': order.status,
                    'note': order.note or '',
                    'created_at': order.created_at.isoformat() if order.created_at else '',
                    'updated_at': order.updated_at.isoformat() if order.updated_at else ''
                }
                orders_data.append(order_dict)
            
            # Создаем DataFrame
            import pandas as pd
            df = pd.DataFrame(orders_data)
            
            # Создаем Excel файл
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Orders', index=False)
            
            output.seek(0)
            
            # Возвращаем файл
            filename = f"orders_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
            return Response(
                content=output.getvalue(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        elif report_type == "participants":
            # Получаем всех участников
            result = await ParticipantService.get_participants_paginated(limit=10000)
            participants = result["participants"]
            
            # Преобразуем объекты Participant в словари
            participants_data = []
            for participant in participants:
                participant_dict = {
                    'order_id': participant.order_id,
                    'username': participant.username,
                    'paid': "Да" if participant.paid else "Нет",
                    'created_at': participant.created_at.isoformat() if participant.created_at else '',
                    'updated_at': participant.updated_at.isoformat() if participant.updated_at else ''
                }
                participants_data.append(participant_dict)
            
            # Создаем DataFrame
            import pandas as pd
            df = pd.DataFrame(participants_data)
            
            # Создаем Excel файл
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Participants', index=False)
            
            output.seek(0)
            
            # Возвращаем файл
            filename = f"participants_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
            return Response(
                content=output.getvalue(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        elif report_type == "full":
            # Получаем все данные
            orders = await OrderService.list_recent_orders(10000)
            all_participants = []
            
            for order in orders:
                participants = await ParticipantService.get_participants(order.order_id)
                all_participants.extend(participants)
            
            # Преобразуем в словари
            orders_data = []
            for order in orders:
                order_dict = {
                    'order_id': order.order_id,
                    'client_name': order.client_name,
                    'country': order.country,
                    'status': order.status,
                    'note': order.note or '',
                    'created_at': order.created_at.isoformat() if order.created_at else '',
                    'updated_at': order.updated_at.isoformat() if order.updated_at else ''
                }
                orders_data.append(order_dict)
            
            participants_data = []
            for participant in all_participants:
                participant_dict = {
                    'order_id': participant.order_id,
                    'username': participant.username,
                    'paid': "Да" if participant.paid else "Нет",
                    'created_at': participant.created_at.isoformat() if participant.created_at else '',
                    'updated_at': participant.updated_at.isoformat() if participant.updated_at else ''
                }
                participants_data.append(participant_dict)
            
            # Создаем Excel файл с двумя листами
            import pandas as pd
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                pd.DataFrame(orders_data).to_excel(writer, sheet_name='Orders', index=False)
                pd.DataFrame(participants_data).to_excel(writer, sheet_name='Participants', index=False)
            
            output.seek(0)
            
            # Возвращаем файл
            filename = f"full_report_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
            return Response(
                content=output.getvalue(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        
        raise HTTPException(400, "Неверный тип отчета")
        
    except Exception as e:
        logger.error(f"Error exporting report {report_type}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# API для запуска миграции
@app.post("/api/admin/migrate")
async def run_migration(current_admin: dict = Depends(get_current_admin)):
    """Запуск миграции системы ролей"""
    try:
        # Только супер-администратор
        if current_admin.get("role") != "Супер-администратор" and current_admin.get("role_name") != "Супер-администратор":
            raise HTTPException(status_code=403, detail="Super admin access required")
        
        # Запускаем миграцию в фоновом режиме
        import subprocess
        import sys
        
        result = subprocess.run([
            sys.executable, "migrate_roles_fixed.py"
        ], capture_output=True, text=True, cwd=".")
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
        
    except Exception as e:
        logger.error(f"Error running migration: {e}")
        raise HTTPException(500, "Ошибка при запуске миграции")

@app.post("/api/admin/simple-setup")
async def simple_setup():
    """Простая ручная настройка системы ролей"""
    try:
        # Запускаем простую настройку
        import subprocess
        import sys
        
        result = subprocess.run([
            sys.executable, "simple_setup.py"
        ], capture_output=True, text=True, cwd=".")
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
        
    except Exception as e:
        logger.error(f"Error running simple setup: {e}")
        raise HTTPException(500, "Ошибка при настройке системы")

# --- Groups Management ---

@app.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request, current_admin: dict = Depends(get_current_admin)):
    check_permission(current_admin, "orders.view") 
    from app.utils.permissions import PermissionChecker
    return templates.TemplateResponse("groups.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "groups",
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

from fastapi.encoders import jsonable_encoder

@app.get("/groups/{group_id}", response_class=HTMLResponse)
async def group_edit_page(request: Request, group_id: int, current_admin: dict = Depends(get_current_admin)):
    check_permission(current_admin, "orders.edit")
    from app.utils.permissions import PermissionChecker
    
    group = await GroupService.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
        
    return templates.TemplateResponse("group_edit.html", {
        "request": request,
        "current_admin": current_admin,
        "current_page": "groups",
        "group": jsonable_encoder(group),
        "statuses": STATUSES,
        "super_admin_role": PermissionChecker.SUPER_ADMIN_ROLE
    })

@app.get("/api/groups")
async def get_groups(current_admin: dict = Depends(get_current_admin)):
    try:
        groups = await GroupService.list_groups()
        return {"groups": [serialize_model(g) for g in groups]}
    except Exception as e:
        logger.error(f"Error fetching groups: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/groups")
async def create_group_api(request: Request, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.create")
        data = await request.json()
        group = await GroupService.create_group(data['name'])
        return {"success": True, "group": serialize_model(group)}
    except Exception as e:
        logger.error(f"Error creating group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/groups/{group_id}")
async def update_group_api(group_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.edit")
        data = await request.json()
        group = await GroupService.update_group(group_id, data['name'])
        return {"success": True, "group": serialize_model(group)}
    except Exception as e:
        logger.error(f"Error updating group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/api/groups/{group_id}")
async def delete_group_api(group_id: int, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.delete")
        await GroupService.delete_group(group_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Error deleting group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/groups/{group_id}/orders")
async def get_group_orders_api(group_id: int, current_admin: dict = Depends(get_current_admin)):
    try:
        orders = await GroupService.get_group_orders(group_id)
        # Serialize orders
        orders_data = []
        for order in orders:
            d = serialize_model(order)
            # Handle dates
            if d.get('created_at') and isinstance(d['created_at'], datetime):
                d['created_at'] = d['created_at'].isoformat()
            if d.get('updated_at') and isinstance(d['updated_at'], datetime):
                d['updated_at'] = d['updated_at'].isoformat()
            orders_data.append(d)
        return {"orders": orders_data}
    except Exception as e:
        logger.error(f"Error fetching group orders: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/groups/{group_id}/orders")
async def add_group_orders_api(group_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.edit")
        data = await request.json()
        order_ids = data.get('order_ids', [])
        await GroupService.add_orders_to_group(group_id, order_ids)
        return {"success": True}
    except Exception as e:
        logger.error(f"Error adding orders to group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/api/groups/{group_id}/orders")
async def remove_group_orders_api(group_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.edit")
        data = await request.json()
        order_ids = data.get('order_ids', [])
        await GroupService.remove_orders_from_group(group_id, order_ids)
        return {"success": True}
    except Exception as e:
        logger.error(f"Error removing orders from group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/groups/{group_id}/update_status")
async def update_group_status_api(group_id: int, request: Request, current_admin: dict = Depends(get_current_admin)):
    try:
        check_permission(current_admin, "orders.edit")
        data = await request.json()
        new_status = data.get('status')
        if not new_status:
             raise HTTPException(400, "Status required")
             
        order_ids = await GroupService.get_group_order_ids(group_id)
        await OrderService.bulk_update_order_statuses(order_ids, new_status)
        return {"success": True, "count": len(order_ids)}
    except Exception as e:
        logger.error(f"Error updating group status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
