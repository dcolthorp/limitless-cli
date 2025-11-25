package cache

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

func TestFilesystemBackend(t *testing.T) {
	// Create temp directory for test
	tmpDir, err := os.MkdirTemp("", "limitless-cache-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	backend := NewFilesystemBackend(tmpDir)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	confirmedDate := "2024-07-20"

	entry := &CacheEntry{
		Logs:                     []map[string]interface{}{{"id": 1, "title": "Test Log"}},
		DataDate:                 "2024-07-15",
		FetchedOnDate:            "2024-07-15",
		ConfirmedCompleteUpToDate: &confirmedDate,
	}

	// Test write
	if err := backend.Write(entry); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	// Verify file was created
	expectedPath := filepath.Join(tmpDir, "2024", "07", "2024-07-15.json")
	if _, err := os.Stat(expectedPath); os.IsNotExist(err) {
		t.Errorf("Expected file %s to exist", expectedPath)
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
	if readEntry.ConfirmedCompleteUpToDate == nil || *readEntry.ConfirmedCompleteUpToDate != "2024-07-20" {
		t.Error("Expected ConfirmedCompleteUpToDate to be 2024-07-20")
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

	// Test reading non-existent entry
	nonExistentDay, _ := time.Parse(core.APIDateFmt, "2024-07-16")
	if backend.Read(nonExistentDay) != nil {
		t.Error("Expected nil for non-existent entry")
	}
}

func TestFilesystemBackendLegacyFormat(t *testing.T) {
	// Create temp directory for test
	tmpDir, err := os.MkdirTemp("", "limitless-cache-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create legacy format file (just an array)
	legacyPath := filepath.Join(tmpDir, "2024", "07", "2024-07-15.json")
	if err := os.MkdirAll(filepath.Dir(legacyPath), 0755); err != nil {
		t.Fatalf("Failed to create dir: %v", err)
	}
	legacyContent := `[{"id": 1, "title": "Legacy Log"}]`
	if err := os.WriteFile(legacyPath, []byte(legacyContent), 0644); err != nil {
		t.Fatalf("Failed to write legacy file: %v", err)
	}

	backend := NewFilesystemBackend(tmpDir)

	day, _ := time.Parse(core.APIDateFmt, "2024-07-15")
	entry := backend.Read(day)

	if entry == nil {
		t.Fatal("Expected entry to be read from legacy format")
	}
	if len(entry.Logs) != 1 {
		t.Errorf("Expected 1 log, got %d", len(entry.Logs))
	}
	if entry.DataDate != "2024-07-15" {
		t.Errorf("Expected data_date 2024-07-15, got %s", entry.DataDate)
	}
	if entry.ConfirmedCompleteUpToDate != nil {
		t.Error("Expected ConfirmedCompleteUpToDate to be nil for legacy format")
	}
}

func TestFilesystemBackendAtomicWrite(t *testing.T) {
	// Create temp directory for test
	tmpDir, err := os.MkdirTemp("", "limitless-cache-test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	backend := NewFilesystemBackend(tmpDir)

	entry := &CacheEntry{
		Logs:          []map[string]interface{}{{"id": 1}},
		DataDate:      "2024-07-15",
		FetchedOnDate: "2024-07-15",
	}

	// Write entry
	if err := backend.Write(entry); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	// Verify no .tmp file remains
	expectedPath := filepath.Join(tmpDir, "2024", "07", "2024-07-15.json")
	tmpPath := expectedPath + ".tmp"
	if _, err := os.Stat(tmpPath); !os.IsNotExist(err) {
		t.Error("Expected .tmp file to be removed after write")
	}

	// Verify main file exists
	if _, err := os.Stat(expectedPath); os.IsNotExist(err) {
		t.Error("Expected main file to exist")
	}
}

func TestFilesystemBackendPath(t *testing.T) {
	backend := NewFilesystemBackend("/test/cache")

	tests := []struct {
		date     string
		expected string
	}{
		{"2024-07-15", "/test/cache/2024/07/2024-07-15.json"},
		{"2023-01-01", "/test/cache/2023/01/2023-01-01.json"},
		{"2024-12-31", "/test/cache/2024/12/2024-12-31.json"},
	}

	for _, tt := range tests {
		day, _ := time.Parse(core.APIDateFmt, tt.date)
		got := backend.Path(day)
		if got != tt.expected {
			t.Errorf("Path(%s) = %s, want %s", tt.date, got, tt.expected)
		}
	}
}

