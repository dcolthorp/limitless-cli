package cache

import (
	"testing"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/api"
	"github.com/colthorp/limitless-cli-go/internal/core"
)

func TestStreamBulk(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	// Force bulk strategy
	originalStrategy := core.FetchStrategy
	core.FetchStrategy = core.FetchStrategyBulk
	defer func() { core.FetchStrategy = originalStrategy }()

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-16")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "asc",
		"limit":     "10",
	}

	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) != 3 {
		t.Errorf("Expected 3 logs, got %d", len(logs))
	}

	// Verify cache was populated for each day
	for _, dateStr := range []string{"2024-07-14", "2024-07-15", "2024-07-16"} {
		d, _ := time.Parse(core.APIDateFmt, dateStr)
		entry := backend.Read(d)
		if entry == nil {
			t.Errorf("Expected cache entry for %s", dateStr)
		}
	}
}

func TestStreamHybrid(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()

	// Pre-populate some cache entries
	confirmedDate := "2024-07-20"
	backend.Seed(&CacheEntry{
		Logs:                     []map[string]interface{}{{"id": 1, "date": "2024-07-14"}},
		DataDate:                 "2024-07-14",
		FetchedOnDate:            "2024-07-14",
		ConfirmedCompleteUpToDate: &confirmedDate,
	})

	manager := NewManager(limitlessAPI, backend, false)

	// Force hybrid strategy
	originalStrategy := core.FetchStrategy
	core.FetchStrategy = core.FetchStrategyHybrid
	defer func() { core.FetchStrategy = originalStrategy }()

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-16")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "asc",
		"limit":     "10",
	}

	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	// Should have logs from cache (2024-07-14) and API (2024-07-15, 2024-07-16)
	if len(logs) < 1 {
		t.Errorf("Expected at least 1 log, got %d", len(logs))
	}
}

func TestStreamMaxResults(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	for i := 0; i < 10; i++ {
		transport.Seed(map[string]interface{}{
			"id":        i,
			"date":      "2024-07-15",
			"startTime": "2024-07-15T10:00:00Z",
		})
	}

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	start, _ := time.Parse(core.APIDateFmt, "2024-07-15")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "desc",
		"limit":     "10",
	}

	// Limit to 5 results
	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, start, common, 5, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) != 5 {
		t.Errorf("Expected 5 logs (max_results), got %d", len(logs))
	}
}

func TestStreamDirection(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-16")

	// Test descending order
	common := map[string]string{
		"timezone":  "UTC",
		"direction": "desc",
		"limit":     "10",
	}

	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) >= 2 {
		// First log should be from 2024-07-16 (descending)
		firstDate := logs[0]["date"].(string)
		lastDate := logs[len(logs)-1]["date"].(string)
		if firstDate < lastDate {
			t.Error("Expected descending order")
		}
	}

	// Reset backend
	backend.Reset()

	// Test ascending order
	common["direction"] = "asc"

	logs = make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) >= 2 {
		// First log should be from 2024-07-14 (ascending)
		firstDate := logs[0]["date"].(string)
		lastDate := logs[len(logs)-1]["date"].(string)
		if firstDate > lastDate {
			t.Error("Expected ascending order")
		}
	}
}

func TestHybridGapStrategy(t *testing.T) {
	backend := NewMemoryBackend()
	manager := NewManager(nil, backend, false)

	// Test that large gaps use bulk strategy
	start, _ := time.Parse(core.APIDateFmt, "2024-07-01")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-10")
	execDate, _ := time.Parse(core.APIDateFmt, "2024-07-15")

	plan := manager.planHybridFetch(start, end, execDate)

	// Should have one gap covering all 10 days
	if len(plan) != 1 {
		t.Errorf("Expected 1 gap for large range, got %d", len(plan))
	}

	if len(plan) > 0 && plan[0].Strategy != "bulk" {
		t.Errorf("Expected bulk strategy for large gap, got %s", plan[0].Strategy)
	}
}

func TestCacheConfirmationLogic(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()

	// Pre-populate cache WITHOUT confirmation
	backend.Seed(&CacheEntry{
		Logs:          []map[string]interface{}{{"id": 999, "date": "2024-07-15"}},
		DataDate:      "2024-07-15",
		FetchedOnDate: "2024-07-15",
		// No ConfirmedCompleteUpToDate - should trigger refetch
	})

	manager := NewManager(limitlessAPI, backend, false)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	common := map[string]string{
		"timezone": "UTC",
		"limit":    "10",
	}

	// Without force_cache, should refetch because no confirmation
	logs, _ := manager.FetchDay(day, common, true, false)

	// Should have fetched new data (id: 1) not cached data (id: 999)
	if len(logs) == 0 {
		t.Error("Expected logs to be fetched")
	}

	// Verify API was called
	if transport.RequestsMade() == 0 {
		t.Error("Expected API request for unconfirmed cache")
	}
}

