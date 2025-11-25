package cli

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

func TestParseDateSpec(t *testing.T) {
	loc := time.UTC

	tests := []struct {
		name    string
		input   string
		want    string
		wantErr bool
	}{
		{"today", "today", time.Now().In(loc).Format(core.APIDateFmt), false},
		{"yesterday", "yesterday", time.Now().In(loc).AddDate(0, 0, -1).Format(core.APIDateFmt), false},
		{"exact date", "2024-07-15", "2024-07-15", false},
		{"invalid", "invalid-date", "", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseDateSpec(tt.input, loc)
			if (err != nil) != tt.wantErr {
				t.Errorf("parseDateSpec(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr && got.Format(core.APIDateFmt) != tt.want {
				t.Errorf("parseDateSpec(%q) = %v, want %v", tt.input, got.Format(core.APIDateFmt), tt.want)
			}
		})
	}
}

func TestFormatLogsForDisplay(t *testing.T) {
	logs := []map[string]interface{}{
		{
			"id":        "test-id",
			"title":     "Test Title",
			"startTime": "2024-07-15T10:00:00Z",
			"endTime":   "2024-07-15T11:00:00Z",
			"markdown":  "# Test Markdown",
			"contents": []interface{}{
				map[string]interface{}{
					"type":    "heading1",
					"content": "First heading content",
				},
			},
		},
	}

	formatted := formatLogsForDisplay(logs)

	if len(formatted) != 1 {
		t.Fatalf("Expected 1 formatted log, got %d", len(formatted))
	}

	log := formatted[0]

	if log["id"] != "test-id" {
		t.Errorf("Expected id 'test-id', got %v", log["id"])
	}
	if log["title"] != "Test Title" {
		t.Errorf("Expected title 'Test Title', got %v", log["title"])
	}
	if log["start_time"] != "2024-07-15T10:00:00Z" {
		t.Errorf("Expected start_time '2024-07-15T10:00:00Z', got %v", log["start_time"])
	}

	summary, ok := log["content_summary"].(map[string]interface{})
	if !ok {
		t.Fatal("Expected content_summary to be a map")
	}
	if summary["sections"] != 1 {
		t.Errorf("Expected 1 section, got %v", summary["sections"])
	}
	if summary["first_section_type"] != "heading1" {
		t.Errorf("Expected first_section_type 'heading1', got %v", summary["first_section_type"])
	}
}

func TestMCPRequestParsing(t *testing.T) {
	// Test initialize request
	initReq := `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`
	var req MCPRequest
	if err := json.Unmarshal([]byte(initReq), &req); err != nil {
		t.Fatalf("Failed to parse initialize request: %v", err)
	}
	if req.Method != "initialize" {
		t.Errorf("Expected method 'initialize', got %s", req.Method)
	}

	// Test tools/list request
	listReq := `{"jsonrpc":"2.0","id":2,"method":"tools/list"}`
	if err := json.Unmarshal([]byte(listReq), &req); err != nil {
		t.Fatalf("Failed to parse tools/list request: %v", err)
	}
	if req.Method != "tools/list" {
		t.Errorf("Expected method 'tools/list', got %s", req.Method)
	}

	// Test tools/call request
	callReq := `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fetch_day","arguments":{"date_spec":"today"}}}`
	if err := json.Unmarshal([]byte(callReq), &req); err != nil {
		t.Fatalf("Failed to parse tools/call request: %v", err)
	}
	if req.Method != "tools/call" {
		t.Errorf("Expected method 'tools/call', got %s", req.Method)
	}
}

func TestFetchDayParamsDefaults(t *testing.T) {
	// Test that defaults are applied correctly
	argsJSON := []byte(`{"date_spec":"today"}`)
	var args FetchDayParams
	if err := json.Unmarshal(argsJSON, &args); err != nil {
		t.Fatalf("Failed to parse args: %v", err)
	}

	if args.DateSpec != "today" {
		t.Errorf("Expected date_spec 'today', got %s", args.DateSpec)
	}
	// Timezone should be empty (will use default)
	if args.Timezone != "" {
		t.Errorf("Expected empty timezone (default), got %s", args.Timezone)
	}
	// Boolean defaults should be false in Go
	if args.IncludeMarkdown != false {
		t.Error("Expected IncludeMarkdown default to be false (Go default)")
	}
}

func TestFetchRangeParamsValidation(t *testing.T) {
	// Test with valid params
	argsJSON := []byte(`{"start_datetime":"2024-07-15 10:00:00","end_datetime":"2024-07-15 12:00:00"}`)
	var args FetchRangeParams
	if err := json.Unmarshal(argsJSON, &args); err != nil {
		t.Fatalf("Failed to parse args: %v", err)
	}

	if args.StartDatetime != "2024-07-15 10:00:00" {
		t.Errorf("Expected start_datetime '2024-07-15 10:00:00', got %s", args.StartDatetime)
	}
	if args.EndDatetime != "2024-07-15 12:00:00" {
		t.Errorf("Expected end_datetime '2024-07-15 12:00:00', got %s", args.EndDatetime)
	}
}

func TestMCPResponseFormat(t *testing.T) {
	// Test successful response
	resp := MCPResponse{
		JSONRPC: "2.0",
		ID:      1,
		Result:  map[string]interface{}{"test": "value"},
	}

	data, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("Failed to marshal response: %v", err)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("Failed to parse response: %v", err)
	}

	if parsed["jsonrpc"] != "2.0" {
		t.Errorf("Expected jsonrpc '2.0', got %v", parsed["jsonrpc"])
	}
	if parsed["id"].(float64) != 1 {
		t.Errorf("Expected id 1, got %v", parsed["id"])
	}
	if parsed["error"] != nil {
		t.Error("Expected no error in success response")
	}

	// Test error response
	errResp := MCPResponse{
		JSONRPC: "2.0",
		ID:      2,
		Error: &MCPError{
			Code:    -32600,
			Message: "Invalid Request",
		},
	}

	data, err = json.Marshal(errResp)
	if err != nil {
		t.Fatalf("Failed to marshal error response: %v", err)
	}

	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	// Result may be present as nil or omitted - check error is present
	errorObj := parsed["error"].(map[string]interface{})
	if errorObj["code"].(float64) != -32600 {
		t.Errorf("Expected error code -32600, got %v", errorObj["code"])
	}
}

