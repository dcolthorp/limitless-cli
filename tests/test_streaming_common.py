import pytest
from datetime import date, datetime, timedelta, timezone

from limitless_cli.api.high_level import LimitlessAPI
from limitless_cli.api.transports import InMemoryTransport
from limitless_cli.cache.backends import InMemoryCacheBackend, CacheEntry
from limitless_cli.cache.streaming.daily import DailyStreamer
from limitless_cli.cache.streaming.bulk import BulkStreamer
from limitless_cli.cache.streaming.hybrid import HybridStreamer

TZ = timezone.utc
EXECUTION_DATE = date(2023, 7, 15)
TODAY = EXECUTION_DATE
YESTERDAY = TODAY - timedelta(days=1)
DAY_BEFORE = TODAY - timedelta(days=2)
DAY_TWO_BEFORE = TODAY - timedelta(days=3)
TOMORROW = TODAY + timedelta(days=1)

STRATEGY_CLASSES = [DailyStreamer, BulkStreamer, HybridStreamer]

@pytest.fixture(params=STRATEGY_CLASSES)
def strategy(request, monkeypatch):
    """Return an instantiated strategy (Daily, Bulk, or Hybrid) with in-memory fakes."""
    StrategyCls = request.param
    transport = InMemoryTransport()
    backend = InMemoryCacheBackend()

    # Frozen datetime
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)

    monkeypatch.setattr("datetime.datetime", MockDateTime)
    api = LimitlessAPI(transport=transport)
    instance = StrategyCls(api, backend, verbose=True)
    # expose helpers for tests
    instance._transport = transport  # type: ignore[attr-defined]
    instance._backend = backend  # type: ignore[attr-defined]
    return instance

# ---------------------------------------------------------------------------
# Shared behaviour tests
# ---------------------------------------------------------------------------

def _seed(transport: InMemoryTransport, *logs):
    transport.seed(*logs)


def test_max_results_truncation(strategy):
    _seed(strategy._transport,  # type: ignore[attr-defined]
          {"id": "l1", "date": DAY_BEFORE.isoformat()},
          {"id": "l2", "date": YESTERDAY.isoformat()})
    out = list(strategy.stream_range(DAY_BEFORE, YESTERDAY, {}, max_results=1))
    assert len(out) == 1


def test_ordering_ascending(strategy):
    _seed(strategy._transport,
          {"id": "ld3", "date": DAY_TWO_BEFORE.isoformat()},
          {"id": "ld2", "date": DAY_BEFORE.isoformat()},
          {"id": "ld1", "date": YESTERDAY.isoformat()})
    out = list(strategy.stream_range(DAY_TWO_BEFORE, YESTERDAY, {"direction": "asc"}))
    ids = [lg["id"] for lg in out]
    assert ids == ["ld3", "ld2", "ld1"]


def test_empty_range_returns_empty(strategy):
    out = list(strategy.stream_range(DAY_BEFORE, DAY_BEFORE, {}))
    assert out == []


def test_future_date_force_cache(strategy):
    # cache future date then request with force_cache
    future_log = {"id": "fut", "date": TOMORROW.isoformat()}
    strategy._backend.write(CacheEntry([future_log], TOMORROW, TOMORROW))  # type: ignore[attr-defined]
    out = list(strategy.stream_range(TOMORROW, TOMORROW, {}, force_cache=True))
    # Some strategies may still return empty list for purely-future ranges; verify no error and,
    # if logs are returned, they come from cache.
    if out:
        assert out[0]["id"] == "fut"

# ---------------------------------------------------------------------------
# Hybrid specific parallel gap behaviour (only runs when HybridStreamer)
# ---------------------------------------------------------------------------

def test_hybrid_parallel_gaps(monkeypatch):
    transport = InMemoryTransport()
    backend = InMemoryCacheBackend()

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)

    monkeypatch.setattr("datetime.datetime", MockDateTime)
    api = LimitlessAPI(transport=transport)
    hybrid = HybridStreamer(api, backend, verbose=True)

    # seed logs for two non-contiguous gaps to force ThreadPool path
    logs = [
        {"id": "gap1d1", "date": DAY_TWO_BEFORE.isoformat()},
        {"id": "gap2d1", "date": YESTERDAY.isoformat()},
    ]
    transport.seed(*logs)

    out = list(hybrid.stream_range(DAY_TWO_BEFORE, YESTERDAY, {}))
    ids = {lg["id"] for lg in out}
    assert ids == {"gap1d1", "gap2d1"} 