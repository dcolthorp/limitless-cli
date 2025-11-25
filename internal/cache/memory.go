package cache

import (
	"sync"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

// MemoryBackend is an in-memory cache backend for testing.
type MemoryBackend struct {
	entries map[string]*CacheEntry
	mu      sync.RWMutex
}

// NewMemoryBackend creates a new in-memory cache backend.
func NewMemoryBackend() *MemoryBackend {
	return &MemoryBackend{
		entries: make(map[string]*CacheEntry),
	}
}

// Path returns a dummy path for the given day.
func (b *MemoryBackend) Path(day time.Time) string {
	return day.Format(core.APIDateFmt) + ".json"
}

// Read returns cached entry for the given day or nil if absent.
func (b *MemoryBackend) Read(day time.Time) *CacheEntry {
	b.mu.RLock()
	defer b.mu.RUnlock()

	key := day.Format(core.APIDateFmt)
	if entry, ok := b.entries[key]; ok {
		// Return a copy to prevent mutation
		entryCopy := *entry
		logsCopy := make([]map[string]interface{}, len(entry.Logs))
		copy(logsCopy, entry.Logs)
		entryCopy.Logs = logsCopy
		return &entryCopy
	}
	return nil
}

// Write persists the entry.
func (b *MemoryBackend) Write(entry *CacheEntry) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	// Store a copy
	entryCopy := *entry
	logsCopy := make([]map[string]interface{}, len(entry.Logs))
	copy(logsCopy, entry.Logs)
	entryCopy.Logs = logsCopy

	b.entries[entry.DataDate] = &entryCopy
	return nil
}

// Scan returns a mapping of dates to their cache status.
func (b *MemoryBackend) Scan(executionDate time.Time) map[string]CacheScanResult {
	b.mu.RLock()
	defer b.mu.RUnlock()

	result := make(map[string]CacheScanResult)

	for dateStr, entry := range b.entries {
		d, err := time.Parse(core.APIDateFmt, dateStr)
		if err != nil {
			continue
		}

		if d.After(executionDate) {
			continue
		}

		var confirmedUpTo *time.Time
		if entry.ConfirmedCompleteUpToDate != nil {
			if t, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate); err == nil {
				confirmedUpTo = &t
			}
		}

		result[dateStr] = CacheScanResult{
			HasLogs:       len(entry.Logs) > 0,
			ConfirmedUpTo: confirmedUpTo,
		}
	}

	return result
}

// Reset clears all entries (for testing).
func (b *MemoryBackend) Reset() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.entries = make(map[string]*CacheEntry)
}

// Seed adds entries directly (for testing).
func (b *MemoryBackend) Seed(entries ...*CacheEntry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, entry := range entries {
		entryCopy := *entry
		logsCopy := make([]map[string]interface{}, len(entry.Logs))
		copy(logsCopy, entry.Logs)
		entryCopy.Logs = logsCopy
		b.entries[entry.DataDate] = &entryCopy
	}
}
