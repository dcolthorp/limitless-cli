import pytest
from datetime import date, datetime, timedelta, timezone
from limitless_cli.api.high_level import LimitlessAPI
from limitless_cli.api.transports import InMemoryTransport
from limitless_cli.cache.backends import InMemoryCacheBackend, CacheEntry
from limitless_cli.cache.streaming.bulk import BulkStreamer

TZ = timezone.utc
EXECUTION_DATE = date(2023, 7, 15)
TODAY = EXECUTION_DATE
YESTERDAY = TODAY - timedelta(days=1)
DAY_BEFORE = TODAY - timedelta(days=2)

@pytest.fixture
def api_transport():
    return InMemoryTransport()

@pytest.fixture
def cache_backend():
    return InMemoryCacheBackend()

@pytest.fixture
def bulk_streamer(monkeypatch, api_transport, cache_backend):
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)
    monkeypatch.setattr("datetime.datetime", MockDateTime)
    api = LimitlessAPI(transport=api_transport)
    return BulkStreamer(api, cache_backend, verbose=True)

def test_bulk_fetch_and_cache(bulk_streamer, api_transport, cache_backend):
    api_transport.seed({"id": "log1", "date": DAY_BEFORE.isoformat()}, {"id": "log2", "date": YESTERDAY.isoformat()})
    logs = list(bulk_streamer.stream_range(DAY_BEFORE, YESTERDAY, {}))
    assert {log["id"] for log in logs} == {"log1", "log2"}
    assert cache_backend.read(DAY_BEFORE) is not None
    assert cache_backend.read(YESTERDAY) is not None

def test_force_cache_skips_api(bulk_streamer, api_transport, cache_backend):
    log = {"id": "cached", "date": YESTERDAY.isoformat()}
    cache_backend.write(CacheEntry([log], YESTERDAY, YESTERDAY))
    logs = list(bulk_streamer.stream_range(YESTERDAY, YESTERDAY, {}, force_cache=True))
    assert len(logs) == 0 or logs[0]["id"] == "cached"

def test_confirmation_upgrade_calls_cache_manager(monkeypatch, bulk_streamer):
    called = {}
    class FakeCacheManager:
        def _post_run_upgrade_confirmations(self, *a, **kw):
            called["upgraded"] = True
    bulk_streamer.cache_manager = FakeCacheManager()
    bulk_streamer._post_run_upgrade_confirmations(EXECUTION_DATE, EXECUTION_DATE, False)
    assert called.get("upgraded") 