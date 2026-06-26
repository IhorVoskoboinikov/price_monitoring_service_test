from enum import StrEnum


class Currency(StrEnum):
    """Supported currencies. StrEnum: a member equals its own string ('USD'), so
    the value drops straight into NBU URLs, Redis keys, and comparisons."""

    USD = "USD"
    UAH = "UAH"
    EUR = "EUR"
    GBP = "GBP"


class TrendDirection(StrEnum):
    """Price trend: today's average against the average of the previous 30 days."""

    UP = "up"
    DOWN = "down"
    SAME = "same"


class SortOption(StrEnum):
    """Sort order for the product list."""

    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    TREND_ASC = "trend_asc"
    TREND_DESC = "trend_desc"
