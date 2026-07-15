import logging
from typing import List, Optional, Dict, Any
from app.models import Order, Participant
from app.database import db

logger = logging.getLogger(__name__)

class OrderService:
    
    @staticmethod
    async def get_order(order_id: str) -> Optional[Order]:
        """Получить заказ по ID"""
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT order_id, client_name, phone, origin, status, note, country, created_at, updated_at FROM orders WHERE order_id = $1", 
                    order_id
                )
                if row:
                    # Преобразуем row в dict и убираем поле 'id' если оно есть
                    order_dict = dict(row)
                    if 'id' in order_dict:
                        del order_dict['id']
                    return Order(**order_dict)
            return None
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return None
    
    @staticmethod
    async def add_order(order: Order) -> bool:
        """Добавить новый заказ"""
        try:
            async with db.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO orders (order_id, client_name, phone, origin, status, note, country)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (order_id) DO UPDATE SET
                    client_name = EXCLUDED.client_name,
                    phone = EXCLUDED.phone,
                    origin = EXCLUDED.origin,
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    country = EXCLUDED.country,
                    updated_at = NOW()
                ''', order.order_id, order.client_name, order.phone, order.origin, 
                   order.status, order.note, order.country)
                return True
        except Exception as e:
            logger.error(f"Error adding order {order.order_id}: {e}")
            return False
    
    @staticmethod
    async def update_order_status(order_id: str, new_status: str) -> bool:
        """Обновить статус заказа"""
        try:
            async with db.pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE orders SET status = $1, updated_at = NOW() WHERE order_id = $2",
                    new_status, order_id
                )
                return "UPDATE 1" in result
        except Exception as e:
            logger.error(f"Error updating order status {order_id}: {e}")
            return False
    
    @staticmethod
    async def list_orders_by_note(note: str) -> List[Order]:
        """Найти заказы по метке в примечании"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, client_name, phone, origin, status, note, country, created_at, updated_at FROM orders WHERE note ILIKE $1 ORDER BY updated_at DESC",
                    f"%{note}%"
                )
                orders = []
                for row in rows:
                    order_dict = dict(row)
                    if 'id' in order_dict:
                        del order_dict['id']
                    orders.append(Order(**order_dict))
                return orders
        except Exception as e:
            logger.error(f"Error getting orders by note: {e}")
            return []
    
    @staticmethod
    async def get_unique_notes() -> List[str]:
        """Получить список уникальных меток из заказов"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT note FROM orders WHERE note IS NOT NULL AND note != '' ORDER BY note"
                )
                return [row['note'] for row in rows if row['note']]
        except Exception as e:
            logger.error(f"Error getting unique notes: {e}")
            return []
    
    @staticmethod
    async def list_recent_orders(limit: int = 20) -> List[Order]:
        """Список последних заказов"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, client_name, phone, origin, status, note, country, created_at, updated_at FROM orders ORDER BY updated_at DESC LIMIT $1",
                    limit
                )
                orders = []
                for row in rows:
                    order_dict = dict(row)
                    if 'id' in order_dict:
                        del order_dict['id']
                    orders.append(Order(**order_dict))
                return orders
        except Exception as e:
            logger.error(f"Error listing recent orders: {e}")
            return []

    @staticmethod
    async def list_orders_by_status(statuses: List[str]) -> List[Order]:
        """Список заказов по статусам"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, client_name, phone, origin, status, note, country, created_at, updated_at FROM orders WHERE status = ANY($1) ORDER BY updated_at DESC",
                    statuses
                )
                orders = []
                for row in rows:
                    order_dict = dict(row)
                    if 'id' in order_dict:
                        del order_dict['id']
                    orders.append(Order(**order_dict))
                return orders
        except Exception as e:
            logger.error(f"Error listing orders by status: {e}")
            return []

    @staticmethod
    async def update_order(order_id: str, update_data: dict) -> bool:
        """Обновление данных заказа с отправкой уведомлений"""
        try:
            old_order = await OrderService.get_order(order_id)
            if not old_order:
                return False
            # Поддержка переименования order_id: если в update_data есть ключ 'order_id'
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    target_id = order_id

                    # Обработка изменения идентификатора заказа
                    if 'order_id' in update_data and update_data['order_id'] and update_data['order_id'] != order_id:
                        new_id = update_data.pop('order_id')

                        # Проверяем, не существует ли уже заказ с новым ID
                        existing = await conn.fetchval("SELECT 1 FROM orders WHERE order_id = $1", new_id)
                        if existing:
                            logger.error(f"Cannot rename order {order_id} to {new_id}: target exists")
                            return False

                        # Обновляем связанные таблицы
                        await conn.execute("UPDATE participants SET order_id = $1 WHERE order_id = $2", new_id, order_id)
                        await conn.execute("UPDATE subscriptions SET order_id = $1 WHERE order_id = $2", new_id, order_id)

                        # Переименовываем сам заказ
                        await conn.execute("UPDATE orders SET order_id = $1, updated_at = NOW() WHERE order_id = $2", new_id, order_id)
                        target_id = new_id

                    # Обновление остальных полей (client_name, country, note, status)
                    set_parts = []
                    values = []
                    i = 1
                    for key, value in update_data.items():
                        if key in ["client_name", "country", "note", "status"]:
                            set_parts.append(f"{key} = ${i}")
                            values.append(value)
                            i += 1

                    if set_parts:
                        values.append(target_id)
                        query = f"UPDATE orders SET {', '.join(set_parts)}, updated_at = NOW() WHERE order_id = ${i}"
                        result = await conn.execute(query, *values)
                    else:
                        result = 'UPDATE 0'

                    # Отправляем уведомления если статус изменился
                    if 'status' in update_data and update_data['status'] != old_order.status:
                        await OrderService._send_status_notifications(target_id, update_data['status'])

                    return "UPDATE 1" in result or True
                
        except Exception as e:
            logger.error(f"Error updating order {order_id}: {e}")
            return False

    @staticmethod
    async def _send_status_notifications(order_id: str, new_status: str):
        """Отправка уведомлений о смене статуса подписанным пользователям"""
        try:
            from app.services.user_service import SubscriptionService
            
            # Получаем подписанных пользователей
            subscriptions = await SubscriptionService.get_subscriptions_by_order(order_id)
            if not subscriptions:
                return
            
            # Получаем информацию о заказе
            order = await OrderService.get_order(order_id)
            if not order:
                return
            
            # Формируем сообщение
            message = f"🔄 <b>Обновление статуса заказа</b>\n\n"
            message += f"📦 <b>Заказ:</b> {order.order_id}\n"
            message += f"👤 <b>Клиент:</b> {order.client_name}\n"
            message += f"🌍 <b>Страна:</b> {order.country}\n"
            message += f"🔄 <b>Новый статус:</b> {new_status}\n"
            message += f"\n💡 <i>Следите за обновлениями!</i>"
            
            # Отправляем уведомления
            from app.webhook import application
            if application and application.bot:
                for subscription in subscriptions:
                    try:
                        await application.bot.send_message(
                            chat_id=subscription.user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent status notification to {subscription.user_id} for order {order_id}")
                    except Exception as e:
                        logger.error(f"Error sending notification to {subscription.user_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error sending status notifications for order {order_id}: {e}")

    @staticmethod
    async def delete_order(order_id: str) -> bool:
        """Удаление заказа и связанных данных"""
        try:
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    # Удаляем участников
                    await conn.execute(
                        "DELETE FROM participants WHERE order_id = $1",
                        order_id
                    )
                    
                    # Удаляем подписки
                    await conn.execute(
                        "DELETE FROM subscriptions WHERE order_id = $1", 
                        order_id
                    )
                    
                    # Удаляем заказ
                    result = await conn.execute(
                        "DELETE FROM orders WHERE order_id = $1",
                        order_id
                    )
                    
                    return "DELETE 1" in result
                    
        except Exception as e:
            logger.error(f"Error deleting order {order_id}: {e}")
            return False
            
    @staticmethod
    async def bulk_update_order_statuses(order_ids: List[str], new_status: str) -> bool:
        """Массовое обновление статусов заказов с уведомлениями"""
        try:
            async with db.pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE orders SET status = $1, updated_at = NOW() WHERE order_id = ANY($2)",
                    new_status, order_ids
                )
                success = "UPDATE" in result
                
                if success:
                    # Отправляем уведомления для каждого обновленного заказа
                    # Запускаем в фоне, чтобы не блокировать ответ
                    import asyncio
                    for order_id in order_ids:
                        # Используем create_task для параллельной отправки или await для последовательной
                        # Лучше await чтобы не перегружать loop если заказов тысячи, 
                        # но здесь предполагается разумное количество
                        try:
                            await OrderService._send_status_notifications(order_id, new_status)
                        except Exception as e:
                            logger.error(f"Error sending notification for {order_id} in bulk update: {e}")
                            
                return success
        except Exception as e:
            logger.error(f"Error bulk updating order statuses: {e}")
            return False

class ParticipantService:
    
    @staticmethod
    async def ensure_participants(order_id: str, usernames: List[str]) -> bool:
        """Добавить участников, если их ещё нет"""
        try:
            async with db.pool.acquire() as conn:
                for username in usernames:
                    await conn.execute('''
                        INSERT INTO participants (order_id, username, paid)
                        VALUES ($1, $2, FALSE)
                        ON CONFLICT (order_id, username) DO NOTHING
                    ''', order_id, username.lower().lstrip('@'))
                return True
        except Exception as e:
            logger.error(f"Error ensuring participants for {order_id}: {e}")
            return False
    
    @staticmethod
    async def get_participants(order_id: str) -> List[Participant]:
        """Получить участников заказа"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, username, paid, created_at, updated_at FROM participants WHERE order_id = $1 ORDER BY username",
                    order_id
                )
                participants = []
                for row in rows:
                    participant_dict = dict(row)
                    if 'id' in participant_dict:
                        del participant_dict['id']
                    participants.append(Participant(**participant_dict))
                return participants
        except Exception as e:
            logger.error(f"Error getting participants for {order_id}: {e}")
            return []

    @staticmethod
    async def toggle_participant_paid(order_id: str, username: str) -> bool:
        """Переключить статус оплаты участника"""
        try:
            async with db.pool.acquire() as conn:
                # Сначала получаем текущее значение
                current = await conn.fetchval(
                    "SELECT paid FROM participants WHERE order_id = $1 AND username = $2",
                    order_id, username.lower().lstrip('@')
                )
                
                if current is None:
                    return False
                
                new_paid = not current
                result = await conn.execute(
                    "UPDATE participants SET paid = $1, updated_at = NOW() WHERE order_id = $2 AND username = $3",
                    new_paid, order_id, username.lower().lstrip('@')
                )
                return "UPDATE 1" in result
        except Exception as e:
            logger.error(f"Error toggling participant paid status: {e}")
            return False
    
    @staticmethod
    async def get_unpaid_usernames(order_id: str) -> List[str]:
        """Получить список username неплательщиков"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT username FROM participants WHERE order_id = $1 AND paid = FALSE",
                    order_id
                )
                return [row['username'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting unpaid usernames: {e}")
            return []

    @staticmethod
    async def get_all_unpaid_grouped() -> Dict[str, List[str]]:
        """Сгруппировать всех неплательщиков по order_id"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, username FROM participants WHERE paid = FALSE ORDER BY order_id"
                )
                
                grouped = {}
                for row in rows:
                    order_id = row['order_id']
                    username = row['username']
                    if order_id not in grouped:
                        grouped[order_id] = []
                    grouped[order_id].append(username)
                
                return grouped
        except Exception as e:
            logger.error(f"Error getting all unpaid grouped: {e}")
            return {}
    
    @staticmethod
    async def find_orders_for_username(username: str) -> List[str]:
        """Найти заказы по username участника"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT order_id FROM participants WHERE username = $1",
                    username.lower().lstrip('@')
                )
                return [row['order_id'] for row in rows]
        except Exception as e:
            logger.error(f"Error finding orders for username: {e}")
            return []

    @staticmethod
    async def get_all_participants(limit: int = 5000) -> List[Participant]:
        """Получить всех участников из всех заказов"""
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT order_id, username, paid, created_at, updated_at FROM participants ORDER BY updated_at DESC LIMIT $1",
                    limit
                )
                participants = []
                for row in rows:
                    participant_dict = dict(row)
                    if 'id' in participant_dict:
                        del participant_dict['id']
                    participants.append(Participant(**participant_dict))
                return participants
        except Exception as e:
            logger.error(f"Error getting all participants: {e}")
            return []

    @staticmethod
    async def get_participants_paginated(
        order_id: Optional[str] = None,
        paid: Optional[bool] = None,
        search: Optional[str] = None,
        order_ids: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Оптимизированное получение участников с пагинацией на уровне БД"""
        try:
            async with db.pool.acquire() as conn:
                # Строим запрос динамически
                where_conditions = []
                params = []
                param_count = 0
                
                if order_id:
                    param_count += 1
                    where_conditions.append(f"order_id = ${param_count}")
                    params.append(order_id)
                
                if order_ids:
                    param_count += 1
                    where_conditions.append(f"order_id = ANY(${param_count})")
                    params.append(order_ids)
                
                if paid is not None:
                    param_count += 1
                    where_conditions.append(f"paid = ${param_count}")
                    params.append(paid)
                
                if search:
                    param_count += 1
                    where_conditions.append(f"(username ILIKE ${param_count} OR order_id ILIKE ${param_count})")
                    params.append(f"%{search}%")
                
                where_clause = ""
                if where_conditions:
                    where_clause = "WHERE " + " AND ".join(where_conditions)
                
                # Получаем общее количество
                count_query = f"SELECT COUNT(*) FROM participants {where_clause}"
                total = await conn.fetchval(count_query, *params)
                
                # Получаем данные с пагинацией
                param_count += 1
                params.append(limit)
                param_count += 1
                params.append(offset)
                
                data_query = f"""
                    SELECT order_id, username, paid, created_at, updated_at 
                    FROM participants 
                    {where_clause}
                    ORDER BY updated_at DESC 
                    LIMIT ${param_count - 1} OFFSET ${param_count}
                """
                
                rows = await conn.fetch(data_query, *params)
                
                participants = []
                for row in rows:
                    participant_dict = dict(row)
                    if 'id' in participant_dict:
                        del participant_dict['id']
                    participants.append(Participant(**participant_dict))
                
                return {
                    "participants": participants,
                    "total": total,
                    "has_more": (offset + limit) < total
                }
                
        except Exception as e:
            logger.error(f"Error getting paginated participants: {e}")
            return {"participants": [], "total": 0, "has_more": False}
