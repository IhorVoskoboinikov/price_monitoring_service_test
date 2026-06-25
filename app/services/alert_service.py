import uuid
from datetime import date
from decimal import Decimal

from app.core.email import send_email
from app.core.exceptions import NotFoundError
from app.core.logger import get_logger
from app.db.models.price_alert import PriceAlert
from app.db.repositories.alert_repo import AlertRepo
from app.db.repositories.product_repo import ProductRepo
from app.schemas.alert import AlertCreate, AlertResponse
from app.schemas.enums import Currency
from app.services.currency_service import CurrencyService

logger = get_logger(__name__)


class AlertService:
    def __init__(
        self,
        alerts: AlertRepo,
        products: ProductRepo,
        currency: CurrencyService,
    ) -> None:
        self.alerts = alerts
        self.products = products
        self.currency = currency

    async def get_alerts(self, user_id: uuid.UUID) -> list[AlertResponse]:
        rows = await self.alerts.list_by_user(user_id)
        return [AlertResponse.model_validate(r) for r in rows]

    async def create_alert(
        self, user_id: uuid.UUID, data: AlertCreate
    ) -> AlertResponse:
        if not await self.products.exists(data.product_id):
            raise NotFoundError("Product not found")

        threshold_usd = await self._to_usd(data.threshold_price, data.currency)

        alert = PriceAlert(
            id=uuid.uuid4(),
            user_id=user_id,
            product_id=data.product_id,
            threshold_price_usd=threshold_usd,
            currency_code=data.currency,
            is_active=True,
        )
        self.alerts.add(alert)
        await self.alerts.flush()
        await self.alerts.refresh(alert)  # подтянуть created_at (server_default)
        logger.info(
            f"Alert created | user={user_id} product={data.product_id} "
            f"threshold_usd={threshold_usd}"
        )
        return AlertResponse.model_validate(alert)

    async def delete_alert(self, user_id: uuid.UUID, alert_id: uuid.UUID) -> None:
        deleted = await self.alerts.delete(alert_id, user_id)
        if deleted == 0:
            raise NotFoundError("Alert not found")
        logger.info(f"Alert deleted | user={user_id} alert={alert_id}")

    async def check_alerts(self) -> int:
        """Находит сработавшие алерты, шлёт письма и деактивирует их.

        Возвращает число отправленных уведомлений. Вызывается Celery-задачей;
        commit — на стороне вызывающего.
        """
        triggered = await self.alerts.list_triggered()
        sent = 0
        for row in triggered:
            subject = f"Цена снизилась: {row.product_title}"
            body = (
                f"Цена на товар «{row.product_title}» достигла вашего порога.\n\n"
                f"Текущая минимальная цена: ${row.min_price_usd}\n"
                f"Ваш порог: ${row.threshold_price_usd} "
                f"(указан в {row.currency_code})\n"
            )
            try:
                await send_email(row.email, subject, body)
            except Exception:
                logger.exception(f"Failed to send alert email | alert={row.id}")
                continue
            await self.alerts.deactivate(row.id)
            sent += 1
        logger.info(f"check_alerts done | triggered={len(triggered)} sent={sent}")
        return sent

    async def _to_usd(self, amount: Decimal, currency: Currency) -> Decimal:
        """Перевести пороговую цену из указанной валюты в USD.

        convert() идёт USD→валюта (price_other = price_usd * rate_usd / rate_other),
        обратное преобразование: price_usd = price_other * rate_other / rate_usd.
        """
        if currency == Currency.USD:
            return amount
        today = date.today()
        rate_usd = await self.currency.get_rate(Currency.USD, today)
        rate_other = await self.currency.get_rate(currency, today)
        return (amount * rate_other / rate_usd).quantize(Decimal("0.0001"))
