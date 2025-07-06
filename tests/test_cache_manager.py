"""Unit tests for the cache manager, using in-memory fakes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from limitless_cli.api.high_level import LimitlessAPI
from limitless_cli.api.transports import InMemoryTransport
from limitless_cli.api.transports.memory import LifelogJSON
from limitless_cli.cache.manager import CacheManager
from limitless_cli.cache.backends import InMemoryCacheBackend, CacheEntry

# --- Test Constants ---
TZ = timezone.utc
EXECUTION_DATE = date(2023, 7, 15)
TODAY = EXECUTION_DATE
YESTERDAY = TODAY - timedelta(days=1)
DAY_BEFORE = TODAY - timedelta(days=2)
TOMORROW = TODAY + timedelta(days=1)

LOG_TODAY: LifelogJSON = {"id": "log_today", "date": TODAY.isoformat(), "title": "Log for Today"}
LOG_YESTERDAY_1: LifelogJSON = {"id": "log_yesterday_1", "date": YESTERDAY.isoformat(), "title": "Log 1"}
LOG_YESTERDAY_2: LifelogJSON = {"id": "log_yesterday_2", "date": YESTERDAY.isoformat(), "title": "Log 2"}
LOG_DAY_BEFORE: LifelogJSON = {"id": "log_day_before", "date": DAY_BEFORE.isoformat(), "title": "Log Day Before"}
LOG_TOMORROW: LifelogJSON = {"id": "log_tomorrow", "date": TOMORROW.isoformat(), "title": "Log Tomorrow"}


# --- Pytest Fixtures ---

@pytest.fixture
def api_transport() -> InMemoryTransport:
    """Provides a fresh, empty in-memory API transport for each test."""
    return InMemoryTransport()

@pytest.fixture
def cache_backend() -> InMemoryCacheBackend:
    """Provides a fresh, empty in-memory cache backend for each test."""
    return InMemoryCacheBackend()

@pytest.fixture
def manager(
    monkeypatch, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
) -> CacheManager:
    """Provides a CacheManager configured with in-memory fakes and a fixed date."""
    
    # Patch datetime.now to return a fixed execution date
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(EXECUTION_DATE, datetime.min.time(), tzinfo=tz or TZ)

    monkeypatch.setattr("limitless_cli.cache.manager.datetime", MockDateTime)

    api = LimitlessAPI(transport=api_transport)
    return CacheManager(api=api, backend=cache_backend, verbose=True)


# --- Test Cases ---

def test_fetch_day_from_api_when_cache_empty(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify it fetches from API if cache is empty and stores the result."""
    api_transport.seed(LOG_YESTERDAY_1)

    # Act
    logs, _ = manager.fetch_day(YESTERDAY, {})

    # Assert
    assert len(logs) == 1
    assert logs[0]["id"] == "log_yesterday_1"
    
    # Verify it was cached
    cached_entry = cache_backend.read(YESTERDAY)
    assert cached_entry is not None
    assert len(cached_entry.logs) == 1
    assert cached_entry.logs[0]["id"] == "log_yesterday_1"

