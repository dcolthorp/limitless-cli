###############################################################################

# Caching Strategy

The Limitless CLI uses a sophisticated caching system to optimize API calls and ensure data completeness for historical lifelog ranges.

## Overview

The caching system stores each day's logs in structured JSON files under `~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json` with metadata to guarantee data-completeness checks. It supports three streaming strategies to balance speed and API efficiency.

## Streaming Strategies

The CLI supports three different strategies for fetching lifelog data over date ranges:

### Daily Strategy (`PER_DAY`)

Fetches logs day-by-day, consulting cache for each individual day.

**Best for:**

- Small date ranges
- When most days are already cached
- When you need precise control over each day's data

**Behavior:**

- Checks cache for each day in the range
- Fetches from API only for days that need fresh data
- Performs "smart probe" to verify completeness when needed
- Always refreshes today's data from API

### Bulk Strategy (`BULK`)

Fetches logs in bulk using date range API parameters, then caches by individual day.

**Best for:**

- Large date ranges
- When most days need fresh data
- When API efficiency is more important than cache efficiency

**Behavior:**

- Makes single API call with start/end date range
- Groups returned logs by day and caches each day separately
- Efficient for ranges with sparse data

### Hybrid Strategy (`HYBRID`) - Default

Combines daily and bulk strategies based on gap analysis.

**Best for:**

- Mixed scenarios where some days are cached and others need fresh data
- Large ranges with sparse data needs
- When you want to balance API efficiency with cache efficiency

**Behavior:**

- Analyzes the requested range to identify gaps that need fresh data
- Uses bulk strategy for large consecutive gaps (≥3 days or ≥40% of range)
- Uses daily strategy for small gaps or individual days
- Executes gaps in parallel when multiple gaps exist

## Configuration

Set the strategy via environment variable or configuration:

```bash
export FETCH_STRATEGY=HYBRID  # Default: HYBRID, PER_DAY, or BULK
```

For backward compatibility, you can also use:

```bash
export USE_BULK_RANGE_PAGINATION=true  # Forces BULK strategy
```

## Cache File Structure

Each cache file contains:

```json
{
  "data_date": "2023-07-15",
  "fetched_on_date": "2023-07-15",
  "logs": [...],
  "confirmed_complete_up_to_date": "2023-07-16"
}
```

- `data_date`: The date the logs belong to
- `fetched_on_date`: When the cache was written
- `logs`: Array of log entries for the date
- `confirmed_complete_up_to_date`: Latest date with confirmed complete data (key for validation)

## Cache Usage Logic

When not using `--force-cache`:

- **Today**: Always re-fetch from API (today's data may be incomplete)
- **Future dates**: Skip entirely (no API call, return empty); exception: if `--force-cache`, allow returning any existing future cache
- **Past dates with confirmed cache**: Use cache if `confirmed_complete_up_to_date > data_date`
- **Past dates without confirmed cache**: Re-fetch from API

**Important nuance**: A past day may still be considered _complete_ even when its own "logs" array is empty. As long as the file's `confirmed_complete_up_to_date` is a date strictly _after_ `data_date`, the absence of logs simply means "no events occurred that day"—no API refetch is required.

**Note**: `fetched_on_date` is informational only; `confirmed_complete_up_to_date` is the sole determinant of past day cache validity.

## Smart Probe Mechanism

**Problem**: When fetching historical ranges, we may lack newer cache data to confirm completeness.

**Solution**: Intelligently probe one date after the range.

**Probe conditions** (ALL must be true):

- Not using `--force-cache`
- No existing cache data for dates AFTER the requested range
- Range contains past days (not just today/future)
- At least one past day in range is empty OR lacks confirmation stamp

**Probe behavior**:

- Targets date immediately after requested range (but ≤ today)
- Runs in parallel background thread during main fetches
- If successful, caches result with proper `confirmed_complete_up_to_date`
- Purpose: Establish completeness confirmation point beyond our range

## Confirmation Stamp Management

**Calculation**: When writing new cache, `confirmed_complete_up_to_date` = latest date across ALL cache files that has non-empty logs. This creates a "high water mark" of confirmed complete data that validates earlier dates.

**Post-run fix-up**: After the script finishes fetching a range, it performs a final pass over just the cache files it actually fetched during this run. If the overall high-water-mark (latest day with data) is newer than a file's existing confirmation stamp, that file is re-written so its `confirmed_complete_up_to_date` is bumped forward.

This prevents redundant re-fetches on the next invocation without unnecessarily touching unrelated historical files.

## Legacy Cache Migration

Pre-v0.7.0 cache files (plain arrays) are detected and treated as having no `confirmed_complete_up_to_date` field, forcing re-fetch to establish proper metadata on first use.

- Any existing cache file that lacks `confirmed_complete_up_to_date` (or has it set to a date < `data_date`) will be re-fetched once from the API
- The file is then rewritten with fresh logs and correct confirmation stamp
- Thereafter it is treated as permanently complete and never re-fetched
- This ensures older cache files are validated against the current sync state

## Force Cache Behavior

The `--force-cache` flag bypasses ALL completeness validation and uses any existing cache data, regardless of confirmation status. Used for offline access.

## Thread Safety

- Cache writes are thread-safe with locks
- The hybrid strategy supports parallel fetching of multiple gaps using a configurable thread pool (default: 3 workers)
- Days are processed internally in reverse chronological order for cache efficiency
- Results are returned in user-specified direction (asc/desc parameter)

###############################################################################