// TestHybridBulkGapCachesResults verifies that when hybrid strategy uses bulk
// sub-strategy for a gap, it properly caches the results by day.
// This was a bug where streamBulkInternal didn't cache, causing repeated API calls.
func TestHybridBulkGapCachesResults(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
		map[string]interface{}{"id": 4, "date": "2024-07-17", "startTime": "2024-07-17T10:00:00Z"},
		map[string]interface{}{"id": 5, "date": "2024-07-18", "startTime": "2024-07-18T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	// Force hybrid strategy
	originalStrategy := core.FetchStrategy
	core.FetchStrategy = core.FetchStrategyHybrid
	defer func() { core.FetchStrategy = originalStrategy }()

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-18")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "asc",
		"limit":     "10",
	}

	// First fetch - should hit API
	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) != 5 {
		t.Errorf("Expected 5 logs on first fetch, got %d", len(logs))
	}

	// Verify cache was populated for each day
	for _, dateStr := range []string{"2024-07-14", "2024-07-15", "2024-07-16", "2024-07-17", "2024-07-18"} {
		d, _ := time.Parse(core.APIDateFmt, dateStr)
		entry := backend.Read(d)
		if entry == nil {
			t.Errorf("Expected cache entry for %s after bulk fetch", dateStr)
		} else if len(entry.Logs) == 0 {
			t.Errorf("Expected non-empty logs in cache for %s", dateStr)
		}
	}

	// Reset request counter
	initialRequests := transport.RequestsMade()

	// Add confirmation stamps so cache is considered valid
	// (In real usage, the probe would establish this)
	confirmedDate := "2024-07-20"
	for _, dateStr := range []string{"2024-07-14", "2024-07-15", "2024-07-16", "2024-07-17", "2024-07-18"} {
		d, _ := time.Parse(core.APIDateFmt, dateStr)
		entry := backend.Read(d)
		if entry != nil {
			entry.ConfirmedCompleteUpToDate = &confirmedDate
			backend.Write(entry)
		}
	}

	// Second fetch - should use cache (no new API requests)
	logs = make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(start, end, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) != 5 {
		t.Errorf("Expected 5 logs on second fetch, got %d", len(logs))
	}

	// Verify no new API requests were made (cache was used)
	newRequests := transport.RequestsMade() - initialRequests
	if newRequests > 0 {
		t.Errorf("Expected 0 new API requests on second fetch (cache should be used), got %d", newRequests)
	}
}

// TestHybridSmartProbeEstablishesConfirmation verifies that the hybrid streaming
// strategy performs a smart probe to establish cache confirmation.
// This was a bug where hybrid didn't probe, so cached data was never considered valid.
func TestHybridSmartProbeEstablishesConfirmation(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	// Data for yesterday (2024-07-14)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-14", "startTime": "2024-07-14T11:00:00Z"},
	)
	// Data for today (2024-07-15) - used by probe
	transport.Seed(
		map[string]interface{}{"id": 3, "date": "2024-07-15", "startTime": "2024-07-15T08:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	// Force hybrid strategy
	originalStrategy := core.FetchStrategy
	core.FetchStrategy = core.FetchStrategyHybrid
	defer func() { core.FetchStrategy = originalStrategy }()

	// Request yesterday's data
	yesterday, _ := time.Parse(core.APIDateFmt, "2024-07-14")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "asc",
		"limit":     "10",
	}

	// First fetch
	logs := make([]map[string]interface{}, 0)
	for log := range manager.StreamRange(yesterday, yesterday, common, 0, true, false, 1) {
		logs = append(logs, log)
	}

	if len(logs) != 2 {
		t.Errorf("Expected 2 logs for yesterday, got %d", len(logs))
	}

	// Verify that yesterday's cache entry has a confirmation stamp
	entry := backend.Read(yesterday)
	if entry == nil {
		t.Fatal("Expected cache entry for yesterday")
	}

	// The confirmation stamp should be set (either from probe or post-run upgrade)
	if entry.ConfirmedCompleteUpToDate == nil {
		t.Error("Expected ConfirmedCompleteUpToDate to be set after fetch with probe")
	} else {
		// Confirmation should be >= yesterday (could be today if probe succeeded)
		confirmed, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate)
		if err != nil {
			t.Errorf("Failed to parse confirmation date: %v", err)
		} else if !confirmed.After(yesterday) && !confirmed.Equal(yesterday) {
			t.Errorf("Expected confirmation date >= %s, got %s", 
				core.FormatDate(yesterday), *entry.ConfirmedCompleteUpToDate)
		}
	}
}

