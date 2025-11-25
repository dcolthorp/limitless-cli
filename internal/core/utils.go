package core

import (
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Eprint writes msg to stderr when verbose is true.
func Eprint(msg string, verbose bool) {
	if verbose {
		fmt.Fprintln(os.Stderr, msg)
	}
}

// ProgressPrint writes msg to stderr unless quiet is true.
func ProgressPrint(msg string, quiet bool) {
	if !quiet {
		fmt.Fprintln(os.Stderr, msg)
	}
}

// GetTZ returns a *time.Location for the given timezone name.
// Falls back to UTC if the timezone is not found.
func GetTZ(name string) *time.Location {
	if name == "" {
		name = DefaultTZ
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: Timezone '%s' not found; falling back to UTC.\n", name)
		return time.UTC
	}
	return loc
}

// GetAPIKey returns the Limitless API key from environment.
// Exits with error if the variable is missing.
func GetAPIKey() string {
	key := os.Getenv(APIKeyEnvVar)
	if key == "" {
		fmt.Fprintf(os.Stderr, "Error: Missing %s\n", APIKeyEnvVar)
		os.Exit(1)
	}
	return key
}

// ParseDate parses a YYYY-MM-DD string into a time.Time (date only, at midnight UTC).
func ParseDate(s string) (time.Time, error) {
	t, err := time.Parse(APIDateFmt, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid date '%s' (expected YYYY-MM-DD)", s)
	}
	return t, nil
}

// ParseDatetime parses a "YYYY-MM-DD HH:MM:SS" string in the given timezone.
func ParseDatetime(s string, loc *time.Location) (time.Time, error) {
	t, err := time.ParseInLocation(APIDatetimeFmt, s, loc)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid datetime '%s' (expected YYYY-MM-DD HH:MM:SS)", s)
	}
	return t, nil
}

// ParseDateSpec returns a concrete date for flexible spec strings.
// Supports:
// 1. Exact YYYY-MM-DD
// 2. M/D or MM/DD (most recent past occurrence)
// 3. Relative forms like d-7 (days), w-2 (weeks), m-3 (months), y-1 (years)
func ParseDateSpec(spec string, loc *time.Location) (time.Time, error) {
	now := time.Now().In(loc)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, loc)

	// 1. YYYY-MM-DD
	if t, err := time.Parse(APIDateFmt, spec); err == nil {
		return t, nil
	}

	// 2. M/D or MM/DD
	mdRegex := regexp.MustCompile(`^(\d{1,2})/(\d{1,2})$`)
	if matches := mdRegex.FindStringSubmatch(spec); matches != nil {
		month, _ := strconv.Atoi(matches[1])
		day, _ := strconv.Atoi(matches[2])
		target := time.Date(now.Year(), time.Month(month), day, 0, 0, 0, 0, loc)
		if target.After(today) {
			target = time.Date(now.Year()-1, time.Month(month), day, 0, 0, 0, 0, loc)
		}
		return target, nil
	}

	// 3. Relative d/w/m/y-N
	relRegex := regexp.MustCompile(`^([dwmy])-(\d+)$`)
	if matches := relRegex.FindStringSubmatch(strings.ToLower(spec)); matches != nil {
		unit := matches[1]
		num, _ := strconv.Atoi(matches[2])

		switch unit {
		case "d":
			return today.AddDate(0, 0, -num), nil
		case "w":
			return today.AddDate(0, 0, -num*7), nil
		case "m":
			return today.AddDate(0, -num, 0), nil
		case "y":
			return today.AddDate(-num, 0, 0), nil
		}
	}

	return time.Time{}, fmt.Errorf("invalid date specification: '%s'", spec)
}

// ParseWeekSpec converts a week spec (N or YYYY-WNN) into (start_date, end_date).
func ParseWeekSpec(spec string) (time.Time, time.Time, error) {
	now := time.Now()
	currentYear := now.Year()

	// 1. Integer week number (assume current year)
	weekNumRegex := regexp.MustCompile(`^\d{1,2}$`)
	if weekNumRegex.MatchString(spec) {
		weekNum, _ := strconv.Atoi(spec)
		if weekNum < 1 || weekNum > 53 {
			return time.Time{}, time.Time{}, fmt.Errorf("week number out of range (1-53)")
		}
		return weekDates(currentYear, weekNum)
	}

	// 2. YYYY-WNN format
	isoWeekRegex := regexp.MustCompile(`^(\d{4})-W(\d{2})$`)
	if matches := isoWeekRegex.FindStringSubmatch(spec); matches != nil {
		year, _ := strconv.Atoi(matches[1])
		weekNum, _ := strconv.Atoi(matches[2])
		if weekNum < 1 || weekNum > 53 {
			return time.Time{}, time.Time{}, fmt.Errorf("week number out of range (1-53) in ISO format")
		}
		return weekDates(year, weekNum)
	}

	return time.Time{}, time.Time{}, fmt.Errorf("invalid week specification format: '%s'", spec)
}

