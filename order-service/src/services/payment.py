from decimal import Decimal
from uuid import UUID

from events import uuid7
from platform_lib.logging import get_logger
from src.services.ports import PaymentResult

log = get_logger(__name__)

DECLINED_CENTS = Decimal("0.13")


class FakePaymentGateway:
    """Имитация платёжного провайдера для учебного стенда.

    Платёж проходит всегда, кроме сумм, оканчивающихся на .13 — детерминированный
    способ проверить отказ оплаты.
    """

    async def charge(self, order_id: UUID, amount: Decimal, currency: str) -> PaymentResult:
        if amount % 1 == DECLINED_CENTS:
            log.info("payment_declined", order_id=str(order_id))
            return PaymentResult(success=False, provider_ref="", error="card declined")
        ref = f"fake-{uuid7()}"
        log.info("payment_charged", order_id=str(order_id), provider_ref=ref)
        return PaymentResult(success=True, provider_ref=ref)

    async def refund(self, provider_ref: str, amount: Decimal, currency: str) -> PaymentResult:
        log.info("payment_refunded", provider_ref=provider_ref)
        return PaymentResult(success=True, provider_ref=provider_ref)
