package cache

import (
	"fmt"
	"sort"
	"strconv"
	"sync"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

// streamDaily fetches logs day-by-day.
func (m *Manager) streamDaily(start, end time.Time, common map[string]string, maxResults int, quiet, forceCache bool, parallel int) <-chan map[string]interface{} {
	ch := make(chan map[string]interface{})

	go func() {
		defer close(ch)

		tzName := common["timezone"]
		if tzName == "" {
			tzName = core.DefaultTZ
		}
		loc := core.GetTZ(tzName)
		executionDate := time.Now().In(loc)
		execDateOnly := core.DateOnly(executionDate)

		// Generate list of days to process
		days := make([]time.Time, 0)
		for d := start; !d.After(end); d = d.AddDate(0, 0, 1) {
			dayOnly := core.DateOnly(d)
			if dayOnly.After(execDateOnly) && !forceCache {
				continue
			}
			days = append(days, dayOnly)
		}

		// Process days in reverse chronological order for cache efficiency
		sort.Slice(days, func(i, j int) bool {
			return days[i].After(days[j])
		})

		// Check if we need to probe for completeness
		if !forceCache {
			cacheData := m.scanCacheDirectory(executionDate)
			if m.shouldProbeForCompleteness(days, executionDate, cacheData, forceCache) {
				// Probe the day after the range
				maxDay := days[0]
				probeDay := maxDay.AddDate(0, 0, 1)
				if probeDay.After(execDateOnly) {
					probeDay = execDateOnly
				}
				m.performLatestDataProbe(probeDay, common, executionDate, quiet)
			}
		}

		// Fetch logs for each day
		logsByDay := make(map[string][]map[string]interface{})
		for _, day := range days {
			logs, _ := m.FetchDay(day, common, quiet, forceCache)
			logsByDay[core.FormatDate(day)] = logs
		}

		// Apply post-run confirmation upgrades
		var latestNonEmpty *time.Time
		for dateStr, logs := range logsByDay {
			if len(logs) > 0 {
				d, _ := time.Parse(core.APIDateFmt, dateStr)
				if latestNonEmpty == nil || d.After(*latestNonEmpty) {
					latestNonEmpty = &d
				}
			}
		}
		if latestNonEmpty != nil {
			m.postRunUpgradeConfirmations(*latestNonEmpty, executionDate, quiet)
		}

		// Yield logs in requested order
		direction := common["direction"]
		if direction == "" {
			direction = "desc"
		}

		orderedLogs := m.orderLogsByDirection(logsByDay, direction)

		count := 0
		for _, log := range orderedLogs {
			if maxResults > 0 && count >= maxResults {
				break
			}
			ch <- log
			count++
		}
	}()

	return ch
}

// streamBulk fetches logs in bulk using date range API parameters.
func (m *Manager) streamBulk(start, end time.Time, common map[string]string, maxResults int, quiet, forceCache bool) <-chan map[string]interface{} {
	ch := make(chan map[string]interface{})

	go func() {
		defer close(ch)

		tzName := common["timezone"]
		if tzName == "" {
			tzName = core.DefaultTZ
		}
		loc := core.GetTZ(tzName)
		executionDate := time.Now().In(loc)
		execDateOnly := core.DateOnly(executionDate)

		startOnly := core.DateOnly(start)
		if startOnly.After(execDateOnly) {
			m.log(fmt.Sprintf("Skipping future date range %s > %s", core.FormatDate(start), core.FormatDate(executionDate)))
			return
		}

		effectiveEnd := end
		if core.DateOnly(end).After(execDateOnly) {
			effectiveEnd = execDateOnly
		}

		// Prepare API parameters
		params := make(map[string]string)
		for k, v := range common {
			params[k] = v
		}
		delete(params, "date")
		params["start"] = fmt.Sprintf("%s 00:00:00", core.FormatDate(start))
		params["end"] = fmt.Sprintf("%s 23:59:59", core.FormatDate(effectiveEnd))
		if _, ok := params["limit"]; !ok {
			params["limit"] = strconv.Itoa(core.PageLimit)
		}

		if !quiet {
			core.ProgressPrint(fmt.Sprintf("[Bulk] Fetching %s → %s…", core.FormatDate(start), core.FormatDate(effectiveEnd)), quiet)
		}

		// Fetch logs and group by day
		logsByDay := make(map[string][]map[string]interface{})
		fetched := 0

		for log := range m.api.Paginate("lifelogs", params, maxResults) {
			fetched++

			// Extract date from log
			dateStr := getLogDateStr(log)
			if dateStr == "" {
				continue
			}

			d, err := time.Parse(core.APIDateFmt, dateStr[:10])
			if err != nil {
				continue
			}

			// Filter to requested range
			if d.Before(startOnly) || d.After(core.DateOnly(effectiveEnd)) {
				continue
			}

			dayStr := core.FormatDate(d)
			logsByDay[dayStr] = append(logsByDay[dayStr], log)
		}

		// Cache results by day
		for d := startOnly; !d.After(core.DateOnly(effectiveEnd)); d = d.AddDate(0, 0, 1) {
			if d.After(execDateOnly) {
				continue
			}

			dayStr := core.FormatDate(d)
			dayLogs := logsByDay[dayStr]
			if dayLogs == nil {
				dayLogs = []map[string]interface{}{}
			}
			m.saveLogs(d, dayLogs, execDateOnly, execDateOnly, quiet)
			m.markFetched(d)
		}

		// Apply post-run confirmation upgrades
		var latestNonEmpty *time.Time
		for dateStr, logs := range logsByDay {
			if len(logs) > 0 {
				d, _ := time.Parse(core.APIDateFmt, dateStr)
				if latestNonEmpty == nil || d.After(*latestNonEmpty) {
					latestNonEmpty = &d
				}
			}
		}
		if latestNonEmpty != nil {
			m.postRunUpgradeConfirmations(*latestNonEmpty, executionDate, quiet)
		}

		// Yield logs in requested order
		direction := common["direction"]
		if direction == "" {
			direction = "desc"
		}

		orderedLogs := m.orderLogsByDirection(logsByDay, direction)

		count := 0
		for _, log := range orderedLogs {
			if maxResults > 0 && count >= maxResults {
				break
			}
			ch <- log
			count++
		}
	}()

	return ch
}

// streamHybrid combines daily and bulk strategies based on gap analysis.
func (m *Manager) streamHybrid(start, end time.Time, common map[string]string, maxResults int, quiet, forceCache bool, parallel int) <-chan map[string]interface{} {
	ch := make(chan map[string]interface{})

	go func() {
		defer close(ch)

		tzName := common["timezone"]
		if tzName == "" {
			tzName = core.DefaultTZ
		}
		loc := core.GetTZ(tzName)
		executionDate := time.Now().In(loc)
		execDateOnly := core.DateOnly(executionDate)

		startOnly := core.DateOnly(start)
		if startOnly.After(execDateOnly) {
			m.log(fmt.Sprintf("Skipping future date range %s > %s", core.FormatDate(start), core.FormatDate(executionDate)))
			return
		}

		effectiveEnd := end
		if core.DateOnly(end).After(execDateOnly) {
			effectiveEnd = execDateOnly
		}
		effectiveEndOnly := core.DateOnly(effectiveEnd)

		// Generate list of days for probe check
		days := make([]time.Time, 0)
		for d := startOnly; !d.After(effectiveEndOnly); d = d.AddDate(0, 0, 1) {
			days = append(days, d)
		}

		// Check if we need to probe for completeness before planning
		if !forceCache && len(days) > 0 {
			cacheData := m.scanCacheDirectory(executionDate)
			if m.shouldProbeForCompleteness(days, executionDate, cacheData, forceCache) {
				// Probe the day after the range (up to today)
				maxDay := effectiveEndOnly
				probeDay := maxDay.AddDate(0, 0, 1)
				if probeDay.After(execDateOnly) {
					probeDay = execDateOnly
				}
				if !probeDay.Equal(maxDay) {
					m.performLatestDataProbe(probeDay, common, executionDate, quiet)
				}
			}
		}

		// Plan the hybrid fetch
		plan := m.planHybridFetch(startOnly, effectiveEndOnly, execDateOnly)
		m.log(fmt.Sprintf("Execution plan: %v", plan))

		logsByDay := make(map[string][]map[string]interface{})

		if len(plan) == 0 {
			// No gaps need fetching, use cached data
			m.log("Using cached data only")
			for d := startOnly; !d.After(effectiveEndOnly); d = d.AddDate(0, 0, 1) {
				entry := m.backend.Read(d)
				if entry != nil {
					logsByDay[core.FormatDate(d)] = entry.Logs
				}
			}
		} else {
			// Execute the plan
			m.log(fmt.Sprintf("Executing plan with %d gaps", len(plan)))
			fetchedData := m.executeHybridPlan(plan, common, quiet, parallel)
			for k, v := range fetchedData {
				logsByDay[k] = v
			}

			// Fill in remaining days from cache
			for d := startOnly; !d.After(effectiveEndOnly); d = d.AddDate(0, 0, 1) {
				dayStr := core.FormatDate(d)
				if _, exists := logsByDay[dayStr]; !exists {
					entry := m.backend.Read(d)
					if entry != nil {
						logsByDay[dayStr] = entry.Logs
					}
				}
			}
		}

		// Apply post-run confirmation upgrades
		var latestNonEmpty *time.Time
		for dateStr, logs := range logsByDay {
			if len(logs) > 0 {
				d, _ := time.Parse(core.APIDateFmt, dateStr)
				if latestNonEmpty == nil || d.After(*latestNonEmpty) {
					latestNonEmpty = &d
				}
			}
		}
		if latestNonEmpty != nil {
			m.postRunUpgradeConfirmations(*latestNonEmpty, executionDate, quiet)
		}

		// Yield logs in requested order
		direction := common["direction"]
		if direction == "" {
			direction = "desc"
		}

		orderedLogs := m.orderLogsByDirection(logsByDay, direction)

		count := 0
		for _, log := range orderedLogs {
			if maxResults > 0 && count >= maxResults {
				break
			}
			ch <- log
			count++
		}
	}()

	return ch
}

// Gap represents a date range that needs to be fetched.
type Gap struct {
	Start    time.Time
	End      time.Time
	Strategy string // "bulk" or "daily"
}

// planHybridFetch identifies which sub-ranges require API calls.
func (m *Manager) planHybridFetch(start, end, executionDate time.Time) []Gap {
	// Determine per-day fetch requirements
	needsAPI := make([]time.Time, 0)

	for d := start; !d.After(end) && !d.After(executionDate); d = d.AddDate(0, 0, 1) {
		needs := false

		if d.Equal(executionDate) {
			needs = true // Always refresh today
		} else {
			entry := m.backend.Read(d)
			if entry == nil {
				needs = true // No cache
			} else {
				if entry.ConfirmedCompleteUpToDate == nil {
					needs = true
				} else {
					confirmed, err := time.Parse(core.APIDateFmt, *entry.ConfirmedCompleteUpToDate)
					if err != nil || !confirmed.After(d) {
						needs = true
					}
				}
			}
		}

		if needs {
			needsAPI = append(needsAPI, d)
		}
	}

	if len(needsAPI) == 0 {
		return nil
	}

	// Group consecutive days into gaps
	gaps := make([]Gap, 0)
	gapStart := needsAPI[0]
	gapEnd := gapStart

	for _, day := range needsAPI[1:] {
		if day.Equal(gapEnd.AddDate(0, 0, 1)) {
			gapEnd = day
		} else {
			gaps = append(gaps, Gap{Start: gapStart, End: gapEnd})
			gapStart = day
			gapEnd = day
		}
	}
	gaps = append(gaps, Gap{Start: gapStart, End: gapEnd})

	// Choose strategy for each gap
	totalDays := int(end.Sub(start).Hours()/24) + 1

	for i := range gaps {
		gapDays := int(gaps[i].End.Sub(gaps[i].Start).Hours()/24) + 1
		ratio := float64(gapDays) / float64(totalDays)

		if gapDays >= core.HybridBulkMinDays || ratio >= core.HybridBulkRatio {
			gaps[i].Strategy = "bulk"
		} else {
			gaps[i].Strategy = "daily"
		}
	}

	return gaps
}

// executeHybridPlan executes the hybrid plan by fetching each gap.
func (m *Manager) executeHybridPlan(plan []Gap, common map[string]string, quiet bool, parallel int) map[string][]map[string]interface{} {
	result := make(map[string][]map[string]interface{})
	var mu sync.Mutex

	if parallel <= 0 {
		parallel = core.HybridMaxWorkers
	}

	if len(plan) == 1 {
		// Single gap, execute directly
		gapResult := m.executeGap(plan[0], common, quiet)
		return gapResult
	}

	// Multiple gaps, execute in parallel
	var wg sync.WaitGroup
	semaphore := make(chan struct{}, parallel)

	for _, gap := range plan {
		wg.Add(1)
		go func(g Gap) {
			defer wg.Done()
			semaphore <- struct{}{}
			defer func() { <-semaphore }()

			gapResult := m.executeGap(g, common, quiet)

			mu.Lock()
			for k, v := range gapResult {
				result[k] = v
			}
			mu.Unlock()
		}(gap)
	}

	wg.Wait()
	return result
}

// executeGap executes a single gap using the specified strategy.
func (m *Manager) executeGap(gap Gap, common map[string]string, quiet bool) map[string][]map[string]interface{} {
	result := make(map[string][]map[string]interface{})

	m.log(fmt.Sprintf("Executing gap %s-%s using %s strategy", core.FormatDate(gap.Start), core.FormatDate(gap.End), gap.Strategy))

	if gap.Strategy == "bulk" {
		// Collect logs from bulk stream
		for log := range m.streamBulkInternal(gap.Start, gap.End, common, 0, true) {
			dateStr := getLogDateStr(log)
			if dateStr == "" {
				continue
			}
			d, err := time.Parse(core.APIDateFmt, dateStr[:10])
			if err != nil {
				continue
			}
			dayStr := core.FormatDate(d)
			if !d.Before(gap.Start) && !d.After(gap.End) {
				result[dayStr] = append(result[dayStr], log)
			}
		}

		// Cache results by day after bulk fetch
		tzName := common["timezone"]
		if tzName == "" {
			tzName = core.DefaultTZ
		}
		loc := core.GetTZ(tzName)
		executionDate := time.Now().In(loc)
		execDateOnly := core.DateOnly(executionDate)

		for d := gap.Start; !d.After(gap.End); d = d.AddDate(0, 0, 1) {
			if d.After(execDateOnly) {
				continue
			}
			dayStr := core.FormatDate(d)
			dayLogs := result[dayStr]
			if dayLogs == nil {
				dayLogs = []map[string]interface{}{}
			}
			m.saveLogs(d, dayLogs, execDateOnly, execDateOnly, quiet)
			m.markFetched(d)
		}
	} else {
		// Daily strategy
		for d := gap.Start; !d.After(gap.End); d = d.AddDate(0, 0, 1) {
			logs, _ := m.FetchDay(d, common, true, false)
			result[core.FormatDate(d)] = logs
		}
	}

	return result
}

// streamBulkInternal is an internal bulk fetch that doesn't cache (used by hybrid).
func (m *Manager) streamBulkInternal(start, end time.Time, common map[string]string, maxResults int, quiet bool) <-chan map[string]interface{} {
	ch := make(chan map[string]interface{})

	go func() {
		defer close(ch)

		tzName := common["timezone"]
		if tzName == "" {
			tzName = core.DefaultTZ
		}
		loc := core.GetTZ(tzName)
		executionDate := time.Now().In(loc)
		execDateOnly := core.DateOnly(executionDate)

		effectiveEnd := end
		if core.DateOnly(end).After(execDateOnly) {
			effectiveEnd = execDateOnly
		}

		params := make(map[string]string)
		for k, v := range common {
			params[k] = v
		}
		delete(params, "date")
		params["start"] = fmt.Sprintf("%s 00:00:00", core.FormatDate(start))
		params["end"] = fmt.Sprintf("%s 23:59:59", core.FormatDate(effectiveEnd))
		if _, ok := params["limit"]; !ok {
			params["limit"] = strconv.Itoa(core.PageLimit)
		}

		for log := range m.api.Paginate("lifelogs", params, maxResults) {
			ch <- log
		}
	}()

	return ch
}

// orderLogsByDirection orders logs by the specified direction.
func (m *Manager) orderLogsByDirection(logsByDay map[string][]map[string]interface{}, direction string) []map[string]interface{} {
	// Get sorted date keys
	dates := make([]string, 0, len(logsByDay))
	for dateStr := range logsByDay {
		dates = append(dates, dateStr)
	}

	sort.Slice(dates, func(i, j int) bool {
		if direction == "desc" {
			return dates[i] > dates[j]
		}
		return dates[i] < dates[j]
	})

	// Flatten logs
	result := make([]map[string]interface{}, 0)
	for _, dateStr := range dates {
		result = append(result, logsByDay[dateStr]...)
	}

	return result
}

// getLogDateStr extracts the date string from a log entry.
func getLogDateStr(log map[string]interface{}) string {
	if d, ok := log["date"].(string); ok && d != "" {
		return d
	}
	if d, ok := log["created_at"].(string); ok && d != "" {
		return d
	}
	if d, ok := log["timestamp"].(string); ok && d != "" {
		return d
	}
	if d, ok := log["startTime"].(string); ok && d != "" {
		return d
	}
	return ""
}
