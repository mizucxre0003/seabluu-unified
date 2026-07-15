import logging
from typing import List, Optional
from app.database import db
from app.models import AdminUser, AdminUserCreate, AdminUserUpdate
from app.utils.security import hash_password, verify_password, generate_avatar_url

logger = logging.getLogger(__name__)

class AdminService:
    # Примечание: создание первого супер-админа при пустой таблице admin_users
    # выполняется в Database.init_tables() (app/database.py) — там же корректно
    # ищется роль "Супер-администратор". Здесь такой логики больше нет: раньше
    # был второй, дублирующий сценарий с багом (искал роль по имени 'super_admin',
    # которого не существует, и в этом случае создавал админа без роли).

    @staticmethod
    async def authenticate_user(username: str, password: str) -> Optional[AdminUser]:
        """Аутентификация пользователя"""
        try:
            async with db.pool.acquire() as conn:
                # Получаем пользователя из базы данных
                row = await conn.fetchrow('''
                    SELECT id, username, email, password_hash, role_id, avatar_url, is_active, last_login, created_at, updated_at
                    FROM admin_users
                    WHERE username = $1 AND is_active = TRUE
                ''', username)
                
                if not row:
                    return None
                
                if not verify_password(password, row['password_hash']):
                    return None
                
                # Преобразуем row в AdminUser, явно указывая поля
                user_data = dict(row)
                return AdminUser(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=user_data['password_hash'],
                    role_id=user_data['role_id'],
                    avatar_url=user_data['avatar_url'],
                    is_active=user_data['is_active'],
                    last_login=user_data['last_login'],
                    created_at=user_data['created_at'],
                    updated_at=user_data['updated_at']
                )
                
        except Exception as e:
            logger.error(f"Error authenticating user {username}: {e}")
            return None
    
    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[AdminUser]:
        """Получить пользователя по ID"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT id, username, email, password_hash, role_id, avatar_url, is_active, last_login, created_at, updated_at
                    FROM admin_users
                    WHERE id = $1
                ''', user_id)
                
                if not row:
                    return None
                
                # Преобразуем row в AdminUser, явно указывая поля
                user_data = dict(row)
                return AdminUser(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=user_data['password_hash'],
                    role_id=user_data['role_id'],
                    avatar_url=user_data['avatar_url'],
                    is_active=user_data['is_active'],
                    last_login=user_data['last_login'],
                    created_at=user_data['created_at'],
                    updated_at=user_data['updated_at']
                )
                
        except Exception as e:
            logger.error(f"Error getting user by id {user_id}: {e}")
            return None
    
    @staticmethod
    async def get_user_by_username(username: str) -> Optional[AdminUser]:
        """Получить пользователя по username"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT id, username, email, password_hash, role_id, avatar_url, is_active, last_login, created_at, updated_at
                    FROM admin_users
                    WHERE username = $1
                ''', username)
                
                if not row:
                    return None
                
                # Преобразуем row в AdminUser, явно указывая поля
                user_data = dict(row)
                return AdminUser(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=user_data['password_hash'],
                    role_id=user_data['role_id'],
                    avatar_url=user_data['avatar_url'],
                    is_active=user_data['is_active'],
                    last_login=user_data['last_login'],
                    created_at=user_data['created_at'],
                    updated_at=user_data['updated_at']
                )
                
        except Exception as e:
            logger.error(f"Error getting user by username {username}: {e}")
            return None
    
    @staticmethod
    async def get_all_users() -> List[dict]:
        """Получить всех пользователей с названиями ролей"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT au.id, au.username, au.email, au.password_hash, au.role_id, 
                           au.avatar_url, au.is_active, au.last_login, au.created_at, au.updated_at,
                           r.name as role_name
                    FROM admin_users au
                    LEFT JOIN roles r ON au.role_id = r.id
                    ORDER BY au.created_at DESC
                ''')
                
                users = []
                for row in rows:
                    user_data = dict(row)
                    users.append({
                        'id': user_data['id'],
                        'username': user_data['username'],
                        'email': user_data['email'],
                        'role_id': user_data['role_id'],
                        'role_name': user_data.get('role_name', 'Не назначена'),
                        'avatar_url': user_data['avatar_url'],
                        'is_active': user_data['is_active'],
                        'last_login': user_data['last_login'],
                        'created_at': user_data['created_at'],
                        'updated_at': user_data['updated_at']
                    })
                
                return users
                
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    @staticmethod
    async def create_user(user_data: AdminUserCreate) -> AdminUser:
        """Создать нового пользователя"""
        try:
            async with db.pool.acquire() as conn:
                # Генерируем аватарку
                avatar_url = generate_avatar_url(user_data.username, user_data.email)
                
                # Хэшируем пароль
                password_hash = hash_password(user_data.password)
                
                # Обрабатываем роль - если пришло название роли, преобразуем в ID
                role_id = user_data.role_id
                
                # Если пришло название роли вместо ID
                if user_data.role and not user_data.role_id:
                    role = await conn.fetchrow("SELECT id FROM roles WHERE name = $1", user_data.role)
                    if role:
                        role_id = role['id']
                    else:
                        # Если роль не найдена, используем роль по умолчанию
                        default_role = await conn.fetchrow("SELECT id FROM roles WHERE is_default = TRUE LIMIT 1")
                        if default_role:
                            role_id = default_role['id']
                
                # Если роль все еще не указана, используем роль по умолчанию
                if role_id is None:
                    default_role = await conn.fetchrow("SELECT id FROM roles WHERE is_default = TRUE LIMIT 1")
                    if default_role:
                        role_id = default_role['id']
                
                row = await conn.fetchrow('''
                    INSERT INTO admin_users (username, email, password_hash, role_id, avatar_url)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id, username, email, password_hash, role_id, avatar_url, is_active, last_login, created_at, updated_at
                ''', user_data.username, user_data.email, password_hash, role_id, avatar_url)
                
                # Преобразуем row в AdminUser, явно указывая поля
                user_data = dict(row)
                return AdminUser(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=user_data['password_hash'],
                    role_id=user_data['role_id'],
                    avatar_url=user_data['avatar_url'],
                    is_active=user_data['is_active'],
                    last_login=user_data['last_login'],
                    created_at=user_data['created_at'],
                    updated_at=user_data['updated_at']
                )
                
        except Exception as e:
            logger.error(f"Error creating user {user_data.username}: {e}")
            raise
    
    @staticmethod
    async def update_user(user_id: int, user_data: AdminUserUpdate) -> Optional[AdminUser]:
        """Обновить пользователя"""
        try:
            async with db.pool.acquire() as conn:
                # Собираем поля для обновления
                update_fields = []
                values = []
                i = 1
                
                if user_data.email is not None:
                    update_fields.append(f"email = ${i}")
                    values.append(user_data.email)
                    i += 1
                
                if user_data.role_id is not None:
                    update_fields.append(f"role_id = ${i}")
                    values.append(user_data.role_id)
                    i += 1
                
                if user_data.avatar_url is not None:
                    update_fields.append(f"avatar_url = ${i}")
                    values.append(user_data.avatar_url)
                    i += 1
                
                if user_data.is_active is not None:
                    update_fields.append(f"is_active = ${i}")
                    values.append(user_data.is_active)
                    i += 1
                
                if user_data.password is not None:
                    update_fields.append(f"password_hash = ${i}")
                    values.append(hash_password(user_data.password))
                    i += 1
                
                if not update_fields:
                    return await AdminService.get_user_by_id(user_id)
                
                values.append(user_id)
                query = f"""
                    UPDATE admin_users 
                    SET {', '.join(update_fields)}, updated_at = NOW()
                    WHERE id = ${i}
                    RETURNING id, username, email, password_hash, role_id, avatar_url, is_active, last_login, created_at, updated_at
                """
                
                row = await conn.fetchrow(query, *values)
                if not row:
                    return None
                
                return AdminUser.model_validate(dict(row))
                
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return None
    
    @staticmethod
    async def delete_user(user_id: int) -> bool:
        """Удалить пользователя"""
        try:
            async with db.pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM admin_users WHERE id = $1",
                    user_id
                )
                return "DELETE 1" in result
                
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return False

    @staticmethod
    async def update_last_login(user_id: int) -> bool:
        """Обновить время последнего входа"""
        try:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE admin_users SET last_login = NOW() WHERE id = $1",
                    user_id
                )
                return True
                
        except Exception as e:
            logger.error(f"Error updating last login for user {user_id}: {e}")
            return False
    
    @staticmethod
    async def change_password(user_id: int, current_password: str, new_password: str) -> bool:
        """Смена пароля"""
        try:
            async with db.pool.acquire() as conn:
                # Получаем текущий хэш пароля
                current_hash = await conn.fetchval(
                    "SELECT password_hash FROM admin_users WHERE id = $1",
                    user_id
                )
                
                if not current_hash or not verify_password(current_password, current_hash):
                    return False
                
                # Обновляем пароль
                new_hash = hash_password(new_password)
                await conn.execute(
                    "UPDATE admin_users SET password_hash = $1, updated_at = NOW() WHERE id = $2",
                    new_hash, user_id
                )
                
                return True
                
        except Exception as e:
            logger.error(f"Error changing password for user {user_id}: {e}")
            return False
