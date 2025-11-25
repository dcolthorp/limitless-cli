package api

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

// APIError is returned when the Limitless API returns an error response.
type APIError struct {
	StatusCode int
	Message    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("API error (HTTP %d): %s", e.StatusCode, e.Message)
}

// Client is the HTTP wrapper around the Limitless REST API.
type Client struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
	verbose    bool
}

// NewClient creates a new API client.
func NewClient(apiKey string, verbose bool) *Client {
	if apiKey == "" {
		apiKey = core.GetAPIKey()
	}
	return &Client{
		apiKey:  apiKey,
		baseURL: fmt.Sprintf("%s/%s", core.APIBaseURL, core.APIVersion),
		httpClient: &http.Client{
			Timeout: 300 * time.Second,
		},
		verbose: verbose,
	}
}

// log writes a message to stderr if verbose mode is enabled.
func (c *Client) log(msg string) {
	core.Eprint(fmt.Sprintf("[API] %s", msg), c.verbose)
}

// Request performs a GET request and decodes the JSON payload.
// Retries automatically on HTTP 5xx or 429 responses with exponential back-off.
func (c *Client) Request(endpoint string, params map[string]string) (map[string]interface{}, error) {
	urlStr := fmt.Sprintf("%s/%s", c.baseURL, endpoint)

	// Build query string
	if len(params) > 0 {
		q := url.Values{}
		for k, v := range params {
			q.Set(k, v)
		}
		urlStr = fmt.Sprintf("%s?%s", urlStr, q.Encode())
	}

	c.log(fmt.Sprintf("GET %s", urlStr))

	maxRetries := 3
	var lastErr error

	for attempt := 1; attempt <= maxRetries; attempt++ {
		req, err := http.NewRequest("GET", urlStr, nil)
		if err != nil {
			return nil, fmt.Errorf("failed to create request: %w", err)
		}

		req.Header.Set("X-API-Key", c.apiKey)
		req.Header.Set("Accept", "application/json")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = err
			if attempt < maxRetries {
				wait := time.Duration(1<<(attempt-1)) * time.Second
				c.log(fmt.Sprintf("Attempt %d failed (connection error); retrying in %v...", attempt, wait))
				time.Sleep(wait)
				continue
			}
			return nil, fmt.Errorf("request failed: %w", err)
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return nil, fmt.Errorf("failed to read response body: %w", err)
		}

		// Check for retryable errors
		if resp.StatusCode >= 500 || resp.StatusCode == 429 {
			lastErr = &APIError{StatusCode: resp.StatusCode, Message: string(body)}
			if attempt < maxRetries {
				wait := time.Duration(1<<(attempt-1)) * time.Second
				if resp.StatusCode == 429 {
					if ra := resp.Header.Get("Retry-After"); ra != "" {
						if secs, err := strconv.Atoi(ra); err == nil {
							wait = time.Duration(secs) * time.Second
						}
					}
				}
				c.log(fmt.Sprintf("Attempt %d failed (HTTP %d); retrying in %v...", attempt, resp.StatusCode, wait))
				time.Sleep(wait)
				continue
			}
			return nil, lastErr
		}

		// Non-retryable error
		if resp.StatusCode >= 400 {
			return nil, &APIError{StatusCode: resp.StatusCode, Message: string(body)}
		}

		// Parse JSON response
		var result map[string]interface{}
		if err := json.Unmarshal(body, &result); err != nil {
			return nil, fmt.Errorf("failed to parse JSON response: %w", err)
		}

		// Log response info
		if data, ok := result["data"].(map[string]interface{}); ok {
			if lifelogs, ok := data["lifelogs"].([]interface{}); ok {
				count := len(lifelogs)
				var nextCursor string
				if meta, ok := result["meta"].(map[string]interface{}); ok {
					if lifelogMeta, ok := meta["lifelogs"].(map[string]interface{}); ok {
						if nc, ok := lifelogMeta["nextCursor"].(string); ok {
							nextCursor = nc
						}
					}
				}
				cursorInfo := ", no more pages"
				if nextCursor != "" {
					cursorInfo = fmt.Sprintf(", nextCursor: %s", nextCursor)
				}
				c.log(fmt.Sprintf("Response: HTTP %d, %d lifelogs returned%s", resp.StatusCode, count, cursorInfo))
			}
		} else {
			c.log(fmt.Sprintf("Response: HTTP %d, %d bytes", resp.StatusCode, len(body)))
		}

		return result, nil
	}

	return nil, lastErr
}

// Paginate yields items across paginated responses.
// Transparently handles Limitless "nextCursor" mechanics.
func (c *Client) Paginate(endpoint string, params map[string]string, maxResults int) <-chan map[string]interface{} {
	ch := make(chan map[string]interface{})

	go func() {
		defer close(ch)

		currentParams := make(map[string]string)
		for k, v := range params {
			currentParams[k] = v
		}

		cursor := ""
		if c, ok := currentParams["cursor"]; ok {
			cursor = c
			delete(currentParams, "cursor")
		}

		fetched := 0
		pagesCount := 0

		for {
			if cursor != "" {
				currentParams["cursor"] = cursor
			}

			data, err := c.Request(endpoint, currentParams)
			if err != nil {
				c.log(fmt.Sprintf("Pagination error: %v", err))
				return
			}

			pagesCount++

			// Extract lifelogs
			var logs []interface{}
			if dataSection, ok := data["data"].(map[string]interface{}); ok {
				if lifelogs, ok := dataSection["lifelogs"].([]interface{}); ok {
					logs = lifelogs
				}
			}

			// Extract cursor
			cursor = ""
			if meta, ok := data["meta"].(map[string]interface{}); ok {
				if lifelogMeta, ok := meta["lifelogs"].(map[string]interface{}); ok {
					if nc, ok := lifelogMeta["nextCursor"].(string); ok && nc != "" {
						cursor = nc
					}
				}
			}

			c.log(fmt.Sprintf("Fetched page %d: %d items, total so far %d", pagesCount, len(logs), fetched+len(logs)))

			if len(logs) == 0 {
				break
			}

			for _, log := range logs {
				if maxResults > 0 && fetched >= maxResults {
					c.log(fmt.Sprintf("Pagination complete: reached max_results limit of %d after %d pages", maxResults, pagesCount))
					return
				}
				if logMap, ok := log.(map[string]interface{}); ok {
					ch <- logMap
					fetched++
				}
			}

			if cursor == "" || (maxResults > 0 && fetched >= maxResults) {
				break
			}
		}

		if fetched > 0 {
			c.log(fmt.Sprintf("Pagination complete: %d total items across %d pages", fetched, pagesCount))
		} else {
			c.log(fmt.Sprintf("Pagination complete: no items found after %d pages", pagesCount))
		}
	}()

	return ch
}

// IsVerbose returns whether verbose logging is enabled.
func (c *Client) IsVerbose() bool {
	return c.verbose
}