// TestExecuteGapBulkCachesAllDays verifies that executeGap with bulk strategy
// caches results for all days in the gap, including days with no logs.
func TestExecuteGapBulkCachesAllDays(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	// Only seed data for some days, leaving gaps
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		// No data for 2024-07-15
		map[string]interface{}{"id": 2, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-16")

	common := map[string]string{
		"timezone":  "UTC",
		"direction": "asc",
	}

	gap := Gap{
		Start:    start,
		End:      end,
		Strategy: "bulk",
	}

	result := manager.executeGap(gap, common, true)

	// Should have entries for all 3 days
	if len(result) < 2 {
		t.Errorf("Expected results for at least 2 days with data, got %d", len(result))
	}

	// Verify cache was created for all days (including empty ones)
	for _, dateStr := range []string{"2024-07-14", "2024-07-15", "2024-07-16"} {
		d, _ := time.Parse(core.APIDateFmt, dateStr)
		entry := backend.Read(d)
		if entry == nil {
			t.Errorf("Expected cache entry for %s (even if empty)", dateStr)
		}
	}

	// Verify 2024-07-15 has empty logs array (not nil)
	day15, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	entry15 := backend.Read(day15)
	if entry15 == nil {
		t.Error("Expected cache entry for 2024-07-15")
	} else if entry15.Logs == nil {
		t.Error("Expected empty logs array for 2024-07-15, got nil")
	} else if len(entry15.Logs) != 0 {
		t.Errorf("Expected 0 logs for 2024-07-15, got %d", len(entry15.Logs))
	}
}

// TestShouldProbeForCompletenessWithoutLaterCache verifies that the probe check
// correctly identifies when a probe is needed (no later cache data exists).
func TestShouldProbeForCompletenessWithoutLaterCache(t *testing.T) {
	backend := NewMemoryBackend()
	manager := NewManager(nil, backend, false)

	yesterday, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	today, _ := time.Parse(core.APIDateFmt, "2024-07-15")

	// No cache exists at all
	cacheData := make(map[string]CacheScanResult)

	days := []time.Time{yesterday}

	// Should need probe because:
	// 1. Yesterday is a past day
	// 2. No cache data exists for dates after yesterday
	shouldProbe := manager.shouldProbeForCompleteness(days, today, cacheData, false)
	if !shouldProbe {
		t.Error("Expected shouldProbeForCompleteness to return true when no later cache exists")
	}

	// Now add cache for today with data
	cacheData["2024-07-15"] = CacheScanResult{
		HasLogs:      true,
		ConfirmedUpTo: &today,
	}

	// Should NOT need probe because later cache with data exists
	shouldProbe = manager.shouldProbeForCompleteness(days, today, cacheData, false)
	if shouldProbe {
		t.Error("Expected shouldProbeForCompleteness to return false when later cache with data exists")
	}
}

// TestCacheValidityRequiresConfirmationAfterDataDate verifies the core caching
// invariant: cache is only valid if confirmed_complete_up_to_date > data_date.
func TestCacheValidityRequiresConfirmationAfterDataDate(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()

	day, _ := time.Parse(core.APIDateFmt, "2024-07-14")

	// Test 1: Cache with confirmation EQUAL to data_date (should NOT be valid)
	sameDate := "2024-07-14"
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 999}},
		DataDate:                  "2024-07-14",
		FetchedOnDate:             "2024-07-14",
		ConfirmedCompleteUpToDate: &sameDate,
	})

	manager := NewManager(limitlessAPI, backend, false)
	common := map[string]string{"timezone": "UTC", "limit": "10"}

	logs, _ := manager.FetchDay(day, common, true, false)

	// Should have refetched (got id: 1, not cached id: 999)
	if len(logs) == 1 {
		if id, ok := logs[0]["id"].(int); ok && id == 999 {
			t.Error("Should have refetched when confirmation == data_date, but used cached data")
		}
	}

	// Reset
	backend.Reset()
	transport.Reset()
	transport.Seed(
		map[string]interface{}{"id": 2, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
	)

	// Test 2: Cache with confirmation AFTER data_date (should be valid)
	laterDate := "2024-07-15"
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 888}},
		DataDate:                  "2024-07-14",
		FetchedOnDate:             "2024-07-14",
		ConfirmedCompleteUpToDate: &laterDate,
	})

	manager = NewManager(limitlessAPI, backend, false)
	requestsBefore := transport.RequestsMade()

	logs, _ = manager.FetchDay(day, common, true, false)

	// Should have used cache (no new API requests)
	if transport.RequestsMade() > requestsBefore {
		t.Error("Should have used cache when confirmation > data_date, but made API request")
	}

	// Should have cached data (id: 888)
	if len(logs) == 1 {
		if id, ok := logs[0]["id"].(int); ok && id != 888 {
			t.Errorf("Expected cached id 888, got %v", id)
		}
	}
}

