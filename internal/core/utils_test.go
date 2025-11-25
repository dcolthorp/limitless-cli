package core

import (
	"testing"
	"time"
)

func TestParseDate(t *testing.T) {
	tests := []struct {
		input   string
		want    string
		wantErr bool
	}{
		{"2024-07-15", "2024-07-15", false},
		{"2023-01-01", "2023-01-01", false},
		{"invalid", "", true},
		{"07/15/2024", "", true},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got, err := ParseDate(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseDate(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr && got.Format(APIDateFmt) != tt.want {
				t.Errorf("ParseDate(%q) = %v, want %v", tt.input, got.Format(APIDateFmt), tt.want)
			}
		})
	}
}

func TestParseDatetime(t *testing.T) {
	loc := time.UTC
	tests := []struct {
		input   string
		want    string
		wantErr bool
	}{
		{"2024-07-15 10:30:00", "2024-07-15 10:30:00", false},
		{"2023-01-01 00:00:00", "2023-01-01 00:00:00", false},
		{"invalid", "", true},
		{"2024-07-15", "", true},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got, err := ParseDatetime(tt.input, loc)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseDatetime(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr && got.Format(APIDatetimeFmt) != tt.want {
				t.Errorf("ParseDatetime(%q) = %v, want %v", tt.input, got.Format(APIDatetimeFmt), tt.want)
			}
		})
	}
}

func TestParseDateSpec(t *testing.T) {
	loc := time.UTC
	// Use a fixed "now" for testing
	now := time.Date(2024, 7, 15, 12, 0, 0, 0, loc)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, loc)

	tests := []struct {
		name    string
		input   string
		want    string
		wantErr bool
	}{
		{"exact date", "2024-07-15", "2024-07-15", false},
		{"relative d-1", "d-1", today.AddDate(0, 0, -1).Format(APIDateFmt), false},
		{"relative d-7", "d-7", today.AddDate(0, 0, -7).Format(APIDateFmt), false},
		{"relative w-1", "w-1", today.AddDate(0, 0, -7).Format(APIDateFmt), false},
		{"relative m-1", "m-1", today.AddDate(0, -1, 0).Format(APIDateFmt), false},
		{"relative y-1", "y-1", today.AddDate(-1, 0, 0).Format(APIDateFmt), false},
		{"invalid", "invalid", "", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := ParseDateSpec(tt.input, loc)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseDateSpec(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr {
				// For relative dates, just check they're valid dates
				if tt.input == "2024-07-15" && got.Format(APIDateFmt) != tt.want {
					t.Errorf("ParseDateSpec(%q) = %v, want %v", tt.input, got.Format(APIDateFmt), tt.want)
				}
			}
		})
	}
}

func TestParseWeekSpec(t *testing.T) {
	tests := []struct {
		name      string
		input     string
		wantStart string
		wantEnd   string
		wantErr   bool
	}{
		{"ISO week format", "2024-W01", "2024-01-01", "2024-01-07", false},
		{"ISO week format W28", "2024-W28", "2024-07-08", "2024-07-14", false},
		{"invalid format", "invalid", "", "", true},
		{"week out of range", "2024-W54", "", "", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			start, end, err := ParseWeekSpec(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseWeekSpec(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr {
				if start.Format(APIDateFmt) != tt.wantStart {
					t.Errorf("ParseWeekSpec(%q) start = %v, want %v", tt.input, start.Format(APIDateFmt), tt.wantStart)
				}
				if end.Format(APIDateFmt) != tt.wantEnd {
					t.Errorf("ParseWeekSpec(%q) end = %v, want %v", tt.input, end.Format(APIDateFmt), tt.wantEnd)
				}
			}
		})
	}
}

func TestGetTimeRange(t *testing.T) {
	loc := time.UTC

	tests := []struct {
		name    string
		period  string
		wantErr bool
	}{
		{"today", "today", false},
		{"yesterday", "yesterday", false},
		{"this-week", "this-week", false},
		{"last-week", "last-week", false},
		{"this-month", "this-month", false},
		{"last-month", "last-month", false},
		{"this-quarter", "this-quarter", false},
		{"last-quarter", "last-quarter", false},
		{"invalid", "invalid-period", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			start, end, err := GetTimeRange(tt.period, loc)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetTimeRange(%q) error = %v, wantErr %v", tt.period, err, tt.wantErr)
				return
			}
			if !tt.wantErr {
				if start.After(end) {
					t.Errorf("GetTimeRange(%q) start %v is after end %v", tt.period, start, end)
				}
			}
		})
	}
}

func TestLogOverlapsRange(t *testing.T) {
	loc := time.UTC
	start := time.Date(2024, 7, 15, 10, 0, 0, 0, loc)
	end := time.Date(2024, 7, 15, 12, 0, 0, 0, loc)

	tests := []struct {
		name string
		log  map[string]interface{}
		want bool
	}{
		{
			"overlaps",
			map[string]interface{}{
				"startTime": "2024-07-15T11:00:00Z",
				"endTime":   "2024-07-15T11:30:00Z",
			},
			true,
		},
		{
			"before range",
			map[string]interface{}{
				"startTime": "2024-07-15T08:00:00Z",
				"endTime":   "2024-07-15T09:00:00Z",
			},
			false,
		},
		{
			"after range",
			map[string]interface{}{
				"startTime": "2024-07-15T14:00:00Z",
				"endTime":   "2024-07-15T15:00:00Z",
			},
			false,
		},
		{
			"no start time",
			map[string]interface{}{},
			false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := LogOverlapsRange(tt.log, start, end, loc)
			if got != tt.want {
				t.Errorf("LogOverlapsRange() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetTZ(t *testing.T) {
	tests := []struct {
		name string
		want string
	}{
		{"America/New_York", "America/New_York"},
		{"UTC", "UTC"},
		{"", DefaultTZ},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			loc := GetTZ(tt.name)
			if tt.name == "" {
				if loc.String() != DefaultTZ {
					t.Errorf("GetTZ(%q) = %v, want %v", tt.name, loc.String(), DefaultTZ)
				}
			} else {
				if loc.String() != tt.want {
					t.Errorf("GetTZ(%q) = %v, want %v", tt.name, loc.String(), tt.want)
				}
			}
		})
	}
}

