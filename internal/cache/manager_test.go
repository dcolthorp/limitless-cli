package cache

import (
	"testing"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/api"
	"github.com/colthorp/limitless-cli-go/internal/core"
)

func TestManagerFetchDay(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T11:00:00Z"},
	)

	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()
	manager := NewManager(limitlessAPI, backend, false)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	common := map[string]string{
		"timezone": "UTC",
		"limit":    "10",
	}

	logs, _ := manager.FetchDay(day, common, true, false)

	if len(logs) != 2 {
		t.Errorf("Expected 2 logs, got %d", len(logs))
	}

	// Verify cache was written
	entry := backend.Read(day)
	if entry == nil {
		t.Error("Expected cache entry to be written")
	}
	if len(entry.Logs) != 2 {
		t.Errorf("Expected 2 cached logs, got %d", len(entry.Logs))
	}
}

func TestManagerFetchDayFromCache(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()

	// Pre-populate cache with confirmed entry
	confirmedDate := "2024-07-20"
	backend.Seed(&CacheEntry{
		Logs:                     []map[string]interface{}{{"id": 1, "date": "2024-07-15"}},
		DataDate:                 "2024-07-15",
		FetchedOnDate:            "2024-07-15",
		ConfirmedCompleteUpToDate: &confirmedDate,
	})

	manager := NewManager(limitlessAPI, backend, false)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	common := map[string]string{
		"timezone": "UTC",
	}

	logs, _ := manager.FetchDay(day, common, true, false)

	if len(logs) != 1 {
		t.Errorf("Expected 1 log from cache, got %d", len(logs))
	}

	// Verify no API request was made
	if transport.RequestsMade() != 0 {
		t.Errorf("Expected 0 API requests (cache hit), got %d", transport.RequestsMade())
	}
}

func TestManagerForceCacheMode(t *testing.T) {
	transport := api.NewInMemoryTransport(false)
	limitlessAPI := api.NewLimitlessAPI(transport)
	backend := NewMemoryBackend()

	// Pre-populate cache without confirmation (normally would trigger refetch)
	backend.Seed(&CacheEntry{
		Logs:          []map[string]interface{}{{"id": 1, "date": "2024-07-15"}},
		DataDate:      "2024-07-15",
		FetchedOnDate: "2024-07-15",
		// No ConfirmedCompleteUpToDate
	})

	manager := NewManager(limitlessAPI, backend, false)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	common := map[string]string{
		"timezone": "UTC",
	}

	// Force cache mode should use cache even without confirmation
	logs, _ := manager.FetchDay(day, common, true, true)

	if len(logs) != 1 {
		t.Errorf("Expected 1 log from cache, got %d", len(logs))
	}

	// Verify no API request was made
	if transport.RequestsMade() != 0 {
		t.Errorf("Expected 0 API requests (force cache), got %d", transport.RequestsMade())
	}
}

func TestMemoryBackend(t *testing.T) {
	backend := NewMemoryBackend()

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	confirmedDate := "2024-07-20"

	entry := &CacheEntry{
		Logs:                     []map[string]interface{}{{"id": 1}},
		DataDate:                 "2024-07-15",
		FetchedOnDate:            "2024-07-15",
		ConfirmedCompleteUpToDate: &confirmedDate,
	}

	// Test write
	if err := backend.Write(entry); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	// Test read
	readEntry := backend.Read(day)
	if readEntry == nil {
		t.Fatal("Expected entry to be read")
	}
	if len(readEntry.Logs) != 1 {
		t.Errorf("Expected 1 log, got %d", len(readEntry.Logs))
	}
	if readEntry.DataDate != "2024-07-15" {
		t.Errorf("Expected data_date 2024-07-15, got %s", readEntry.DataDate)
	}

	// Test scan
	execDate, _ := time.Parse(core.APIDateFmt, "2024-07-25")
	scanResult := backend.Scan(execDate)
	if len(scanResult) != 1 {
		t.Errorf("Expected 1 scan result, got %d", len(scanResult))
	}
	if result, ok := scanResult["2024-07-15"]; ok {
		if !result.HasLogs {
			t.Error("Expected HasLogs to be true")
		}
		if result.ConfirmedUpTo == nil {
			t.Error("Expected ConfirmedUpTo to be set")
		}
	} else {
		t.Error("Expected scan result for 2024-07-15")
	}
}

func TestStreamDaily(t *testing.T) {
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

	// Verify ascending order
	if len(logs) >= 2 {
		id1 := logs[0]["id"].(int)
		id2 := logs[1]["id"].(int)
		if id1 > id2 {
			t.Error("Expected logs in ascending order")
		}
	}
}

func TestHybridPlanGeneration(t *testing.T) {
	backend := NewMemoryBackend()
	manager := NewManager(nil, backend, false)

	// Pre-populate some cache entries
	confirmedDate := "2024-07-20"
	backend.Seed(
		&CacheEntry{
			Logs:                     []map[string]interface{}{{"id": 1}},
			DataDate:                 "2024-07-14",
			FetchedOnDate:            "2024-07-14",
			ConfirmedCompleteUpToDate: &confirmedDate,
		},
		// 2024-07-15 is missing (gap)
		&CacheEntry{
			Logs:                     []map[string]interface{}{{"id": 2}},
			DataDate:                 "2024-07-16",
			FetchedOnDate:            "2024-07-16",
			ConfirmedCompleteUpToDate: &confirmedDate,
		},
	)

	start, _ := time.Parse(core.APIDateFmt, "2024-07-14")
	end, _ := time.Parse(core.APIDateFmt, "2024-07-16")
	execDate, _ := time.Parse(core.APIDateFmt, "2024-07-20")

	plan := manager.planHybridFetch(start, end, execDate)

	// Should have one gap for 2024-07-15
	if len(plan) != 1 {
		t.Errorf("Expected 1 gap in plan, got %d", len(plan))
	}

	if len(plan) > 0 {
		if core.FormatDate(plan[0].Start) != "2024-07-15" {
			t.Errorf("Expected gap start 2024-07-15, got %s", core.FormatDate(plan[0].Start))
		}
		if plan[0].Strategy != "daily" {
			t.Errorf("Expected daily strategy for single day gap, got %s", plan[0].Strategy)
		}
	}
}

