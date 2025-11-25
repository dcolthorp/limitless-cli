package cache

import (
	"fmt"
	"strconv"
	"sync"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/api"
	"github.com/colthorp/limitless-cli-go/internal/core"
)

// Manager orchestrates caching and fetching of lifelogs.
//
// # Features
//
//   - Stores each day's logs in structured JSON files under ~/.limitless/cache/
//   - Adds metadata to guarantee data-completeness checks for historical ranges
//   - Supports three fetch strategies: Daily, Bulk, and Hybrid (default)
//   - Includes "smart probe" that verifies completeness by fetching a single log
//     on the day after a requested range
//   - Thread-safe cache writes and optional multi-threaded retrieval
//
// # Streaming Strategies
//
// Daily (PER_DAY): Fetches logs day-by-day, consulting cache for each day.
// Best for small ranges or when most days are cached.
//
// Bulk (BULK): Fetches logs in bulk using date range API parameters.
// Best for large ranges when most days need fresh data.
//
// Hybrid (HYBRID): Combines daily and bulk based on gap analysis.
// Uses bulk for large consecutive gaps (≥3 days or ≥40% of range).
// Default strategy, best for mixed scenarios.
//
// # Cache Validity
//
// Cache is valid for a past day iff confirmed_complete_up_to_date > data_date.
// Today's data is always re-fetched. Future dates are skipped unless force_cache.
type Manager struct {
	api     *api.LimitlessAPI
	backend Backend
	verbose bool

	// Internal bookkeeping for cache scanning and session tracking
	cacheScanCache map[string]map[string]CacheScanResult // Memoized scan results
	cacheScanLock  sync.Mutex                            // Protects cacheScanCache
	cacheWriteLock sync.Mutex                            // Ensures atomic writes
	fetchedSession map[string]bool                       // Days fetched this session (for post-run upgrades)
	fetchedLock    sync.Mutex                            // Protects fetchedSession
}

// NewManager creates a new cache manager with the given API client and backend.
// If backend is nil, uses the default FilesystemBackend.
// If limitlessAPI is nil, creates a new one with the specified verbosity.
func NewManager(limitlessAPI *api.LimitlessAPI, backend Backend, verbose bool) *Manager {
	if backend == nil {
		backend = NewFilesystemBackend("")
	}
	if limitlessAPI == nil {
		limitlessAPI = api.NewLimitlessAPIWithVerbose(verbose)
	}
	return &Manager{
		api:            limitlessAPI,
		backend:        backend,
		verbose:        verbose,
		cacheScanCache: make(map[string]map[string]CacheScanResult),
		fetchedSession: make(map[string]bool),
	}
}

// log writes a debug message if verbose mode is enabled.
func (m *Manager) log(msg string) {
	core.Eprint(fmt.Sprintf("[Cache] %s", msg), m.verbose)
}

