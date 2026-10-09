class UserError(Exception):
    pass


class UserNotFoundError(UserError):
    pass


class AccessDeniedError(UserError):
    pass


class LastAdminError(UserError):
    """Операция оставила бы систему без администратора."""


class SelfModificationError(UserError):
    """Администратор не может снять с себя ROLE_ADMIN или удалить себя."""
