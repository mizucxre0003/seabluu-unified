class PermissionChecker:
    """Константы ролей. Реальная проверка прав живёт в web_admin.py:
    check_permission(current_admin, "orders.view") и check_super_admin(current_admin) —
    они сверяются напрямую со списком прав пользователя (RoleService.check_permission),
    а не с этим классом."""

    SUPER_ADMIN_ROLE = "Супер-администратор"
    ADMIN_ROLE = "Администратор"
    MANAGER_ROLE = "Менеджер"
    VIEWER_ROLE = "Наблюдатель"