// FetchDay returns logs for the given day, consulting cache when permissible.
//
// Cache lookup rules:
//   - If forceCache: return cached data regardless of confirmation status
//   - If day == today: always fetch from API (today's data may be incomplete)
//   - If day > today: skip (return nil) unless forceCache
//   - If cache exists with confirmed_complete_up_to_date > data_date: use cache
//   - Otherwise: fetch from API and cache the result
//
// Returns the logs and a pointer to the day if logs were found (used for
// determining the "high water mark" for confirmation stamps).
func (m *Manager) FetchDay(day time.Time, common map[string]string, quiet, forceCache bool) ([]map[string]interface{}, *time.Time) {
	tzName := common["timezone"]
	if tzName == "" {
		tzName = core.DefaultTZ
	}
	loc := core.GetTZ(tzName)
	executionDate := time.Now().In(loc)
	execDateOnly := core.DateOnly(executionDate)
	dayOnly := core.DateOnly(day)

	// Skip future dates unless force cache
	if dayOnly.After(execDateOnly) && !forceCache {
		m.log(fmt.Sprintf("Skipping future date %s", core.FormatDate(day)))
		return nil, nil
	}

	var logs []map[string]interface{}
	var maxDateInLogs *time.Time

	// Check cache
	entry := m.backend.Read(day)
	needsFetch := true

	if entry != nil {
		if forceCache {
			logs = entry.Logs
			if len(logs) > 0 {
				maxDateInLogs = &dayOnly
			}
			needsFetch = false
		} else {
			if dayOnly.Equal(execDateOnly) {
				needsFetch = true // Always refresh today
			} else if entry.ConfirmedCompleteUpToDate != nil {
				confirmed, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate)
				if err == nil {
					dataDate, _ := time.Parse(core.APIDateFmt, entry.DataDate)
					if confirmed.After(dataDate) {
						logs = entry.Logs
						if len(logs) > 0 {
							maxDateInLogs = &dayOnly
						}
						needsFetch = false
					}
				}
			}
		}
	} else if forceCache {
		needsFetch = false
	}

	// Fetch from API if needed
	if needsFetch {
		core.ProgressPrint(fmt.Sprintf("Fetching API for %s…", core.FormatDate(day)), quiet)

		params := make(map[string]string)
		for k, v := range common {
			params[k] = v
		}
		params["timezone"] = tzName
		params["date"] = core.FormatDate(day)
		if _, ok := params["limit"]; !ok {
			params["limit"] = strconv.Itoa(core.PageLimit)
		}

		fetchedLogs := make([]map[string]interface{}, 0)
		for log := range m.api.Paginate("lifelogs", params, 0) {
			fetchedLogs = append(fetchedLogs, log)
		}

		logs = fetchedLogs
		if len(logs) > 0 {
			maxDateInLogs = &dayOnly
		}

		m.saveLogs(day, logs, execDateOnly, execDateOnly, quiet)
		m.markFetched(day)
	}

	return logs, maxDateInLogs
}

// StreamRange yields logs over start...end inclusive in requested order.
//
// Delegates to the appropriate streaming strategy based on configuration:
//   - BULK strategy if USE_BULK_RANGE_PAGINATION is set
//   - HYBRID strategy (default) for mixed cache/API scenarios
//   - Daily strategy as fallback or when forceCache is true
//
// The direction parameter in common controls output order (asc/desc).
// Results are capped at maxResults if > 0.
func (m *Manager) StreamRange(start, end time.Time, common map[string]string, maxResults int, quiet, forceCache bool, parallel int) <-chan map[string]interface{} {
	strategy := core.FetchStrategy
	if core.UseBulkRangePagination {
		strategy = core.FetchStrategyBulk
	}

	switch strategy {
	case core.FetchStrategyBulk:
		if !forceCache {
			return m.streamBulk(start, end, common, maxResults, quiet, forceCache)
		}
	case core.FetchStrategyHybrid:
		if !forceCache {
			return m.streamHybrid(start, end, common, maxResults, quiet, forceCache, parallel)
		}
	}

	// Default to daily strategy
	return m.streamDaily(start, end, common, maxResults, quiet, forceCache, parallel)
}

// saveLogs persists logs for a day via the configured backend.
//
// Sets confirmed_complete_up_to_date to the most recent cached date AFTER
// the current day that has data. This creates a "high water mark" that
// validates earlier dates. If no such date exists, the field is nil.
func (m *Manager) saveLogs(day time.Time, logs []map[string]interface{}, fetchedOnDate, executionDate time.Time, quiet bool) {
	confirmed := m.getMaxKnownNonEmptyDataDate(day, executionDate, quiet)

	var confirmedStr *string
	if confirmed != nil {
		s := core.FormatDate(*confirmed)
		confirmedStr = &s
	}

	entry := &CacheEntry{
		Logs:                      logs,
		DataDate:                  core.FormatDate(day),
		FetchedOnDate:             core.FormatDate(fetchedOnDate),
		ConfirmedCompleteUpToDate: confirmedStr,
	}

	m.cacheWriteLock.Lock()
	defer m.cacheWriteLock.Unlock()

	if err := m.backend.Write(entry); err != nil {
		m.log(fmt.Sprintf("Failed to write cache for %s: %v", core.FormatDate(day), err))
	}

	// Clear scan cache
	m.cacheScanLock.Lock()
	m.cacheScanCache = make(map[string]map[string]CacheScanResult)
	m.cacheScanLock.Unlock()
}

