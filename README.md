# Limitless CLI

A command-line utility for interacting with data from your Limitless AI device.

This tool allows you to fetch, cache, and display lifelog data directly from the terminal, with flexible options for querying by date, week, or relative time periods.

## Features

- **Robust Caching**: Intelligently caches daily logs to minimize API calls while ensuring data is complete and up-to-date. See the full [caching strategy](./docs/caching_strategy.md) for details.
- **Flexible Queries**: Fetch data for a single day, a specific week, a date range, or using relative periods like `today`, `last-week`, or `this-month`.
- **Multiple Fetch Strategies**: Automatically uses a hybrid fetch strategy to balance API efficiency and speed, with optional parallel fetching.
- **Multiple Output Formats**: View data as clean, readable markdown or as raw JSON for piping to other tools.

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

## Developer Documentation

- **API Reference**: See the [API reference](./docs/api_reference.md) for details on the endpoints this tool consumes.
- **Caching Strategy**: The logic for caching is explained in the [caching strategy document](./docs/caching_strategy.md).
