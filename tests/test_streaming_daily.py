import pytest
from datetime import date, datetime, timedelta, timezone
from limitless_cli.api.high_level import LimitlessAPI
from limitless_cli.api.transports import InMemoryTransport
from limitless_cli.cache.backends import InMemoryCacheBackend, CacheEntry
from limitless_cli.cache.streaming.daily import DailyStreamer

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
def daily_streamer(monkeypatch, api_transport, cache_backend):
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)
    monkeypatch.setattr("datetime.datetime", MockDateTime)
    api = LimitlessAPI(transport=api_transport)
    return DailyStreamer(api, cache_backend, verbose=True)

def test_per_day_cache_hit(daily_streamer, api_transport, cache_backend):
    log = {"id": "cached", "date": YESTERDAY.isoformat()}
    cache_backend.write(CacheEntry([log], YESTERDAY, YESTERDAY, confirmed_complete_up_to_date=TODAY))
    logs = list(daily_streamer.stream_range(YESTERDAY, YESTERDAY, {}))
    assert len(logs) == 1 and logs[0]["id"] == "cached"
    assert api_transport.requests_made == 0

def test_per_day_cache_miss_fetches_api(daily_streamer, api_transport, cache_backend):
    api_transport.seed({"id": "api_log", "date": YESTERDAY.isoformat()})
    logs = list(daily_streamer.stream_range(YESTERDAY, YESTERDAY, {}))
    assert len(logs) == 1 and logs[0]["id"] == "api_log"
    assert api_transport.requests_made > 0

def test_force_cache_returns_stale(daily_streamer, api_transport, cache_backend):
    log = {"id": "stale", "date": YESTERDAY.isoformat()}
    cache_backend.write(CacheEntry([log], YESTERDAY, YESTERDAY))
    api_transport.seed({"id": "api_log", "date": YESTERDAY.isoformat()})
    logs = list(daily_streamer.stream_range(YESTERDAY, YESTERDAY, {}, force_cache=True))
    assert len(logs) == 1 and logs[0]["id"] == "stale"
    assert api_transport.requests_made == 0

def test_probe_logic_triggers_probe(monkeypatch, daily_streamer, api_transport, cache_backend):
    # No cache for today, so probe should run for tomorrow
    api_transport.seed({"id": "probe_log", "date": TODAY.isoformat()})
    called = []
    def fake_save_logs(day, logs, fetched_on, execution_date, quiet):
        called.append(day)
    monkeypatch.setattr(daily_streamer, "_save_logs", fake_save_logs)
    list(daily_streamer.stream_range(DAY_BEFORE, YESTERDAY, {}))
    assert TODAY in called

def test_confirmation_upgrade_calls_cache_manager(monkeypatch, daily_streamer):
    called = {}
    class FakeCacheManager:
        def _post_run_upgrade_confirmations(self, *a, **kw):
            called["upgraded"] = True
    daily_streamer.cache_manager = FakeCacheManager()
    daily_streamer._post_run_upgrade_confirmations(EXECUTION_DATE, EXECUTION_DATE, False)
    assert called.get("upgraded") 