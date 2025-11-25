# Limitless CLI (Go)

A command-line utility for interacting with data from your Limitless AI device, written in Go.

This is a complete port of the [Python Limitless CLI](../limitless-cli) with identical behavior, CLI flags, caching semantics, and MCP server functionality.

## Features

- **Robust Caching**: Intelligently caches daily logs to minimize API calls while ensuring data is complete and up-to-date. Uses the same cache format and directory structure as the Python CLI (`~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json`).
- **Flexible Queries**: Fetch data for a single day, a specific week, a date range, or using relative periods like `today`, `last-week`, or `this-month`.
- **Multiple Fetch Strategies**: Supports three streaming strategies (Daily, Bulk, Hybrid) to optimize for different scenarios. The default Hybrid strategy automatically analyzes gaps and uses the most efficient approach.
- **Multiple Output Formats**: View data as clean, readable markdown or as raw JSON for piping to other tools.
- **AI Integration**: Built-in MCP (Model Context Protocol) server for seamless integration with AI assistants like Claude, Cursor, and other MCP-compatible tools.

## Installation

### From Source

```sh
# Clone the repository
git clone https://github.com/colthorp/limitless-cli-go.git
cd limitless-cli-go

# Build the binary
make build

# Or install directly to $GOPATH/bin
make install
```

### Pre-built Binaries

Build for multiple platforms:

```sh
make build-all
```

This creates binaries in `bin/` for:
- macOS (amd64, arm64)
- Linux (amd64, arm64)
- Windows (amd64)

## Configuration

Set your Limitless API key as an environment variable:

```sh
export LIMITLESS_API_KEY="YOUR_API_KEY_HERE"
```

Add this to your shell profile (e.g., `~/.zshrc`, `~/.bash_profile`) to make it permanent.

## Usage

```sh
limitless <command> [options]
```

### Get Help

```sh
limitless --help
limitless <command> --help
```

### Basic Examples

**Get logs for today:**

```sh
limitless today
```

**Get logs for yesterday (in raw JSON format):**

```sh
limitless yesterday --raw
```

**Get logs for a specific date:**

```sh
limitless get 2024-07-28
```

**Get logs for a specific week:**

```sh
limitless week 30
```

**List logs for a date range:**

```sh
limitless list --start "2024-07-01 00:00:00" --end "2024-07-07 23:59:59"
```

**Fetch logs for a datetime range:**

```sh
limitless range "2024-07-15 10:00:00" "2024-07-15 12:00:00"
```

### Available Commands

| Command | Description |
|---------|-------------|
| `today` | Fetch logs for today |
| `yesterday` | Fetch logs for yesterday |
| `this-week` | Fetch logs for the current week |
| `last-week` | Fetch logs for the previous week |
| `this-month` | Fetch logs for the current month |
| `last-month` | Fetch logs for the previous month |
| `this-quarter` | Fetch logs for the current quarter |
| `last-quarter` | Fetch logs for the previous quarter |
| `get <date_spec>` | Get logs for a flexible date (e.g., `d-1`, `7/15`, `2024-07-15`) |
| `week <week_spec>` | Get logs for an ISO week (e.g., `30` or `2024-W30`) |
| `list` | List logs for a date or datetime range |
| `range <start> <end>` | Fetch logs for a datetime range |
| `get-lifelog-by-id <id>` | Retrieve a specific lifelog by ID |
| `mcp` | Start MCP server for AI integration |

### Global Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--verbose` | `-v` | Verbose debug output to stderr |
| `--quiet` | | Suppress progress messages |
| `--raw` | | Emit raw JSON instead of markdown |
| `--include-markdown` | | Include markdown in output (default: true) |
| `--include-headings` | | Include headings in markdown output (default: true) |
| `--force-cache` | `-f` | Use cache only; skip API requests |
| `--timezone` | | Timezone for date calculations (default: America/Detroit) |
| `--limit` | | Maximum number of results to return |

## AI Integration (MCP Server)

The CLI includes a built-in MCP server that allows AI assistants to directly access your Limitless data.

### Starting the MCP Server

```sh
limitless mcp
```

The server runs on stdio transport and exposes the following tools:

#### `fetch_day`

Fetches Limitless logs for a specific date.

**Parameters:**
- `date_spec` (string): Date specification - YYYY-MM-DD or shorthand ('today', 'yesterday')
- `timezone` (string, optional): Timezone for date calculations
- `include_markdown` (boolean, optional): Include markdown content
- `include_headings` (boolean, optional): Include headings
- `raw` (boolean, optional): Return raw JSON

#### `fetch_range`

Fetches Limitless logs for a specific datetime range.

**Parameters:**
- `start_datetime` (string): Start datetime in "YYYY-MM-DD HH:MM:SS" format
- `end_datetime` (string): End datetime in "YYYY-MM-DD HH:MM:SS" format
- `timezone` (string, optional): IANA timezone specifier
- `include_markdown` (boolean, optional): Include markdown content
- `include_headings` (boolean, optional): Include headings
- `raw` (boolean, optional): Return raw JSON

### Claude Desktop Configuration

Add to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "limitless": {
      "command": "limitless",
      "args": ["mcp"],
      "env": {
        "LIMITLESS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Caching Strategy

The CLI uses a sophisticated caching system identical to the Python version:

- **Cache Location**: `~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json`
- **Confirmation Stamps**: Each cache file includes a `confirmed_complete_up_to_date` field that validates historical data completeness
- **Smart Probing**: Automatically probes for newer data to confirm historical completeness
- **Streaming Strategies**:
  - **Daily**: Fetches day-by-day, best for small ranges or mostly cached data
  - **Bulk**: Single API call for date ranges, best for large uncached ranges
  - **Hybrid** (default): Analyzes gaps and uses the optimal strategy for each

The Go implementation uses the same cache format as the Python CLI, so caches are interoperable.

## Development

```sh
# Run tests
make test

# Run tests with coverage
make test-coverage

# Format code
make fmt

# Run linter (requires golangci-lint)
make lint

# Tidy dependencies
make tidy
```

## License

MIT License - see LICENSE file for details.

