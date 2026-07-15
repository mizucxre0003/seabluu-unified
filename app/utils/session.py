from fastapi import Request, HTTPException
from app.utils.security import verify_token
from app.services.admin_service import AdminService
from app.models import AdminUser

async def get_current_admin(request: Request):
    """Получение текущего администратора из токена"""
    import logging
    logger = logging.getLogger(__name__)
    
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    username = payload.get("sub")
    user_id = payload.get("user_id")
    
    if not username or not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    # Получаем актуальные данные пользователя из базы
    admin_user = await AdminService.get_user_by_id(user_id)
    if not admin_user or not admin_user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    
    # Получаем название роли и разрешения из базы данных
    from app.services.role_service import RoleService
    role_name = "admin"
    permissions = []
    
    logger.info(f"Getting role for user {username} with role_id: {admin_user.role_id}")
    
    # Используем role_id для получения названия роли из базы данных
    if admin_user.role_id:
        role_obj = await RoleService.get_role_by_id(admin_user.role_id)
        if role_obj:
            role_name = role_obj.get('name', 'admin')
            permissions = role_obj.get('permissions', [])
            logger.info(f"Found role: {role_name} with permissions: {permissions}")
        else:
            logger.warning(f"Role with id {admin_user.role_id} not found")
    else:
        logger.warning(f"User {username} has no role_id")
    
    # Возвращаем реальные данные пользователя из базы
    return {
        "user_id": admin_user.id,
        "username": admin_user.username,
        "role": role_name,
        "permissions": permissions,
        "avatar_url": admin_user.avatar_url
    }
