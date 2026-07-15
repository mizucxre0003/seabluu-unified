from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Order(BaseModel):
    order_id: str
    client_name: str
    phone: Optional[str] = None
    origin: Optional[str] = None
    status: str
    note: Optional[str] = None
    country: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Participant(BaseModel):
    order_id: str
    username: str
    paid: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Address(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    postcode: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Subscription(BaseModel):
    user_id: int
    order_id: str
    last_sent_status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Модели для групп заказов
class Group(BaseModel):
    id: int
    name: str
    created_at: Optional[datetime] = None
    # Список заказов не храним в модели Group напрямую для БД, но можем использовать для API responses
    order_count: Optional[int] = None 

    class Config:
        from_attributes = True

class GroupCreate(BaseModel):
    name: str

class GroupUpdate(BaseModel):
    name: str

# Модели для системы аккаунтов
class AdminUser(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    password_hash: Optional[str] = None
    role_id: Optional[int] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        alias_generator = None
        extra = "forbid"

class AdminUserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str
    role_id: Optional[int] = None

    class Config:
        alias_generator = None
        extra = "forbid"

class AdminUserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None

    class Config:
        alias_generator = None
        extra = "forbid"

class AdminChatMessage(BaseModel):
    id: int
    user_id: int
    username: str
    message: str
    is_system: bool = False
    created_at: Optional[datetime] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True

class AdminChatMessageCreate(BaseModel):
    message: str

# Модели для системы ролей и разрешений
class Permission(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Role(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    permissions: List[str] = []
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []
    is_default: bool = False

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_default: Optional[bool] = None
