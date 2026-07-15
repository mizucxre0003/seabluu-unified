#!/usr/bin/env python3
"""Скрипт для миграции системы ролей"""

import asyncio
import json
import os
from dotenv import load_dotenv
from app.database import db
from app.utils.security import hash_password
from app.services.role_service import RoleService

load_dotenv()

async def migrate_roles():
    """Миграция системы ролей"""
    try:
        # Подключаемся к базе данных
        await db.init()
        
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
            
            # 2. Инициализируем стандартные роли
            print("👥 Создаем стандартные роли...")
            await RoleService.initialize_roles()
            
            # 3. Добавляем колонку role_id в admin_users если не существует
            print("🔄 Добавляем колонку role_id в таблицу admin_users...")
            await conn.execute('ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role_id INTEGER REFERENCES roles(id)')
            
            # 4. Мигрируем существующих пользователей
            print("👤 Мигрируем существующих администраторов...")
            
            # Получаем ID ролей
            super_admin_id = await conn.fetchval("SELECT id FROM roles WHERE name = 'super_admin'")
            admin_id = await conn.fetchval("SELECT id FROM roles WHERE name = 'admin'")
            
            if not super_admin_id:
                print("❌ Роль super_admin не найдена!")
                return
            
            if not admin_id:
                print("❌ Роль admin не найдена!")
                return
            
            # Мигрируем пользователей на основе их текущей роли
            await conn.execute('''
                UPDATE admin_users 
                SET role_id = CASE 
                    WHEN role = 'super_admin' THEN $1
                    ELSE $2
                END
                WHERE role_id IS NULL
            ''', super_admin_id, admin_id)
            
            # 5. Удаляем старую колонку role если она существует
            print("🗑️ Удаляем старую колонку role...")
            try:
                await conn.execute('ALTER TABLE admin_users DROP COLUMN IF EXISTS role')
            except Exception as e:
                print(f"⚠️ Не удалось удалить колонку role: {e}")
            
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

if __name__ == "__main__":
    asyncio.run(migrate_roles())