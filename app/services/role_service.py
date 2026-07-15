import logging
import json
from typing import List, Optional
from app.database import db

logger = logging.getLogger(__name__)

class RoleService:
    
    # Стандартные разрешения
    PERMISSIONS = [
        # Заказы
        ("orders.view", "Просмотр заказов", "orders"),
        ("orders.create", "Создание заказов", "orders"),
        ("orders.edit", "Редактирование заказов", "orders"),
        ("orders.delete", "Удаление заказов", "orders"),
        
        # Участники
        ("participants.view", "Просмотр участников", "participants"),
        ("participants.edit", "Редактирование участников", "participants"),
        
        # Адреса
        ("addresses.view", "Просмотр адресов", "addresses"),
        ("addresses.export", "Экспорт адресов", "addresses"),
        
        # Отчеты
        ("reports.view", "Просмотр отчетов", "reports"),
        ("reports.export", "Экспорт отчетов", "reports"),
        
        # Рассылки
        ("broadcast.send", "Отправка рассылок", "broadcast"),
        
        # Администраторы
        ("admin_users.view", "Просмотр администраторов", "admin_users"),
        ("admin_users.create", "Создание администраторов", "admin_users"),
        ("admin_users.edit", "Редактирование администраторов", "admin_users"),
        ("admin_users.delete", "Удаление администраторов", "admin_users"),
        
        # Роли
        ("roles.view", "Просмотр ролей", "roles"),
        ("roles.create", "Создание ролей", "roles"),
        ("roles.edit", "Редактирование ролей", "roles"),
        ("roles.delete", "Удаление ролей", "roles"),
        
        # Настройки
        ("settings.view", "Просмотр настроек", "settings"),
        ("settings.edit", "Редактирование настроек", "settings"),
    ]
    
    # Стандартные роли
    DEFAULT_ROLES = {
        "super_admin": {
            "name": "Супер-администратор",
            "description": "Полный доступ ко всем функциям",
            "permissions": [perm[0] for perm in PERMISSIONS],
            "is_default": False
        },
        "admin": {
            "name": "Администратор",
            "description": "Расширенный доступ",
            "permissions": [
                "orders.view", "orders.create", "orders.edit", "orders.delete",
                "participants.view", "participants.edit",
                "addresses.view", "addresses.export",
                "reports.view", "reports.export",
                "broadcast.send",
                "settings.view"
            ],
            "is_default": True
        },
        "manager": {
            "name": "Менеджер",
            "description": "Базовый доступ для работы с заказами",
            "permissions": [
                "orders.view", "orders.create", "orders.edit",
                "participants.view", "participants.edit",
                "addresses.view",
                "reports.view"
            ],
            "is_default": False
        },
        "viewer": {
            "name": "Наблюдатель",
            "description": "Только просмотр данных",
            "permissions": [
                "orders.view",
                "participants.view",
                "addresses.view",
                "reports.view"
            ],
            "is_default": False
        }
    }
    
    @staticmethod
    async def initialize_roles():
        """Инициализация стандартных ролей и разрешений"""
        try:
            async with db.pool.acquire() as conn:
                # Создаем таблицу ролей если не существует
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS roles (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL UNIQUE,
                        description TEXT,
                        permissions JSONB NOT NULL DEFAULT '[]',
                        is_default BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # Добавляем стандартные роли
                for role_key, role_data in RoleService.DEFAULT_ROLES.items():
                    # Преобразуем список разрешений в JSON строку
                    permissions_json = json.dumps(role_data["permissions"])
                    await conn.execute('''
                        INSERT INTO roles (name, description, permissions, is_default)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (name) DO UPDATE SET
                            description = EXCLUDED.description,
                            permissions = EXCLUDED.permissions,
                            is_default = EXCLUDED.is_default,
                            updated_at = NOW()
                    ''', role_data["name"], role_data["description"], 
                       permissions_json, role_data["is_default"])
                
                logger.info("Roles initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing roles: {e}")
    
    @staticmethod
    async def get_all_roles():
        """Получить все роли"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM roles ORDER BY name")
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all roles: {e}")
            return []
    
    @staticmethod
    async def get_role_by_id(role_id: int):
        """Получить роль по ID"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM roles WHERE id = $1", role_id)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting role {role_id}: {e}")
            return None
    
    @staticmethod
    async def get_role_by_name(name: str):
        """Получить роль по имени"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM roles WHERE name = $1", name)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting role {name}: {e}")
            return None
    
    @staticmethod
    async def create_role(name: str, description: str = None, permissions: List[str] = None, is_default: bool = False):
        """Создать новую роль"""
        try:
            async with db.pool.acquire() as conn:
                permissions = permissions or []
                row = await conn.fetchrow('''
                    INSERT INTO roles (name, description, permissions, is_default)
                    VALUES ($1, $2, $3, $4)
                    RETURNING *
                ''', name, description, permissions, is_default)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating role {name}: {e}")
            return None
    
    @staticmethod
    async def update_role(role_id: int, name: str = None, description: str = None, permissions: List[str] = None, is_default: bool = None):
        """Обновить роль"""
        try:
            async with db.pool.acquire() as conn:
                # Собираем поля для обновления
                update_fields = []
                update_values = []
                
                if name is not None:
                    update_fields.append("name = $%d")
                    update_values.append(name)
                if description is not None:
                    update_fields.append("description = $%d")
                    update_values.append(description)
                if permissions is not None:
                    update_fields.append("permissions = $%d")
                    update_values.append(permissions)
                if is_default is not None:
                    update_fields.append("is_default = $%d")
                    update_values.append(is_default)
                
                if not update_fields:
                    return await RoleService.get_role_by_id(role_id)
                
                update_fields.append("updated_at = NOW()")
                update_values.append(role_id)
                
                query = f"UPDATE roles SET {', '.join(update_fields)} WHERE id = ${len(update_values)} RETURNING *"
                row = await conn.fetchrow(query, *update_values)
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Error updating role {role_id}: {e}")
            return None
    
    @staticmethod
    async def delete_role(role_id: int):
        """Удалить роль"""
        try:
            async with db.pool.acquire() as conn:
                # Проверяем, что роль не используется
                users_count = await conn.fetchval("SELECT COUNT(*) FROM admin_users WHERE role_id = $1", role_id)
                if users_count > 0:
                    return False
                
                # Проверяем, что это не стандартная роль
                role = await RoleService.get_role_by_id(role_id)
                if role and role.get('is_default'):
                    return False
                
                result = await conn.execute("DELETE FROM roles WHERE id = $1", role_id)
                return "DELETE 1" in result
                
        except Exception as e:
            logger.error(f"Error deleting role {role_id}: {e}")
            return False
    
    @staticmethod
    async def get_default_role():
        """Получить роль по умолчанию"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM roles WHERE is_default = TRUE")
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting default role: {e}")
            return None
    
    @staticmethod
    async def get_permissions_list():
        """Получить список всех разрешений"""
        return [{"id": perm[0], "name": perm[1], "category": perm[2]} for perm in RoleService.PERMISSIONS]
    
    @staticmethod
    def check_permission(user_permissions: List[str], required_permission: str) -> bool:
        """Проверить наличие разрешения у пользователя"""
        return required_permission in user_permissions
    
    @staticmethod
    async def get_user_permissions(role_id: int) -> List[str]:
        """Получить разрешения пользователя по его роли"""
        try:
            if role_id:
                role = await RoleService.get_role_by_id(role_id)
                if role:
                    return role.get('permissions', [])
            
            # Если роль не найдена, возвращаем разрешения по умолчанию
            default_role = await RoleService.get_default_role()
            return default_role.get('permissions', []) if default_role else []
            
        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return []
