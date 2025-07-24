# ==========================

# Limitless API Documentation

# ==========================

## Authentication

All API requests require authentication using an API key in the `X-API-Key` header.
Obtain your API key from the Developer settings in your Limitless account.

## Base URL

`https://api.limitless.ai/v1`

## Endpoints

### GET /lifelogs

Returns a list of lifelog entries based on time range or specific date.

**Query Parameters:**

- `timezone` (string): IANA timezone specifier (default: UTC)
- `date` (string): Single date in `YYYY-MM-DD` format
- `start` (string): Start datetime in `YYYY-MM-DD` or `YYYY-MM-DD HH:mm:SS` format
- `end` (string): End datetime in `YYYY-MM-DD` or `YYYY-MM-DD HH:mm:SS` format
- `cursor` (string): Pagination cursor for next set of results
- `direction` (string): Sort direction - "asc" or "desc" (default: desc)
- `includeMarkdown` (boolean): Include markdown content (default: true)
- `includeHeadings` (boolean): Include headings in response (default: true)
- `limit` (integer): Maximum results to return (max: 10, default: 3)

**Response Structure:**

```json
{
  "data": {
    "lifelogs": [
      {
        "id": "string",
        "title": "string",
        "markdown": "string",
        "startTime": "ISO-8601 string",
        "endTime": "ISO-8601 string",
        "contents": [
          {
            "type": "heading1|heading2|blockquote",
            "content": "string",
            "startTime": "ISO-8601 string",
            "endTime": "ISO-8601 string",
            "startOffsetMs": "integer",
            "endOffsetMs": "integer",
            "children": [],
            "speakerName": "string",
            "speakerIdentifier": "user|null"
          }
        ]
      }
    ]
  },
  "meta": {
    "lifelogs": {
      "nextCursor": "string",
      "count": "integer"
    }
  }
}
```

### GET /lifelogs/{lifelog_id}

Returns a specific lifelog entry by ID.

**Path Parameters:**

- `lifelog_id` (string): The ID of the lifelog entry to retrieve

**Query Parameters:**

- `includeMarkdown` (boolean): Include markdown content (default: true)
- `includeHeadings` (boolean): Include headings in response (default: true)

**Response Structure:**

```json
{
  "data": {
    "lifelog": {
      "id": "string",
      "title": "string",
      "markdown": "string",
      "startTime": "ISO-8601 string",
      "endTime": "ISO-8601 string",
      "contents": [
        /* ContentNode array */
      ]
    }
  }
}
```

## Error Handling

The API returns standard HTTP status codes:

- `200`: Success
- `401`: Unauthorized (invalid API key)
- `404`: Not found
- `429`: Rate limit exceeded (check `Retry-After` header)
- `500`: Internal server error

## Rate Limiting

Rate-limited requests return a `429` status with a `Retry-After` header indicating
wait time in seconds before retrying.

## Data Types

**ContentNode Properties:**

- `type`: Content node type (`heading1`, `heading2`, `heading3`, `blockquote`, etc.)
- `content`: Text content of the node
- `startTime`/`endTime`: ISO-8601 timestamps in specified timezone
- `startOffsetMs`/`endOffsetMs`: Milliseconds offset from entry start
- `children`: Array of nested ContentNode objects
- `speakerName`: Speaker identifier for certain node types
- `speakerIdentifier`: "user" when speaker is identified as the user, null otherwise

## MCP Server Integration

The Limitless CLI includes a built-in MCP (Model Context Protocol) server that provides programmatic access to the API through AI assistants and other MCP-compatible tools.

### Starting the MCP Server

```bash
limitless mcp
```

The server runs on stdio transport and exposes the following tools:

### MCP Tools

#### fetch_day

Fetches Limitless logs for a specific date with flexible date specifications.

**Parameters:**

- `date_spec` (string): Date specification - YYYY-MM-DD format or shorthand ('today', 'yesterday')
- `timezone` (string, optional): IANA timezone specifier (default: UTC)
- `include_markdown` (boolean, optional): Include markdown content (default: true)
- `include_headings` (boolean, optional): Include headings in response (default: true)
- `raw` (boolean, optional): Return raw API response instead of formatted output (default: false)

**Returns:**

```json
{
  "date": "2024-01-15",
  "timezone": "UTC",
  "logs_count": 5,
  "logs": [
    /* formatted or raw log entries */
  ],
  "max_date_in_logs": "2024-01-15"
}
```

**Error Response:**

```json
{
  "error": "Invalid date specification: invalid-date",
  "valid_formats": ["YYYY-MM-DD", "today", "yesterday"],
  "date_spec": "invalid-date",
  "timezone": "UTC"
}
```

### Integration Examples

#### Claude Desktop Configuration

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

#### Cursor IDE Integration

The MCP server can be used with Cursor's AI features to analyze your Limitless data within your development environment.

## Notes

- The API is currently in beta and supports Pendant data only
- Timezones/offsets in start/end parameters are ignored; use `timezone` parameter
- Use `cursor` parameter for pagination when limit is reached
- Maximum `limit` is 10 entries per request
- MCP server requires `LIMITLESS_API_KEY` environment variable to be set
