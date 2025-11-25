package api

import (
	"testing"
)

func TestInMemoryTransportPagination(t *testing.T) {
	transport := NewInMemoryTransport(false)

	// Seed with test data
	for i := 0; i < 10; i++ {
		transport.Seed(map[string]interface{}{
			"id":        i,
			"date":      "2024-07-15",
			"startTime": "2024-07-15T10:00:00Z",
		})
	}

	// Test that we can retrieve all items through pagination
	// The InMemoryTransport uses limit=3 by default
	result, err := transport.Request("lifelogs", map[string]string{"date": "2024-07-15", "limit": "3"})
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	data := result["data"].(map[string]interface{})
	lifelogs := data["lifelogs"].([]interface{})
	if len(lifelogs) != 3 {
		t.Errorf("Expected 3 items in first page, got %d", len(lifelogs))
	}

	// Check that nextCursor is set
	meta := result["meta"].(map[string]interface{})
	lifelogMeta := meta["lifelogs"].(map[string]interface{})
	nextCursor := lifelogMeta["nextCursor"]
	if nextCursor == nil {
		t.Error("Expected nextCursor to be set for pagination")
	}
}

func TestInMemoryTransportMaxResults(t *testing.T) {
	transport := NewInMemoryTransport(false)

	// Seed with test data
	for i := 0; i < 10; i++ {
		transport.Seed(map[string]interface{}{
			"id":        i,
			"date":      "2024-07-15",
			"startTime": "2024-07-15T10:00:00Z",
		})
	}

	api := NewLimitlessAPI(transport)

	// Test with max results (limit 10 to get all in one page, then cap at 5)
	count := 0
	for range api.Paginate("lifelogs", map[string]string{"limit": "10", "date": "2024-07-15"}, 5) {
		count++
	}

	if count != 5 {
		t.Errorf("Expected 5 items (max_results), got %d", count)
	}
}

func TestInMemoryTransportDateFiltering(t *testing.T) {
	transport := NewInMemoryTransport(false)

	// Seed with data from different dates
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-15", "startTime": "2024-07-15T11:00:00Z"},
		map[string]interface{}{"id": 4, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
	)

	api := NewLimitlessAPI(transport)

	// Filter by specific date
	count := 0
	for range api.Paginate("lifelogs", map[string]string{"date": "2024-07-15", "limit": "10"}, 0) {
		count++
	}

	if count != 2 {
		t.Errorf("Expected 2 items for 2024-07-15, got %d", count)
	}
}

func TestInMemoryTransportRangeFiltering(t *testing.T) {
	transport := NewInMemoryTransport(false)

	// Seed with data from different dates
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14", "startTime": "2024-07-14T10:00:00Z"},
		map[string]interface{}{"id": 2, "date": "2024-07-15", "startTime": "2024-07-15T10:00:00Z"},
		map[string]interface{}{"id": 3, "date": "2024-07-16", "startTime": "2024-07-16T10:00:00Z"},
		map[string]interface{}{"id": 4, "date": "2024-07-17", "startTime": "2024-07-17T10:00:00Z"},
	)

	api := NewLimitlessAPI(transport)

	// Filter by date range
	count := 0
	for range api.Paginate("lifelogs", map[string]string{
		"start": "2024-07-15 00:00:00",
		"end":   "2024-07-16 23:59:59",
		"limit": "10",
	}, 0) {
		count++
	}

	if count != 2 {
		t.Errorf("Expected 2 items in range, got %d", count)
	}
}

func TestInMemoryTransportDirection(t *testing.T) {
	transport := NewInMemoryTransport(false)

	// Seed with data
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14"},
		map[string]interface{}{"id": 2, "date": "2024-07-15"},
		map[string]interface{}{"id": 3, "date": "2024-07-16"},
	)

	api := NewLimitlessAPI(transport)

	// Test descending order (default)
	var ids []int
	for log := range api.Paginate("lifelogs", map[string]string{"direction": "desc", "limit": "10"}, 0) {
		if id, ok := log["id"].(int); ok {
			ids = append(ids, id)
		}
	}

	if len(ids) != 3 || ids[0] != 3 {
		t.Errorf("Expected descending order starting with 3, got %v", ids)
	}

	// Reset and test ascending
	transport.Reset()
	transport.Seed(
		map[string]interface{}{"id": 1, "date": "2024-07-14"},
		map[string]interface{}{"id": 2, "date": "2024-07-15"},
		map[string]interface{}{"id": 3, "date": "2024-07-16"},
	)

	ids = nil
	for log := range api.Paginate("lifelogs", map[string]string{"direction": "asc", "limit": "10"}, 0) {
		if id, ok := log["id"].(int); ok {
			ids = append(ids, id)
		}
	}

	if len(ids) != 3 || ids[0] != 1 {
		t.Errorf("Expected ascending order starting with 1, got %v", ids)
	}
}

func TestMockTransport(t *testing.T) {
	fixtures := map[string][]map[string]interface{}{
		"lifelogs": {
			{
				"data": map[string]interface{}{
					"lifelogs": []interface{}{
						map[string]interface{}{"id": 1},
						map[string]interface{}{"id": 2},
					},
				},
				"meta": map[string]interface{}{
					"lifelogs": map[string]interface{}{
						"nextCursor": "2",
						"count":      2,
					},
				},
			},
			{
				"data": map[string]interface{}{
					"lifelogs": []interface{}{
						map[string]interface{}{"id": 3},
					},
				},
				"meta": map[string]interface{}{
					"lifelogs": map[string]interface{}{
						"nextCursor": nil,
						"count":      1,
					},
				},
			},
		},
	}

	transport := NewMockTransport(fixtures)

	// First request
	result, err := transport.Request("lifelogs", map[string]string{})
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	data := result["data"].(map[string]interface{})
	lifelogs := data["lifelogs"].([]interface{})
	if len(lifelogs) != 2 {
		t.Errorf("Expected 2 lifelogs in first page, got %d", len(lifelogs))
	}

	// Second request with cursor
	result, err = transport.Request("lifelogs", map[string]string{"cursor": "1"})
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	data = result["data"].(map[string]interface{})
	lifelogs = data["lifelogs"].([]interface{})
	if len(lifelogs) != 1 {
		t.Errorf("Expected 1 lifelog in second page, got %d", len(lifelogs))
	}

	// Verify request log
	if len(transport.RequestLog) != 2 {
		t.Errorf("Expected 2 requests logged, got %d", len(transport.RequestLog))
	}
}

