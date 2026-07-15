#!/usr/bin/env python3
"""Скрипт для миграции системы ролей"""

import asyncio
import json
import os
import sys
from dotenv import load_dotenv

# Добавляем текущую директорию в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import db
from app.utils.security import hash_password

load_dotenv()

async def migrate_roles():
    """Миграция системы ролей"""
    try:
        # Подключаемся к базе данных
        await db.connect()
        
        print("🔧 Начинаем миграцию системы ролей...")
        
        async with db.pool.acquire() as conn:
            # 1. Создаем таблицу ролей если не существует
            print("📋 Создаем таблицу ролей...")
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS roles (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    description TEXT,
                    permissions JSONB NOT NULL DEFAULT '[]',
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            
            # 2. Создаем стандартные роли вручную
            print("👥 Создаем стандартные роли...")
            
            default_roles = [
                ('super_admin', 'Супер-администратор', [
                    'orders.view', 'orders.create', 'orders.edit', 'orders.delete',
                    'participants.view', 'participants.edit',
                    'addresses.view', 'addresses.export',
                    'reports.view', 'reports.export',
                    'broadcast.send',
                    'admin_users.view', 'admin_users.create', 'admin_users.edit', 'admin_users.delete',
                    'roles.view', 'roles.create', 'roles.edit', 'roles.delete',
                    'settings.view', 'settings.edit'
                ], False),
                ('admin', 'Администратор', [
                    'orders.view', 'orders.create', 'orders.edit', 'orders.delete',
                    'participants.view', 'participants.edit',
                    'addresses.view', 'addresses.export',
                    'reports.view', 'reports.export',
                    'broadcast.send',
                    'settings.view'
                ], True),
                ('manager', 'Менеджер', [
                    'orders.view', 'orders.create', 'orders.edit',
                    'participants.view', 'participants.edit',
                    'addresses.view',
                    'reports.view'
                ], False),
                ('viewer', 'Наблюдатель', [
                    'orders.view',
                    'participants.view',
                    'addresses.view',
                    'reports.view'
                ], False)
            ]
            
            for role_name, description, permissions, is_default in default_roles:
                permissions_json = json.dumps(permissions)
                await conn.execute('''
                    INSERT INTO roles (name, description, permissions, is_default)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description,
                        permissions = EXCLUDED.permissions,
                        is_default = EXCLUDED.is_default,
                        updated_at = NOW()
                ''', role_name, description, permissions_json, is_default)
            
            # 3. Проверяем есть ли старая колонка role
            print("🔍 Проверяем структуру таблицы admin_users...")
            
            # Проверяем есть ли колонка role
            has_role_column = await conn.fetchval('''
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'admin_users' AND column_name = 'role'
            ''')
            
            if has_role_column:
                print("📝 Найдена старая колонка role, мигрируем данные...")
                
                # Получаем ID ролей
                super_admin_id = await conn.fetchval("SELECT id FROM roles WHERE name = 'super_admin'")
                admin_id = await conn.fetchval("SELECT id FROM roles WHERE name = 'admin'")
                
                if super_admin_id and admin_id:
                    # Мигрируем пользователей на основе их текущей роли
                    await conn.execute('''
                        UPDATE admin_users 
                        SET role_id = CASE 
                            WHEN role = 'super_admin' THEN $1
                            ELSE $2
                        END
                        WHERE role_id IS NULL
                    ''', super_admin_id, admin_id)
                    
                    # Удаляем старую колонку
                    await conn.execute('ALTER TABLE admin_users DROP COLUMN role')
                    print("✅ Старая колонка role удалена")
            else:
                print("✅ Старая колонка role не найдена")
            
            # 4. Проверяем есть ли колонка role_id
            has_role_id_column = await conn.fetchval('''
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'admin_users' AND column_name = 'role_id'
            ''')
            
            if not has_role_id_column:
                print("📝 Добавляем колонку role_id...")
                await conn.execute('ALTER TABLE admin_users ADD COLUMN role_id INTEGER REFERENCES roles(id)')
            
            # 5. Обновляем пользователей без роли
            print("👤 Обновляем пользователей без роли...")
            
            default_role_id = await conn.fetchval("SELECT id FROM roles WHERE is_default = TRUE LIMIT 1")
            if default_role_id:
                await conn.execute('''
                    UPDATE admin_users 
                    SET role_id = $1
                    WHERE role_id IS NULL
                ''', default_role_id)
            
            # 6. Проверяем результат
            print("✅ Проверяем результат миграции...")
            
            # Подсчитываем пользователей по ролям
            role_stats = await conn.fetch('''
                SELECT r.name, COUNT(au.id) as user_count
                FROM roles r
                LEFT JOIN admin_users au ON r.id = au.role_id
                GROUP BY r.id, r.name
                ORDER BY r.name
            ''')
            
            print("\n📊 Статистика после миграции:")
            for stat in role_stats:
                print(f"   {stat['name']}: {stat['user_count']} пользователей")
            
            # Показываем список администраторов
            admins = await conn.fetch('''
                SELECT au.username, r.name as role_name
                FROM admin_users au
                LEFT JOIN roles r ON au.role_id = r.id
                ORDER BY r.name, au.username
            ''')
            
            print("\n👥 Список администраторов:")
            for admin in admins:
                print(f"   {admin['username']} - {admin['role_name']}")
            
            print("\n✅ Миграция завершена успешно!")
            
    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = asyncio.run(migrate_roles())
    sys.exit(0 if success else 1)