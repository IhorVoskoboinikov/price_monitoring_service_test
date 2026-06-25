from enum import StrEnum


class Currency(StrEnum):
    """Поддерживаемые валюты. StrEnum: член == своя строка ('USD'), поэтому
    значение прозрачно подставляется в URL НБУ, ключи Redis и сравнения."""

    USD = "USD"
    UAH = "UAH"
    EUR = "EUR"
    GBP = "GBP"


class TrendDirection(StrEnum):
    """Тренд цены: средняя за сегодня против средней за предыдущие 30 дней."""

    UP = "up"
    DOWN = "down"
    SAME = "same"


class SortOption(StrEnum):
    """Сортировка списка товаров."""

    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    TREND_ASC = "trend_asc"
    TREND_DESC = "trend_desc"
