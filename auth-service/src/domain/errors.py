class AuthError(Exception):
    """Базовая ошибка домена аутентификации."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class WeakPasswordError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    """Неверный email/пароль, неактивный пользователь — наружу один и тот же ответ."""


class InvalidTokenError(AuthError):
    """Токен (refresh или подтверждения email) неизвестен, истёк или уже использован."""


class TooManyAttemptsError(AuthError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many failed login attempts")
        self.retry_after_seconds = retry_after_seconds
