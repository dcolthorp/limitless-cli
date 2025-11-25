package api

import (
	"fmt"
	"strconv"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/core"
)

// LimitlessAPI provides a typed convenience layer over the Limitless REST API.
type LimitlessAPI struct {
	transport Transport
	verbose   bool
}

// NewLimitlessAPI creates a new high-level API client.
func NewLimitlessAPI(transport Transport) *LimitlessAPI {
	if transport == nil {
		transport = NewClient("", false)
	}
	api := &LimitlessAPI{
		transport: transport,
	}
	// Check if transport has verbose flag
	if c, ok := transport.(*Client); ok {
		api.verbose = c.IsVerbose()
	}
	return api
}

// NewLimitlessAPIWithVerbose creates a new high-level API client with explicit verbose setting.
func NewLimitlessAPIWithVerbose(verbose bool) *LimitlessAPI {
	transport := NewClient("", verbose)
	return &LimitlessAPI{
		transport: transport,
		verbose:   verbose,
	}
}

// Paginate yields lifelog items across paginated responses.
func (api *LimitlessAPI) Paginate(endpoint string, params map[string]string, maxResults int) <-chan map[string]interface{} {
	if client, ok := api.transport.(*Client); ok {
		return client.Paginate(endpoint, params, maxResults)
	}

	// Fallback for other transports (mock, etc.)
	ch := make(chan map[string]interface{})
	go func() {
		defer close(ch)

		currentParams := make(map[string]string)
		for k, v := range params {
			currentParams[k] = v
		}

		cursor := ""
		fetched := 0

		for {
			if cursor != "" {
				currentParams["cursor"] = cursor
			}

			data, err := api.transport.Request(endpoint, currentParams)
			if err != nil {
				return
			}

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

			if len(logs) == 0 {
				break
			}

			for _, log := range logs {
				if maxResults > 0 && fetched >= maxResults {
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
	}()

	return ch
}

// FetchLifelogs fetches lifelogs for a date or range.
func (api *LimitlessAPI) FetchLifelogs(opts LifelogOptions) <-chan map[string]interface{} {
	params := make(map[string]string)

	if opts.Timezone != "" {
		params["timezone"] = opts.Timezone
	}
	if opts.Date != nil {
		params["date"] = opts.Date.Format(core.APIDateFmt)
	}
	if opts.Start != nil {
		params["start"] = opts.Start.Format(core.APIDatetimeFmt)
	}
	if opts.End != nil {
		params["end"] = opts.End.Format(core.APIDatetimeFmt)
	}
	if opts.Limit > 0 {
		params["limit"] = strconv.Itoa(opts.Limit)
	} else {
		params["limit"] = strconv.Itoa(core.PageLimit)
	}
	if opts.Direction != "" {
		params["direction"] = opts.Direction
	}
	if !opts.IncludeMarkdown {
		params["includeMarkdown"] = "false"
	}
	if !opts.IncludeHeadings {
		params["includeHeadings"] = "false"
	}

	maxResults := 0
	if opts.MaxResults > 0 {
		maxResults = opts.MaxResults
	}

	return api.Paginate("lifelogs", params, maxResults)
}

// FetchLifelogByID fetches a single lifelog by ID.
func (api *LimitlessAPI) FetchLifelogByID(id string, includeMarkdown, includeHeadings bool) (map[string]interface{}, error) {
	params := make(map[string]string)
	if !includeMarkdown {
		params["includeMarkdown"] = "false"
	}
	if !includeHeadings {
		params["includeHeadings"] = "false"
	}

	result, err := api.transport.Request(fmt.Sprintf("lifelogs/%s", id), params)
	if err != nil {
		return nil, err
	}

	// Extract the lifelog from the response
	if data, ok := result["data"].(map[string]interface{}); ok {
		if lifelog, ok := data["lifelog"].(map[string]interface{}); ok {
			return lifelog, nil
		}
	}

	return result, nil
}

// LifelogOptions contains options for fetching lifelogs.
type LifelogOptions struct {
	Date            *time.Time
	Start           *time.Time
	End             *time.Time
	Timezone        string
	Limit           int
	MaxResults      int
	Direction       string
	IncludeMarkdown bool
	IncludeHeadings bool
}

// IsVerbose returns whether verbose logging is enabled.
func (api *LimitlessAPI) IsVerbose() bool {
	return api.verbose
}

// GetTransport returns the underlying transport.
func (api *LimitlessAPI) GetTransport() Transport {
	return api.transport
}

