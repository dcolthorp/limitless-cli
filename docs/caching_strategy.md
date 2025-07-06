###############################################################################

# Caching Strategy (v0.7.0+)

#

# Daily logs are cached in JSON files at ~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json

# with metadata to ensure past day completeness before using cached data.

#

# 1. CORE PROBLEM & RATIONALE:

# The Limitless device syncs to cloud periodically, so past dates may be incomplete

# until newer data confirms the sync point. We need positive evidence of completeness

# before trusting cached historical data, not just absence of errors.

#

# 2. CACHE FILE STRUCTURE:

# Each `~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json` contains:

# • "data_date": Date the logs belong to (string, "YYYY-MM-DD")

# • "fetched_on_date": When cache was written (string, "YYYY-MM-DD")

# • "logs": Array of log entry objects for data_date

# • "confirmed_complete_up_to_date": Latest date with confirmed complete data

# (string "YYYY-MM-DD" or null). This is the KEY field for validation.

#

# 3. CACHE USAGE DECISION LOGIC (when not --force-cache):

# Let execution_date = current script run date, target_day = requested date

#

# IF target_day == execution_date (today):

# → Always re-fetch from API (today's data may be incomplete)

#

# ELSE IF target_day > execution_date (future date):

# → Skip entirely (no API call, return empty); future dates never contain data

# → Exception: if --force-cache, allow returning any existing future cache

#

# ELSE IF target_day < execution_date (past day) AND cache exists:

# IF confirmed_complete_up_to_date > data_date:

# → Use cache (positive evidence of completeness)

# ELSE:

# → Re-fetch from API (no completeness confirmation)

#

# ELSE (no cache):

# → Fetch from API

#

# Note: fetched_on_date is informational only; confirmed_complete_up_to_date

# is the sole determinant of past day cache validity.

#

# • A past day may still be considered _complete_ even when its own "logs"

# array is empty. As long as the file's confirmed_complete_up_to_date is a

# date strictly _after_ data_date, the absence of logs simply means "no

# events occurred that day"—no API refetch is required.

#

# 4. SMART DATA PROBE MECHANISM:

# Problem: When fetching historical ranges, we may lack newer cache data to

# confirm completeness. Solution: Intelligently probe one date after the range.

#

# Probe conditions (ALL must be true):

# • Not using --force-cache

# • No existing cache data for dates AFTER the requested range

# • Range contains past days (not just today/future)

# • At least one past day in range is empty OR lacks confirmation stamp

#

# Probe behavior:

# • Targets date immediately after requested range (but ≤ today)

# • Runs in parallel background thread during main fetches

# • If successful, caches result with proper confirmed_complete_up_to_date

# • Purpose: Establish completeness confirmation point beyond our range

#

# 5. RANGE PROCESSING OPTIMIZATION:

# • Days processed internally in reverse chronological order for cache efficiency

# • Results returned in user-specified direction (asc/desc parameter)

# • Parallel fetching available via ThreadPoolExecutor (--parallel flag)

#

# 6. CONFIRMED_COMPLETE_UP_TO_DATE CALCULATION & POST-RUN FIX-UP:

# When writing new cache, this field = latest date across ALL cache files

# that has non-empty logs. This creates a "high water mark" of confirmed

# complete data that validates earlier dates.

#

# After the script finishes fetching a range it performs a final pass over

# just the cache files it actually fetched during this run. If the overall

# high-water-mark (latest day with data) is newer than a file's existing

# confirmation stamp, that file is re-written so its

# confirmed_complete_up_to_date is bumped forward. This prevents redundant

# re-fetches on the next invocation without unnecessarily touching unrelated

# historical files.

#

# 7. LEGACY CACHE MIGRATION & ONE-TIME RE-VALIDATION:

# Pre-v0.7.0 cache files (plain arrays) are detected and treated as having

# no confirmed_complete_up_to_date field, forcing re-fetch to establish

# proper metadata on first use.

#

# • Any existing cache file that lacks confirmed_complete_up_to_date (or has

# it set to a date < data_date) will be re-fetched once from the API

# • The file is then rewritten with fresh logs and correct confirmation stamp

# • Thereafter it is treated as permanently complete and never re-fetched

# • This ensures older cache files are validated against the current sync state

#

# 8. --FORCE-CACHE BEHAVIOR:

# Bypasses ALL completeness validation and uses any existing cache data,

# regardless of confirmed_complete_up_to_date status. Used for offline access.

###############################################################################