// markFetched records that a day was fetched this session.
// Used by postRunUpgradeConfirmations to know which days need stamp upgrades.
func (m *Manager) markFetched(day time.Time) {
	m.fetchedLock.Lock()
	defer m.fetchedLock.Unlock()
	m.fetchedSession[core.FormatDate(day)] = true
}

// scanCacheDirectory returns cache status for all dates <= executionDate.
// Results are memoized per execution date to avoid repeated filesystem scans.
// The scan cache is cleared whenever a new cache entry is written.
func (m *Manager) scanCacheDirectory(executionDate time.Time) map[string]CacheScanResult {
	cacheKey := fmt.Sprintf("scan_%s", core.FormatDate(executionDate))

	m.cacheScanLock.Lock()
	if cached, ok := m.cacheScanCache[cacheKey]; ok {
		m.cacheScanLock.Unlock()
		return cached
	}
	m.cacheScanLock.Unlock()

	result := m.backend.Scan(executionDate)

	m.cacheScanLock.Lock()
	m.cacheScanCache[cacheKey] = result
	m.cacheScanLock.Unlock()

	return result
}

// getGlobalLatestNonEmptyDate returns the latest date with non-empty data.
// This is the "high water mark" used for setting confirmation stamps.
func (m *Manager) getGlobalLatestNonEmptyDate(executionDate time.Time) *time.Time {
	cacheData := m.scanCacheDirectory(executionDate)
	var latest *time.Time

	for dateStr, result := range cacheData {
		if result.HasLogs {
			d, err := time.Parse(core.APIDateFmt, dateStr)
			if err != nil {
				continue
			}
			if latest == nil || d.After(*latest) {
				latest = &d
			}
		}
	}

	return latest
}

// getMaxKnownNonEmptyDataDate returns the most recent cached date AFTER currentDate that has data.
// Used when saving cache entries to set their confirmed_complete_up_to_date field.
// Returns nil if no later date with data exists in cache.
func (m *Manager) getMaxKnownNonEmptyDataDate(currentDate, executionDate time.Time, quiet bool) *time.Time {
	cacheData := m.scanCacheDirectory(executionDate)
	var maxDate *time.Time

	currentDateOnly := core.DateOnly(currentDate)

	for dateStr, result := range cacheData {
		d, err := time.Parse(core.APIDateFmt, dateStr)
		if err != nil {
			continue
		}

		if !d.After(currentDateOnly) {
			continue
		}

		if result.HasLogs {
			if maxDate == nil || d.After(*maxDate) {
				maxDate = &d
			}
		}
	}

	return maxDate
}

// shouldProbeForCompleteness determines if a "smart probe" is needed.
//
// The smart probe fetches one log from the day after the requested range to
// establish a confirmation point. This is needed when:
//   - Not using forceCache
//   - Range contains past days (not just today/future)
//   - No existing cache data for dates AFTER the range has non-empty logs
//   - At least one past day lacks a valid confirmation stamp
//
// Optimization: Includes an optimistic short-circuit that checks if ANY day
// in the range already has confirmation beyond the range, which can skip
// the expensive full cache scan in common cases.
func (m *Manager) shouldProbeForCompleteness(days []time.Time, executionDate time.Time, cacheData map[string]CacheScanResult, forceCache bool) bool {
	if forceCache {
		return false
	}

	execDateOnly := core.DateOnly(executionDate)

	// Check if any day is in the past
	hasPastDay := false
	for _, d := range days {
		if core.DateOnly(d).Before(execDateOnly) {
			hasPastDay = true
			break
		}
	}
	if !hasPastDay {
		return false
	}

	// Find max date in range
	var maxDateInRange time.Time
	for _, d := range days {
		if d.After(maxDateInRange) {
			maxDateInRange = d
		}
	}

	// Optimistic short-circuit: check if any day already has confirmation beyond the range.
	// This can skip the expensive full cache scan in many cases.
	for _, d := range days {
		entry := m.backend.Read(d)
		if entry != nil && entry.ConfirmedCompleteUpToDate != nil {
			confirmed, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate)
			if err == nil && confirmed.After(maxDateInRange) {
				// At least one day already confirms completeness beyond the range
				return false
			}
		}
	}

	// Check if we have later cache with data
	for dateStr, result := range cacheData {
		d, err := time.Parse(core.APIDateFmt, dateStr)
		if err != nil {
			continue
		}
		if d.After(maxDateInRange) && result.HasLogs {
			return false
		}
	}

	// Check if any past day lacks confirmation or has insufficient confirmation
	for _, day := range days {
		dayOnly := core.DateOnly(day)
		if !dayOnly.Before(execDateOnly) {
			continue
		}

		dateStr := core.FormatDate(day)
		result, exists := cacheData[dateStr]
		if !exists {
			return true
		}
		// Cache validity requires: confirmed_complete_up_to_date > data_date
		// So we need to check: confirmedUpTo is nil OR confirmedUpTo <= dayOnly
		if !result.HasLogs || result.ConfirmedUpTo == nil || !result.ConfirmedUpTo.After(dayOnly) {
			return true
		}
	}

	return false
}

