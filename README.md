# Limitless CLI

A command-line utility for interacting with data from your Limitless AI device.

This tool allows you to fetch, cache, and display lifelog data directly from the terminal, with flexible options for querying by date, week, or relative time periods.

## Features

- **Robust Caching**: Intelligently caches daily logs to minimize API calls while ensuring data is complete and up-to-date. See the full [caching strategy](./docs/caching_strategy.md) for details.
- **Flexible Queries**: Fetch data for a single day, a specific week, a date range, or using relative periods like `today`, `last-week`, or `this-month`.
- **Multiple Fetch Strategies**: Supports three streaming strategies (Daily, Bulk, Hybrid) to optimize for different scenarios. The default Hybrid strategy automatically analyzes gaps and uses the most efficient approach for each.
- **Multiple Output Formats**: View data as clean, readable markdown or as raw JSON for piping to other tools.
- **AI Integration**: Built-in MCP (Model Context Protocol) server for seamless integration with AI assistants like Claude, Cursor, and other MCP-compatible tools.

## Installation

This project uses [uv](https://github.com/astral-sh/uv) for high-performance package and virtual environment management.

1.  **Install `uv`:**

    Follow the official installation instructions for your platform. For macOS and Linux:

    ```sh
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

2.  **Clone the repository:**

    ```sh
    git clone https://github.com/your-username/limitless-cli.git
    cd limitless-cli
    ```

3.  **Create and activate a virtual environment using `uv`:**

    ```sh
    uv venv -p python3
    source .venv/bin/activate
    ```

4.  **Install dependencies in editable mode:**
    To install the package and its development dependencies for testing and linting:
    ```sh
    uv pip install -e ".[dev]"
    ```

## Configuration

Before running the CLI, you need to set your Limitless API key as an environment variable.

```sh
export LIMITLESS_API_KEY="YOUR_API_KEY_HERE"
```

You can add this line to your shell profile (e.g., `~/.zshrc`, `~/.bash_profile`) to make it permanent.

## Usage

To run the CLI, use the `limitless` command followed by your desired arguments.

```sh
limitless <command> [options]
```

For example:

```sh
limitless today
limitless last-week --output-format json
```

> **Note:** If you have another version of `limitless` installed globally, your shell might run that version instead of the one in this project's virtual environment. To ensure you are running the local package, you can invoke it directly:
>
> ```sh
> .venv/bin/python -m limitless_cli.cli.entry <command> [options]
> ```

### Get Help

```sh
limitless --help
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

### Advanced Usage

- Use `--verbose` (`-v`) to see detailed debugging output.
- Use `--force-cache` (`-fc`) to bypass API calls and use only local cache (useful for offline access).
- Use `--parallel <N>` to specify the number of parallel workers for fetching multiple days.
- Configure fetch strategy via `FETCH_STRATEGY` environment variable: `HYBRID` (default), `PER_DAY`, or `BULK`.

## AI Integration (MCP Server)

The Limitless CLI includes a built-in MCP (Model Context Protocol) server that allows AI assistants to directly access your Limitless data. This enables powerful workflows where AI can analyze your logs, answer questions about your activities, and help you understand patterns in your data.

### Starting the MCP Server

```sh
limitless mcp
```

The server runs on stdio transport (standard for MCP) and will remain active until terminated.

### Available MCP Tools

The MCP server exposes the following tools to AI clients:

#### `fetch_day`

Fetches Limitless logs for a specific date.

**Parameters:**

- `date_spec` (string): Date specification - either YYYY-MM-DD format or shorthand ('today', 'yesterday')
- `timezone` (string, optional): Timezone for date calculations (default: UTC)
- `include_markdown` (boolean, optional): Include markdown content in results (default: true)
- `include_headings` (boolean, optional): Include headings in markdown output (default: true)
- `raw` (boolean, optional): Return raw JSON instead of formatted results (default: false)

**Examples:**

- `fetch_day("today")` - Get today's logs
- `fetch_day("yesterday")` - Get yesterday's logs
- `fetch_day("2024-01-15")` - Get logs for a specific date
- `fetch_day("2024-01-15", timezone="America/New_York", raw=true)` - Get raw logs for a specific date in EST

### Using with AI Assistants

#### Claude Desktop

Add the following to your Claude Desktop configuration:

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

#### Cursor IDE

The MCP server can be integrated with Cursor's AI features for analyzing your Limitless data within your development workflow.

#### Other MCP Clients

Any MCP-compatible client can connect to the server using stdio transport. The server automatically registers its tools and makes them discoverable to connected clients.

## Developer Documentation

- **API Reference**: See the [API reference](./docs/api_reference.md) for details on the endpoints this tool consumes.
- **Caching Strategy**: The logic for caching is explained in the [caching strategy document](./docs/caching_strategy.md).
