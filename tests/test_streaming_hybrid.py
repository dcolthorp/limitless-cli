import pytest
from datetime import date, datetime, timedelta, timezone
from limitless_cli.api.high_level import LimitlessAPI
from limitless_cli.api.transports import InMemoryTransport
from limitless_cli.cache.backends import InMemoryCacheBackend, CacheEntry
from limitless_cli.cache.streaming.hybrid import HybridStreamer

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
def hybrid_streamer(monkeypatch, api_transport, cache_backend):
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)
    monkeypatch.setattr("datetime.datetime", MockDateTime)
    api = LimitlessAPI(transport=api_transport)
    return HybridStreamer(api, cache_backend, verbose=True)

def test_hybrid_plan_gap_analysis(hybrid_streamer, cache_backend):
    # Only DAY_BEFORE is missing, others are cached and confirmed
    cache_backend.write(CacheEntry([{"id": "cached", "date": YESTERDAY.isoformat()}], YESTERDAY, YESTERDAY, confirmed_complete_up_to_date=TODAY))
    plan = hybrid_streamer._plan_hybrid_fetch(DAY_BEFORE, YESTERDAY, TODAY, cache_backend.scan(TODAY))
    assert plan and plan[0][0] == DAY_BEFORE

def test_hybrid_delegates_to_bulk_and_daily(monkeypatch, hybrid_streamer, api_transport, cache_backend):
    # Patch sub-strategies to record calls
    called = {"bulk": False, "daily": False}
    class FakeBulk:
        def stream_range(self, *a, **k):
            called["bulk"] = True
            return iter([])
    class FakeDaily:
        def _fetch_day(self, *a, **k):
            called["daily"] = True
            return [], None
    hybrid_streamer.bulk_streamer = FakeBulk()
    hybrid_streamer.daily_streamer = FakeDaily()
    # Simulate a plan with both strategies
    plan = [(DAY_BEFORE, DAY_BEFORE, "daily"), (YESTERDAY, YESTERDAY, "bulk")]
    hybrid_streamer._execute_hybrid_plan(plan, {}, False)
    assert called["bulk"] and called["daily"]

def test_confirmation_upgrade_calls_cache_manager(monkeypatch, hybrid_streamer):
    called = {}
    class FakeCacheManager:
        def _post_run_upgrade_confirmations(self, *a, **kw):
            called["upgraded"] = True
    hybrid_streamer.cache_manager = FakeCacheManager()
    hybrid_streamer._post_run_upgrade_confirmations(EXECUTION_DATE, EXECUTION_DATE, False)
    assert called.get("upgraded") 