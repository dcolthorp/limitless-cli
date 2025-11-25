// Package cache provides caching functionality for Limitless lifelog data.
//
// # Overview
//
// The caching system stores each day's logs in structured JSON files under
// ~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json with metadata to guarantee
// data-completeness checks. It supports three streaming strategies to balance
// speed and API efficiency: Daily (PER_DAY), Bulk (BULK), and Hybrid (HYBRID).
//
// # Cache File Structure
//
// Each cache file contains:
//
//	{
//	  "data_date": "2023-07-15",
//	  "fetched_on_date": "2023-07-15",
//	  "logs": [...],
//	  "confirmed_complete_up_to_date": "2023-07-16"
//	}
//
// The key field is confirmed_complete_up_to_date, which determines cache validity.
//
// # Cache Validity Rules
//
// When not using --force-cache:
//   - Today: Always re-fetch from API (today's data may be incomplete)
//   - Future dates: Skip entirely (return empty)
//   - Past dates: Use cache ONLY if confirmed_complete_up_to_date > data_date
//
// Important: A past day may be "complete" even with empty logs. As long as
// confirmed_complete_up_to_date > data_date, the absence of logs means
// "no events occurred that day" - no refetch required.
//
// # Smart Probe Mechanism
//
// Problem: When fetching historical ranges, we may lack newer cache data to
// confirm completeness.
//
// Solution: Probe one date after the requested range. If successful, this
// establishes a confirmation point that validates all earlier dates.
//
// # Confirmation Stamp Management
//
// When writing cache, confirmed_complete_up_to_date = latest date across ALL
// cache files that has non-empty logs. This creates a "high water mark" that
// validates earlier dates.
//
// Post-run fix-up: After fetching, upgrade confirmation stamps for all fetched
// days to point to the new high water mark.
package cache

import (
	"time"
)

// CacheEntry represents one day's cached logs with metadata.
//
// Fields:
//   - Logs: Array of log entries for the date (may be empty for days with no events)
//   - DataDate: The date the logs belong to (YYYY-MM-DD format)
//   - FetchedOnDate: When the cache was written (informational only)
//   - ConfirmedCompleteUpToDate: Latest date with confirmed complete data
//     This is the KEY field for cache validity: cache is valid iff this > DataDate
type CacheEntry struct {
	Logs                      []map[string]interface{} `json:"logs"`
	DataDate                  string                   `json:"data_date"`
	FetchedOnDate             string                   `json:"fetched_on_date"`
	ConfirmedCompleteUpToDate *string                  `json:"confirmed_complete_up_to_date"`
}

// CacheFilePayload is the JSON structure stored in cache files.
// This matches the Python CLI format for cross-compatibility.
type CacheFilePayload struct {
	DataDate                  string                   `json:"data_date"`
	FetchedOnDate             string                   `json:"fetched_on_date"`
	Logs                      []map[string]interface{} `json:"logs"`
	ConfirmedCompleteUpToDate *string                  `json:"confirmed_complete_up_to_date"`
}

// Backend is the interface for cache storage backends.
// The default implementation is FilesystemBackend which stores JSON files on disk.
type Backend interface {
	// Read returns cached entry for the given day or nil if absent.
	// Handles both legacy format (plain array) and current format (with metadata).
	Read(day time.Time) *CacheEntry

	// Write persists the entry atomically using temp file + rename.
	Write(entry *CacheEntry) error

	// Scan returns cache status for all days <= executionDate.
	// Used for determining which days need fetching and for finding
	// the global "high water mark" for confirmation stamps.
	Scan(executionDate time.Time) map[string]CacheScanResult

	// Path returns the filesystem path for the given day (for debugging).
	Path(day time.Time) string
}

// CacheScanResult holds the result of scanning a cache entry.
type CacheScanResult struct {
	HasLogs       bool       // Whether the cache entry has any logs
	ConfirmedUpTo *time.Time // The confirmed_complete_up_to_date value (may be nil)
}

