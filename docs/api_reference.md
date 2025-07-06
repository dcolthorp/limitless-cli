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

## Notes

- The API is currently in beta and supports Pendant data only
- Timezones/offsets in start/end parameters are ignored; use `timezone` parameter
- Use `cursor` parameter for pagination when limit is reached
- Maximum `limit` is 10 entries per request
