package api

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// InMemoryTransport is a lightweight simulation of the Limitless lifelogs API.
// Only implements the /lifelogs endpoint sufficient for unit testing cache logic.
type InMemoryTransport struct {
	lifelogs   []map[string]interface{}
	RequestLog []RequestLogEntry
	Verbose    bool
}

// RequestLogEntry records a request made to the transport.
type RequestLogEntry struct {
	Endpoint string
	Params   map[string]string
}

// NewInMemoryTransport creates a new in-memory transport for testing.
func NewInMemoryTransport(verbose bool) *InMemoryTransport {
	return &InMemoryTransport{
		lifelogs:   make([]map[string]interface{}, 0),
		RequestLog: make([]RequestLogEntry, 0),
		Verbose:    verbose,
	}
}

// Seed adds one or more lifelog objects to the in-memory store.
func (t *InMemoryTransport) Seed(logs ...map[string]interface{}) {
	t.lifelogs = append(t.lifelogs, logs...)
}

// RequestsMade returns the number of requests made to this transport.
func (t *InMemoryTransport) RequestsMade() int {
	return len(t.RequestLog)
}

// Reset clears all stored logs and recorded requests.
func (t *InMemoryTransport) Reset() {
	t.lifelogs = make([]map[string]interface{}, 0)
	t.RequestLog = make([]RequestLogEntry, 0)
}

// Request simulates a low-level Limitless API request (lifelogs only).
func (t *InMemoryTransport) Request(endpoint string, params map[string]string) (map[string]interface{}, error) {
	// Track the call for assertions in unit tests
	t.RequestLog = append(t.RequestLog, RequestLogEntry{
		Endpoint: endpoint,
		Params:   copyParams(params),
	})

	if !strings.HasPrefix(endpoint, "lifelogs") {
		return map[string]interface{}{}, nil
	}

	// Copy lifelogs for filtering
	subset := make([]map[string]interface{}, len(t.lifelogs))
	copy(subset, t.lifelogs)

	// Filter by date
	if dateStr, ok := params["date"]; ok && dateStr != "" {
		filtered := make([]map[string]interface{}, 0)
		for _, lg := range subset {
			logDate := getLogDate(lg)
			if logDate[:10] == dateStr {
				filtered = append(filtered, lg)
			}
		}
		subset = filtered
	} else {
		// Filter by start/end
		start := params["start"]
		end := params["end"]
		if start != "" || end != "" {
			filtered := make([]map[string]interface{}, 0)
			sDate := ""
			eDate := ""
			if start != "" {
				sDate = start[:10]
			}
			if end != "" {
				eDate = end[:10]
			}
			for _, lg := range subset {
				logDate := getLogDate(lg)[:10]
				if (sDate == "" || logDate >= sDate) && (eDate == "" || logDate <= eDate) {
					filtered = append(filtered, lg)
				}
			}
			subset = filtered
		}
	}

	// Sort by date
	direction := params["direction"]
	if direction == "" {
		direction = "desc"
	}
	sort.Slice(subset, func(i, j int) bool {
		di := getLogDate(subset[i])
		dj := getLogDate(subset[j])
		if direction == "desc" {
			return di > dj
		}
		return di < dj
	})

	// Pagination
	limit := 3
	if l, ok := params["limit"]; ok && l != "" {
		if parsed, err := strconv.Atoi(l); err == nil {
			limit = parsed
		}
	}

	startIdx := 0
	if cursor, ok := params["cursor"]; ok && cursor != "" {
		if idx, err := strconv.Atoi(cursor); err == nil {
			startIdx = idx
		}
	}

	endIdx := startIdx + limit
	if endIdx > len(subset) {
		endIdx = len(subset)
	}

	page := subset[startIdx:endIdx]

	var nextCursor *string
	if endIdx < len(subset) {
		nc := fmt.Sprintf("%d", endIdx)
		nextCursor = &nc
	}

	return map[string]interface{}{
		"data": map[string]interface{}{
			"lifelogs": toInterfaceSlice(page),
		},
		"meta": map[string]interface{}{
			"lifelogs": map[string]interface{}{
				"nextCursor": nextCursor,
				"count":      len(page),
			},
		},
	}, nil
}

// getLogDate extracts the date string from a log entry.
func getLogDate(lg map[string]interface{}) string {
	if d, ok := lg["date"].(string); ok && d != "" {
		return d
	}
	if d, ok := lg["created_at"].(string); ok && d != "" {
		return d
	}
	if d, ok := lg["startTime"].(string); ok && d != "" {
		return d
	}
	return ""
}

// copyParams creates a copy of the params map.
func copyParams(params map[string]string) map[string]string {
	result := make(map[string]string)
	for k, v := range params {
		result[k] = v
	}
	return result
}

// toInterfaceSlice converts a slice of maps to a slice of interfaces.
func toInterfaceSlice(logs []map[string]interface{}) []interface{} {
	result := make([]interface{}, len(logs))
	for i, lg := range logs {
		result[i] = lg
	}
	return result
}

// MockTransport is an in-memory fake suitable for deterministic unit tests.
type MockTransport struct {
	Fixtures   map[string][]map[string]interface{}
	RequestLog []RequestLogEntry
}

// NewMockTransport creates a new mock transport with the given fixtures.
func NewMockTransport(fixtures map[string][]map[string]interface{}) *MockTransport {
	return &MockTransport{
		Fixtures:   fixtures,
		RequestLog: make([]RequestLogEntry, 0),
	}
}

// Request simulates an API request using fixtures.
func (t *MockTransport) Request(endpoint string, params map[string]string) (map[string]interface{}, error) {
	t.RequestLog = append(t.RequestLog, RequestLogEntry{
		Endpoint: endpoint,
		Params:   copyParams(params),
	})

	pages, ok := t.Fixtures[endpoint]
	if !ok || len(pages) == 0 {
		return map[string]interface{}{
			"data": map[string]interface{}{"lifelogs": []interface{}{}},
			"meta": map[string]interface{}{"lifelogs": map[string]interface{}{"nextCursor": nil}},
		}, nil
	}

	idx := 0
	if cursor, ok := params["cursor"]; ok && cursor != "" {
		if parsed, err := strconv.Atoi(cursor); err == nil {
			idx = parsed
		}
	}

	if idx < len(pages) {
		return pages[idx], nil
	}

	return map[string]interface{}{
		"data": map[string]interface{}{"lifelogs": []interface{}{}},
		"meta": map[string]interface{}{"lifelogs": map[string]interface{}{"nextCursor": nil}},
	}, nil
}