// TestShouldProbeWithConfirmationEqualToDay verifies that shouldProbeForCompleteness
// correctly returns true when a day's confirmation equals the day itself.
// This is a regression test for a bug where confirmed < day was used instead of confirmed <= day.
func TestShouldProbeWithConfirmationEqualToDay(t *testing.T) {
	backend := NewMemoryBackend()
	manager := NewManager(nil, backend, false)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	today, _ := time.Parse(core.APIDateFmt, "2024-07-15")

	// Cache exists with confirmation == data_date (not valid per caching rules)
	sameDate := "2024-07-14"
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 1}},
		DataDate:                  "2024-07-14",
		FetchedOnDate:             "2024-07-14",
		ConfirmedCompleteUpToDate: &sameDate,
	})

	// Build cache scan result
	cacheData := map[string]CacheScanResult{
		"2024-07-14": {
			HasLogs:       true,
			ConfirmedUpTo: &day, // confirmed == data_date
		},
	}

	days := []time.Time{day}

	// Should probe because confirmation == day is NOT sufficient
	// (we need confirmation > day for cache to be valid)
	shouldProbe := manager.shouldProbeForCompleteness(days, today, cacheData, false)
	if !shouldProbe {
		t.Error("Expected shouldProbeForCompleteness to return true when confirmation == data_date")
	}

	// Now test with confirmation > day (should NOT probe)
	laterDate := "2024-07-15"
	backend.Reset()
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 1}},
		DataDate:                  "2024-07-14",
		FetchedOnDate:             "2024-07-14",
		ConfirmedCompleteUpToDate: &laterDate,
	})

	confirmedTime, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	cacheData = map[string]CacheScanResult{
		"2024-07-14": {
			HasLogs:       true,
			ConfirmedUpTo: &confirmedTime, // confirmed > data_date
		},
	}

	shouldProbe = manager.shouldProbeForCompleteness(days, today, cacheData, false)
	if shouldProbe {
		t.Error("Expected shouldProbeForCompleteness to return false when confirmation > data_date")
	}
}

// TestOptimisticShortCircuitInProbeCheck verifies that the optimistic short-circuit
// in shouldProbeForCompleteness works correctly by checking individual cache entries
// before doing a full cache scan.
func TestOptimisticShortCircuitInProbeCheck(t *testing.T) {
	backend := NewMemoryBackend()
	manager := NewManager(nil, backend, false)

	day1, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	day2, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	today, _ := time.Parse(core.APIDateFmt, "2024-07-20")

	// One day has confirmation beyond the range, one doesn't
	laterDate := "2024-07-18" // Beyond max in range (2024-07-15)
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 1}},
		DataDate:                  "2024-07-14",
		FetchedOnDate:             "2024-07-14",
		ConfirmedCompleteUpToDate: &laterDate,
	})
	backend.Seed(&CacheEntry{
		Logs:                      []map[string]interface{}{{"id": 2}},
		DataDate:                  "2024-07-15",
		FetchedOnDate:             "2024-07-15",
		ConfirmedCompleteUpToDate: nil, // No confirmation
	})

	// Empty cache scan data to simulate not having done the expensive scan
	cacheData := map[string]CacheScanResult{}

	days := []time.Time{day1, day2}

	// Should NOT probe because day1 already has confirmation beyond the range
	// (optimistic short-circuit should kick in)
	shouldProbe := manager.shouldProbeForCompleteness(days, today, cacheData, false)
	if shouldProbe {
		t.Error("Expected optimistic short-circuit to skip probe when one day has confirmation beyond range")
	}
}