def test_fetch_day_from_cache_when_confirmed(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify it uses the cache for past days if the data is confirmed complete."""
    # Pre-seed the cache with a confirmed entry
    cached_log = {"id": "cached_log", "date": DAY_BEFORE.isoformat()}
    cache_entry = CacheEntry(
        logs=[cached_log],
        data_date=DAY_BEFORE,
        fetched_on_date=DAY_BEFORE,
        confirmed_complete_up_to_date=YESTERDAY  # Confirmed by later data
    )
    cache_backend.write(cache_entry)
    
    # Put different data in the API to ensure it's not called
    api_transport.seed({"id": "api_log", "date": DAY_BEFORE.isoformat()})

    # Act
    logs, _ = manager.fetch_day(DAY_BEFORE, {})
    
    # Assert
    assert len(logs) == 1
    assert logs[0]["id"] == "cached_log"
    assert len(api_transport._lifelogs) > 0 # make sure we seeded the api
    # Check that the API was NOT called by inspecting the transport's request count
    assert api_transport.requests_made == 0


def test_fetch_day_refreshes_today_ignoring_cache(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify it always fetches today's data from the API, even if cached."""
    # Pre-seed the cache with stale data for today
    stale_cached_log = {"id": "stale_cached_log", "date": TODAY.isoformat()}
    cache_backend.write(CacheEntry(logs=[stale_cached_log], data_date=TODAY, fetched_on_date=TODAY))
    
    # Seed the API with fresh data
    api_transport.seed(LOG_TODAY)

    # Act
    logs, _ = manager.fetch_day(TODAY, {})

    # Assert
    assert len(logs) == 1
    assert logs[0]["id"] == "log_today"  # Should be the fresh data from the API

def test_stream_range_fetches_and_caches_multiple_days(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify `stream_range` fetches and caches a range of days correctly."""
    api_transport.seed(LOG_YESTERDAY_1, LOG_YESTERDAY_2, LOG_DAY_BEFORE)

    # Act
    streamed_logs = list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assert
    assert len(streamed_logs) == 3
    assert {log["id"] for log in streamed_logs} == {"log_yesterday_1", "log_yesterday_2", "log_day_before"}

    # Verify both days were cached
    yesterday_entry = cache_backend.read(YESTERDAY)
    day_before_entry = cache_backend.read(DAY_BEFORE)

    assert yesterday_entry is not None
    assert day_before_entry is not None
    assert len(yesterday_entry.logs) == 2
    assert len(day_before_entry.logs) == 1


def test_fetch_future_date_returns_empty(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Future dates should return no logs and skip API/caching when not forced."""
    future_day = TOMORROW

    # Act
    logs, _ = manager.fetch_day(future_day, {})

    # Assert
    assert logs == []
    assert api_transport.requests_made == 0
    assert cache_backend.read(future_day) is None


def test_fetch_future_date_force_cache_returns_cached(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """With --force-cache, cached future data should be returned even though the date is > today."""
    future_day = TOMORROW
    cached_log = {"id": "cached_future", "date": future_day.isoformat()}
    cache_backend.write(
        CacheEntry(logs=[cached_log], data_date=future_day, fetched_on_date=future_day)
    )

    # Act
    logs, _ = manager.fetch_day(future_day, {}, force_cache=True)

    # Assert
    assert len(logs) == 1 and logs[0]["id"] == "cached_future"
    assert api_transport.requests_made == 0


def test_fetch_day_unconfirmed_cache_triggers_refetch(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Past day with unconfirmed cache should be re-fetched from the API."""
    stale_log = {"id": "stale_log", "date": DAY_BEFORE.isoformat()}
    cache_backend.write(
        CacheEntry(logs=[stale_log], data_date=DAY_BEFORE, fetched_on_date=DAY_BEFORE)
    )

    api_transport.seed(LOG_DAY_BEFORE)

    # Act
    logs, _ = manager.fetch_day(DAY_BEFORE, {})

    # Assert – fresh data should replace stale cache
    assert len(logs) == 1 and logs[0]["id"] == "log_day_before"
    # The transport should have recorded at least one request (refetch).
    assert api_transport.requests_made > 0
    updated_entry = cache_backend.read(DAY_BEFORE)
    assert updated_entry is not None and updated_entry.logs[0]["id"] == "log_day_before"


def test_fetch_day_empty_but_confirmed_skips_api(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """An empty but *confirmed* cache entry represents a valid 'no-events' day and should not hit the API."""
    cache_backend.write(
        CacheEntry(
            logs=[],
            data_date=DAY_BEFORE,
            fetched_on_date=DAY_BEFORE,
            confirmed_complete_up_to_date=YESTERDAY,
        )
    )

    api_transport.seed(LOG_DAY_BEFORE)  # Would be fetched if confirmation logic failed

    # Act
    logs, _ = manager.fetch_day(DAY_BEFORE, {})

    # Assert – remains empty and no request made
    assert logs == []
    assert api_transport.requests_made == 0


def test_force_cache_uses_unconfirmed_cache(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """The --force-cache flag should bypass confirmation checks and serve whatever is cached."""
    cached_log = {"id": "stale_unconfirmed", "date": DAY_BEFORE.isoformat()}
    cache_backend.write(
        CacheEntry(logs=[cached_log], data_date=DAY_BEFORE, fetched_on_date=DAY_BEFORE)
    )

    api_transport.seed(LOG_DAY_BEFORE)

    # Act
    logs, _ = manager.fetch_day(DAY_BEFORE, {}, force_cache=True)

    # Assert – stale data returned, API untouched
    assert len(logs) == 1 and logs[0]["id"] == "stale_unconfirmed"
    assert api_transport.requests_made == 0


def test_save_logs_sets_confirmation_based_on_future_data(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """When saving a day, confirmation stamp should point to the latest *later* day with data."""
    # Pre-seed later day (yesterday) with data so it can confirm earlier day
    cache_backend.write(
        CacheEntry(
            logs=[dict(LOG_YESTERDAY_1)],
            data_date=YESTERDAY,
            fetched_on_date=YESTERDAY,
        )
    )

    api_transport.seed(LOG_DAY_BEFORE)

    # Act – fetch earlier day, which should set its confirmation to YESTERDAY
    manager.fetch_day(DAY_BEFORE, {})

    # Assert
    entry = cache_backend.read(DAY_BEFORE)
    assert entry is not None and entry.confirmed_complete_up_to_date == YESTERDAY


def test_stream_range_probe_sets_confirmation_stamps(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Streaming a past-day range with no later cache should trigger the smart probe and stamp confirmations."""
    api_transport.seed(LOG_TODAY, LOG_YESTERDAY_1, LOG_YESTERDAY_2, LOG_DAY_BEFORE)

    # Act
    streamed = list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assertions on streamed content
    assert {lg["id"] for lg in streamed} == {
        "log_day_before",
        "log_yesterday_1",
        "log_yesterday_2",
    }

    # Ensure the relevant days are now cached
    yesterday_entry = cache_backend.read(YESTERDAY)
    day_before_entry = cache_backend.read(DAY_BEFORE)

    assert yesterday_entry is not None and len(yesterday_entry.logs) == 2
    assert day_before_entry is not None and len(day_before_entry.logs) == 1


def test_post_run_upgrades_confirmation_stamps(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """After fetching a range, existing cache files should get updated confirmation stamps."""
    # Pre-seed with old confirmation stamps
    old_stale_log = {"id": "old_stale", "date": DAY_BEFORE.isoformat()}
    cache_backend.write(
        CacheEntry(
            logs=[old_stale_log],
            data_date=DAY_BEFORE,
            fetched_on_date=DAY_BEFORE,
            confirmed_complete_up_to_date=DAY_BEFORE  # Old stamp
        )
    )

    # Seed API with fresh data for the range
    api_transport.seed(LOG_YESTERDAY_1, LOG_YESTERDAY_2, LOG_DAY_BEFORE)

    # Act - fetch range that includes newer data
    list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assert - DAY_BEFORE should have been re-fetched and cached
    updated_entry = cache_backend.read(DAY_BEFORE)
    assert updated_entry is not None
    assert updated_entry.logs[0]["id"] == "log_day_before"  # Fresh data
    assert updated_entry.fetched_on_date == EXECUTION_DATE  # Re-fetched today


def test_legacy_cache_migration(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Legacy cache files (plain arrays) should be re-fetched and upgraded."""
    # Simulate legacy cache by writing a plain list (old format)
    legacy_logs = [{"id": "legacy_log", "date": DAY_BEFORE.isoformat()}]
    # Write legacy format directly to simulate old cache files
    cache_backend._store[DAY_BEFORE] = legacy_logs  # type: ignore

    # Seed API with different data to ensure re-fetch
    api_transport.seed(LOG_DAY_BEFORE)

    # Act - fetch the day with legacy cache
    logs, _ = manager.fetch_day(DAY_BEFORE, {})

    # Assert - should have fetched fresh data and upgraded to new format
    assert len(logs) == 1 and logs[0]["id"] == "log_day_before"
    assert api_transport.requests_made > 0

    # Verify cache was upgraded to new format
    entry = cache_backend.read(DAY_BEFORE)
    assert entry is not None
    assert hasattr(entry, 'confirmed_complete_up_to_date')  # New format
    assert entry.logs[0]["id"] == "log_day_before"  # Fresh data


def test_probe_skipped_when_later_cache_exists(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Probe should be skipped if cache data exists after the range."""
    # Pre-seed cache with data after the range (today)
    cache_backend.write(
        CacheEntry(
            logs=[dict(LOG_TODAY)],
            data_date=TODAY,
            fetched_on_date=TODAY,
            confirmed_complete_up_to_date=TODAY
        )
    )

    # Seed API with data for the range
    api_transport.seed(LOG_YESTERDAY_1, LOG_YESTERDAY_2, LOG_DAY_BEFORE)

    # Act - fetch range that has later cache data
    list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assert - today should not have been probed (no new cache entry)
    today_entry = cache_backend.read(TODAY)
    assert today_entry is not None
    # The existing entry should remain unchanged (no re-fetch)
    assert today_entry.fetched_on_date == TODAY


def test_probe_skipped_for_today_only_range(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Probe should be skipped for ranges that only contain today/future."""
    api_transport.seed(LOG_TODAY)

    # Act - fetch range that only includes today
    list(manager.stream_range(TODAY, TODAY, {}))

    # Assert - no probe should have been performed
    # (Today is always fetched fresh, no probe needed)
    assert cache_backend.read(TODAY) is not None


def test_probe_skipped_with_force_cache(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Probe should be skipped when --force-cache is used."""
    # Pre-seed some cache data
    cache_backend.write(
        CacheEntry(
            logs=[dict(LOG_DAY_BEFORE)],
            data_date=DAY_BEFORE,
            fetched_on_date=DAY_BEFORE
        )
    )

    # Act - fetch range with force_cache
    list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}, force_cache=True))

    # Assert - no probe should have been performed (force_cache bypasses probe logic)
    # The probe would normally cache today, but with force_cache it shouldn't
    today_entry = cache_backend.read(TODAY)
    # Today should not be cached since probe was skipped


def test_confirmation_stamp_uses_global_max(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Confirmation stamps should use the latest date across ALL cache files."""
    # Pre-seed multiple days with different confirmation levels
    cache_backend.write(
        CacheEntry(
            logs=[{"id": "old_log", "date": DAY_BEFORE.isoformat()}],
            data_date=DAY_BEFORE,
            fetched_on_date=DAY_BEFORE,
            confirmed_complete_up_to_date=DAY_BEFORE  # Old stamp
        )
    )
    
    # Add a day with newer confirmation
    cache_backend.write(
        CacheEntry(
            logs=[{"id": "newer_log", "date": YESTERDAY.isoformat()}],
            data_date=YESTERDAY,
            fetched_on_date=YESTERDAY,
            confirmed_complete_up_to_date=YESTERDAY  # Newer stamp
        )
    )

    # Seed API with today's data
    api_transport.seed(LOG_TODAY)

    # Act - fetch today, which should update global max
    manager.fetch_day(TODAY, {})

    # Assert - today should be cached with fresh data
    today_entry = cache_backend.read(TODAY)
    assert today_entry is not None
    assert today_entry.logs[0]["id"] == "log_today"
    assert today_entry.fetched_on_date == EXECUTION_DATE


def test_corrupted_cache_file_handling(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Corrupted cache files should be deleted and re-fetched."""
    # Simulate corrupted cache by writing invalid data that will cause read() to fail
    cache_backend._store[DAY_BEFORE] = "invalid json data"  # type: ignore

    # Seed API with valid data
    api_transport.seed(LOG_DAY_BEFORE)

    # Act - fetch the day with corrupted cache
    logs, _ = manager.fetch_day(DAY_BEFORE, {})

    # Assert - should have fetched fresh data despite corruption
    assert len(logs) == 1 and logs[0]["id"] == "log_day_before"
    assert api_transport.requests_made > 0

    # Verify cache was replaced with valid entry
    entry = cache_backend.read(DAY_BEFORE)
    assert entry is not None
    assert entry.logs[0]["id"] == "log_day_before"


def test_empty_range_handling(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Empty ranges should be handled gracefully."""
    # Act - fetch range with no data
    streamed = list(manager.stream_range(DAY_BEFORE, DAY_BEFORE, {}))

    # Assert - should return empty list without errors
    assert streamed == []


def test_parallel_fetching_behavior(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Parallel fetching should work correctly."""
    api_transport.seed(LOG_YESTERDAY_1, LOG_YESTERDAY_2, LOG_DAY_BEFORE)

    # Act - fetch range with parallel processing
    streamed = list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}, parallel=2))

    # Assert - should get all logs regardless of parallel processing
    assert len(streamed) == 3
    assert {log["id"] for log in streamed} == {"log_day_before", "log_yesterday_1", "log_yesterday_2"}

    # Verify all days were cached
    assert cache_backend.read(DAY_BEFORE) is not None
    assert cache_backend.read(YESTERDAY) is not None


def test_stream_range_returns_in_ascending_order(
    manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify that `direction='asc'` returns logs sorted from oldest to newest."""
    api_transport.seed(LOG_YESTERDAY_1, LOG_DAY_BEFORE, LOG_TODAY)

    # Act
    streamed = list(manager.stream_range(DAY_BEFORE, TODAY, {"direction": "asc"}))

    # Assert
    assert len(streamed) == 3
    assert [log["id"] for log in streamed] == ["log_day_before", "log_yesterday_1", "log_today"]


def test_bulk_fetch_strategy_works_and_caches(
    monkeypatch, manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify that `FETCH_STRATEGY='BULK'` correctly fetches and caches logs."""
    monkeypatch.setattr("limitless_cli.cache.manager.FETCH_STRATEGY", "BULK")
    api_transport.seed(LOG_YESTERDAY_1, LOG_DAY_BEFORE)

    # Act
    streamed = list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assert logs are correct
    assert len(streamed) == 2
    assert {log["id"] for log in streamed} == {"log_day_before", "log_yesterday_1"}

    # Assert that days were cached correctly even in bulk mode
    day_before_entry = cache_backend.read(DAY_BEFORE)
    yesterday_entry = cache_backend.read(YESTERDAY)
    assert day_before_entry is not None and len(day_before_entry.logs) == 1
    assert yesterday_entry is not None and len(yesterday_entry.logs) == 1


def test_hybrid_fetch_strategy_works_and_caches(
    monkeypatch, manager: CacheManager, api_transport: InMemoryTransport, cache_backend: InMemoryCacheBackend
):
    """Verify that `FETCH_STRATEGY='HYBRID'` correctly fetches and caches logs."""
    monkeypatch.setattr("limitless_cli.cache.manager.FETCH_STRATEGY", "HYBRID")

    # Setup: Day before is cached, yesterday is not. Hybrid should fetch yesterday.
    cache_backend.write(CacheEntry(logs=[dict(LOG_DAY_BEFORE)], data_date=DAY_BEFORE, fetched_on_date=DAY_BEFORE, confirmed_complete_up_to_date=YESTERDAY))
    api_transport.seed(LOG_YESTERDAY_1)

    # Act
    streamed = list(manager.stream_range(DAY_BEFORE, YESTERDAY, {}))

    # Assert logs are correct
    assert len(streamed) == 2
    assert {log["id"] for log in streamed} == {"log_day_before", "log_yesterday_1"}

    # Assert that the newly fetched day was cached
    yesterday_entry = cache_backend.read(YESTERDAY)
    assert yesterday_entry is not None and len(yesterday_entry.logs) == 1
