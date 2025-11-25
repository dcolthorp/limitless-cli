package cache

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

// FilesystemBackend stores JSON files on disk.
// Directory layout matches the Python CLI: ~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json
type FilesystemBackend struct {
	root      string
	writeLock sync.Mutex
}

// NewFilesystemBackend creates a new filesystem-based cache backend.
func NewFilesystemBackend(root string) *FilesystemBackend {
	if root == "" {
		root = core.CacheRoot()
	}
	return &FilesystemBackend{root: root}
}

// Path returns the filesystem path for the given day.
func (b *FilesystemBackend) Path(day time.Time) string {
	return filepath.Join(
		b.root,
		day.Format("2006"),
		day.Format("01"),
		day.Format("2006-01-02")+".json",
	)
}

// Read returns cached entry for the given day or nil if absent.
func (b *FilesystemBackend) Read(day time.Time) *CacheEntry {
	path := b.Path(day)

	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}

	// Try to parse as new format first
	var payload CacheFilePayload
	if err := json.Unmarshal(data, &payload); err != nil {
		// Try legacy format (just an array)
		var legacyLogs []map[string]interface{}
		if err := json.Unmarshal(data, &legacyLogs); err != nil {
			// Corrupt file, remove it
			os.Remove(path)
			return nil
		}
		// Convert legacy format
		dateStr := day.Format(core.APIDateFmt)
		return &CacheEntry{
			Logs:                     legacyLogs,
			DataDate:                 dateStr,
			FetchedOnDate:            dateStr,
			ConfirmedCompleteUpToDate: nil,
		}
	}

	return &CacheEntry{
		Logs:                     payload.Logs,
		DataDate:                 payload.DataDate,
		FetchedOnDate:            payload.FetchedOnDate,
		ConfirmedCompleteUpToDate: payload.ConfirmedCompleteUpToDate,
	}
}

// Write persists the entry atomically.
func (b *FilesystemBackend) Write(entry *CacheEntry) error {
	day, err := time.Parse(core.APIDateFmt, entry.DataDate)
	if err != nil {
		return err
	}

	path := b.Path(day)

	payload := CacheFilePayload{
		DataDate:                 entry.DataDate,
		FetchedOnDate:            entry.FetchedOnDate,
		Logs:                     entry.Logs,
		ConfirmedCompleteUpToDate: entry.ConfirmedCompleteUpToDate,
	}

	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}

	b.writeLock.Lock()
	defer b.writeLock.Unlock()

	// Ensure directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	// Write to temp file first, then rename (atomic)
	tmpPath := path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return err
	}

	return os.Rename(tmpPath, path)
}

// Scan returns a mapping of dates to their cache status.
func (b *FilesystemBackend) Scan(executionDate time.Time) map[string]CacheScanResult {
	result := make(map[string]CacheScanResult)

	if _, err := os.Stat(b.root); os.IsNotExist(err) {
		return result
	}

	// Walk year directories
	yearDirs, err := os.ReadDir(b.root)
	if err != nil {
		return result
	}

	for _, yearDir := range yearDirs {
		if !yearDir.IsDir() || len(yearDir.Name()) != 4 {
			continue
		}

		yearPath := filepath.Join(b.root, yearDir.Name())
		monthDirs, err := os.ReadDir(yearPath)
		if err != nil {
			continue
		}

		for _, monthDir := range monthDirs {
			if !monthDir.IsDir() || len(monthDir.Name()) != 2 {
				continue
			}

			monthPath := filepath.Join(yearPath, monthDir.Name())
			files, err := os.ReadDir(monthPath)
			if err != nil {
				continue
			}

			for _, file := range files {
				if filepath.Ext(file.Name()) != ".json" {
					continue
				}

				// Parse date from filename
				dateStr := file.Name()[:10] // YYYY-MM-DD
				d, err := time.Parse(core.APIDateFmt, dateStr)
				if err != nil {
					continue
				}

				// Skip future dates
				if d.After(executionDate) {
					continue
				}

				// Read the cache entry
				entry := b.Read(d)
				if entry == nil {
					continue
				}

				var confirmedUpTo *time.Time
				if entry.ConfirmedCompleteUpToDate != nil {
					if t, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate); err == nil {
						confirmedUpTo = &t
					}
				}

				result[dateStr] = CacheScanResult{
					HasLogs:     len(entry.Logs) > 0,
					ConfirmedUpTo: confirmedUpTo,
				}
			}
		}
	}

	return result
}