// weekDates returns the start (Monday) and end (Sunday) dates for a given ISO week.
func weekDates(year, week int) (time.Time, time.Time, error) {
	// Find January 4th of the year (always in week 1 per ISO 8601)
	jan4 := time.Date(year, time.January, 4, 0, 0, 0, 0, time.UTC)
	// Find the Monday of that week
	weekday := int(jan4.Weekday())
	if weekday == 0 {
		weekday = 7 // Sunday = 7
	}
	mondayWeek1 := jan4.AddDate(0, 0, -(weekday - 1))
	// Calculate the Monday of the target week
	startDate := mondayWeek1.AddDate(0, 0, (week-1)*7)
	endDate := startDate.AddDate(0, 0, 6)
	return startDate, endDate, nil
}

// GetTimeRange returns (start, end) datetimes representing a period.
// Supported periods: today, yesterday, this-week, last-week, this-month,
// last-month, this-quarter, last-quarter.
func GetTimeRange(period string, loc *time.Location) (time.Time, time.Time, error) {
	now := time.Now().In(loc)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, loc)

	startOfDay := func(t time.Time) time.Time {
		return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, loc)
	}
	endOfDay := func(t time.Time) time.Time {
		return time.Date(t.Year(), t.Month(), t.Day(), 23, 59, 59, 999999999, loc)
	}

	switch period {
	case "today":
		return startOfDay(today), endOfDay(today), nil

	case "yesterday":
		d := today.AddDate(0, 0, -1)
		return startOfDay(d), endOfDay(d), nil

	case "this-week":
		// Week starts on Monday
		weekday := int(today.Weekday())
		if weekday == 0 {
			weekday = 7
		}
		start := today.AddDate(0, 0, -(weekday - 1))
		end := start.AddDate(0, 0, 6)
		return startOfDay(start), endOfDay(end), nil

	case "last-week":
		weekday := int(today.Weekday())
		if weekday == 0 {
			weekday = 7
		}
		startThisWeek := today.AddDate(0, 0, -(weekday - 1))
		start := startThisWeek.AddDate(0, 0, -7)
		end := start.AddDate(0, 0, 6)
		return startOfDay(start), endOfDay(end), nil

	case "this-month":
		first := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, loc)
		last := first.AddDate(0, 1, -1)
		return startOfDay(first), endOfDay(last), nil

	case "last-month":
		first := time.Date(now.Year(), now.Month()-1, 1, 0, 0, 0, 0, loc)
		last := first.AddDate(0, 1, -1)
		return startOfDay(first), endOfDay(last), nil

	case "this-quarter":
		q := (int(now.Month()) - 1) / 3
		firstMonth := time.Month(q*3 + 1)
		first := time.Date(now.Year(), firstMonth, 1, 0, 0, 0, 0, loc)
		last := first.AddDate(0, 3, -1)
		return startOfDay(first), endOfDay(last), nil

	case "last-quarter":
		q := (int(now.Month()) - 1) / 3
		var first time.Time
		if q == 0 {
			first = time.Date(now.Year()-1, time.October, 1, 0, 0, 0, 0, loc)
		} else {
			firstMonth := time.Month((q-1)*3 + 1)
			first = time.Date(now.Year(), firstMonth, 1, 0, 0, 0, 0, loc)
		}
		last := first.AddDate(0, 3, -1)
		return startOfDay(first), endOfDay(last), nil
	}

	return time.Time{}, time.Time{}, fmt.Errorf("unknown period: %s", period)
}

// LogOverlapsRange returns true when log overlaps with the [startDt, endDt] interval.
func LogOverlapsRange(log map[string]interface{}, startDt, endDt time.Time, loc *time.Location) bool {
	startStr := ""
	if v, ok := log["startTime"].(string); ok {
		startStr = v
	} else if v, ok := log["start_time"].(string); ok {
		startStr = v
	}

	if startStr == "" {
		return false
	}

	logStart, err := time.Parse(time.RFC3339, startStr)
	if err != nil {
		// Try parsing without timezone
		logStart, err = time.ParseInLocation("2006-01-02T15:04:05", startStr, loc)
		if err != nil {
			return false
		}
	}

	endStr := ""
	if v, ok := log["endTime"].(string); ok {
		endStr = v
	} else if v, ok := log["end_time"].(string); ok {
		endStr = v
	}

	var logEnd time.Time
	if endStr != "" {
		logEnd, err = time.Parse(time.RFC3339, endStr)
		if err != nil {
			logEnd, err = time.ParseInLocation("2006-01-02T15:04:05", endStr, loc)
			if err != nil {
				logEnd = logStart
			}
		}
	} else {
		logEnd = logStart
	}

	return !logStart.After(endDt) && !logEnd.Before(startDt)
}

// DateOnly returns a time.Time with only the date portion (midnight UTC).
func DateOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// FormatDate formats a time.Time as YYYY-MM-DD.
func FormatDate(t time.Time) string {
	return t.Format(APIDateFmt)
}

// FormatDatetime formats a time.Time as YYYY-MM-DD HH:MM:SS.
func FormatDatetime(t time.Time) string {
	return t.Format(APIDatetimeFmt)
}

