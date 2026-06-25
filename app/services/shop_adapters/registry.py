from app.services.shop_adapters.base import BaseShopAdapter
from app.services.shop_adapters.dummyjson import DummyJsonAdapter
from app.services.shop_adapters.fakestore import FakeStoreAdapter

ADAPTERS: dict[str, type[BaseShopAdapter]] = {
    "dummyjson": DummyJsonAdapter,
    "fakestore": FakeStoreAdapter,
}


def get_adapter(adapter_key: str, base_url: str) -> BaseShopAdapter:
    adapter_class = ADAPTERS[adapter_key]
    return adapter_class(base_url)
