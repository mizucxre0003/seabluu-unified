import logging
from typing import List, Optional, Dict, Any
from app.models import Group, Order
from app.database import db

logger = logging.getLogger(__name__)

class GroupService:
    @staticmethod
    async def create_group(name: str) -> Group:
        """Создать новую группу"""
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO groups (name)
                VALUES ($1)
                RETURNING id, name, created_at
            """, name)
            return Group(**dict(row))

    @staticmethod
    async def list_groups() -> List[Group]:
        """Список всех групп с количеством заказов"""
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT g.*, COUNT(go.order_id) as order_count
                FROM groups g
                LEFT JOIN group_orders go ON g.id = go.group_id
                GROUP BY g.id
                ORDER BY g.created_at DESC
            """)
            return [Group(**dict(row)) for row in rows]

    @staticmethod
    async def get_group(group_id: int) -> Optional[Group]:
        """Получить группу по ID"""
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT g.*, COUNT(go.order_id) as order_count
                FROM groups g
                LEFT JOIN group_orders go ON g.id = go.group_id
                WHERE g.id = $1
                GROUP BY g.id
            """, group_id)
            if row:
                return Group(**dict(row))
            return None

    @staticmethod
    async def delete_group(group_id: int):
        """Удалить группу"""
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM groups WHERE id = $1", group_id)

    @staticmethod
    async def update_group(group_id: int, name: str) -> Optional[Group]:
        """Обновить название группы"""
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE groups
                SET name = $1
                WHERE id = $2
                RETURNING id, name, created_at
            """, name, group_id)
            if row:
                return Group(**dict(row))
            return None

    @staticmethod
    async def add_orders_to_group(group_id: int, order_ids: List[str]):
        """Добавить заказы в группу"""
        if not order_ids:
            return
            
        async with db.pool.acquire() as conn:
            # Используем executemany для массовой вставки
            data = [(group_id, oid) for oid in order_ids]
            try:
                await conn.executemany("""
                    INSERT INTO group_orders (group_id, order_id)
                    VALUES ($1, $2)
                    ON CONFLICT (group_id, order_id) DO NOTHING
                """, data)
            except Exception as e:
                logger.error(f"Error adding orders to group: {e}")
                raise

    @staticmethod
    async def remove_orders_from_group(group_id: int, order_ids: List[str]):
        """Удалить заказы из группы"""
        if not order_ids:
            return
            
        async with db.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM group_orders
                WHERE group_id = $1 AND order_id = ANY($2)
            """, group_id, order_ids)

    @staticmethod
    async def get_group_orders(group_id: int) -> List[Order]:
        """Получить заказы в группе"""
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT o.*
                FROM orders o
                JOIN group_orders go ON o.order_id = go.order_id
                WHERE go.group_id = $1
                ORDER BY o.created_at DESC
            """, group_id)
            return [Order(**dict(row)) for row in rows]
            
    @staticmethod
    async def get_group_order_ids(group_id: int) -> List[str]:
        """Получить ID заказов в группе"""
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT order_id
                FROM group_orders
                WHERE group_id = $1
            """, group_id)
            return [row['order_id'] for row in rows]
