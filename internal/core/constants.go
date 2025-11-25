// Package core provides shared constants and configuration for the Limitless CLI.
package core

import (
	"os"
	"path/filepath"
)

// API configuration
const (
	APIBaseURL   = "https://api.limitless.ai"
	APIVersion   = "v1"
	APIKeyEnvVar = "LIMITLESS_API_KEY"
	DefaultTZ    = "America/Detroit"
)

// Date formats
const (
	APIDateFmt     = "2006-01-02"
	APIDatetimeFmt = "2006-01-02 15:04:05"
)

// Pagination
const (
	PageLimit = 10
)

// Fetch strategy defaults
const (
	FetchStrategyHybrid = "HYBRID"
	FetchStrategyPerDay = "PER_DAY"
	FetchStrategyBulk   = "BULK"
)

// Default fetch strategy
var FetchStrategy = FetchStrategyHybrid

// Hybrid strategy thresholds
const (
	HybridBulkMinDays = 3   // Min consecutive days to warrant bulk fetch
	HybridBulkRatio   = 0.4 // Min ratio of range to warrant bulk fetch
	HybridMaxWorkers  = 3   // Max parallel workers for hybrid gaps
)

// Backward compatibility flags
var UseBulkRangePagination = false

func init() {
	// Override defaults from environment variables
	if strategy := os.Getenv("FETCH_STRATEGY"); strategy != "" {
		FetchStrategy = strategy
	}
	if val := os.Getenv("USE_BULK_RANGE_PAGINATION"); val == "true" || val == "1" {
		UseBulkRangePagination = true
	}
}

// CacheRoot returns the default cache directory path.
func CacheRoot() string {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return filepath.Join(home, ".limitless", "cache")
}

// Version is the current CLI version.
const Version = "0.7.0"