// performLatestDataProbe fetches one log from the probe day to establish completeness.
func (m *Manager) performLatestDataProbe(probeDay time.Time, common map[string]string, executionDate time.Time, quiet bool) bool {
	m.log(fmt.Sprintf("Probe for %s…", core.FormatDate(probeDay)))

	params := make(map[string]string)
	for k, v := range common {
		params[k] = v
	}
	params["date"] = core.FormatDate(probeDay)
	params["limit"] = "1"

	probeLogs := make([]map[string]interface{}, 0)
	for log := range m.api.Paginate("lifelogs", params, 1) {
		probeLogs = append(probeLogs, log)
	}

	if len(probeLogs) > 0 {
		m.saveLogs(probeDay, probeLogs, executionDate, executionDate, quiet)
		return true
	}

	return false
}

// postRunUpgradeConfirmations upgrades confirmation stamps for fetched days.
func (m *Manager) postRunUpgradeConfirmations(finalMaxDate, executionDate time.Time, quiet bool) {
	m.fetchedLock.Lock()
	if len(m.fetchedSession) == 0 {
		m.fetchedLock.Unlock()
		return
	}
	fetchedDates := make([]string, 0, len(m.fetchedSession))
	for dateStr := range m.fetchedSession {
		fetchedDates = append(fetchedDates, dateStr)
	}
	m.fetchedLock.Unlock()

	globalLatest := m.getGlobalLatestNonEmptyDate(executionDate)
	effectiveMax := finalMaxDate
	if globalLatest != nil && globalLatest.After(finalMaxDate) {
		effectiveMax = *globalLatest
	}

	for _, dateStr := range fetchedDates {
		d, err := time.Parse(core.APIDateFmt, dateStr)
		if err != nil {
			continue
		}

		if d.Equal(effectiveMax) || d.After(effectiveMax) {
			continue
		}

		entry := m.backend.Read(d)
		if entry == nil {
			continue
		}

		needsUpdate := false
		if entry.ConfirmedCompleteUpToDate == nil {
			needsUpdate = true
		} else {
			confirmed, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate)
			if err != nil || confirmed.Before(effectiveMax) {
				needsUpdate = true
			}
		}

		if needsUpdate {
			effectiveMaxStr := core.FormatDate(effectiveMax)
			entry.ConfirmedCompleteUpToDate = &effectiveMaxStr

			m.cacheWriteLock.Lock()
			if err := m.backend.Write(entry); err != nil {
				m.log(fmt.Sprintf("Failed to upgrade confirmation for %s: %v", dateStr, err))
			} else {
				m.log(fmt.Sprintf("Confirmation upgraded for %s → %s", dateStr, effectiveMaxStr))
			}
			m.cacheWriteLock.Unlock()
		}
	}
}

// GetBackend returns the cache backend (for testing).
func (m *Manager) GetBackend() Backend {
	return m.backend
}
