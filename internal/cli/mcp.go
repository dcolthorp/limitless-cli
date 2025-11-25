package cli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/api"
	"github.com/colthorp/limitless-cli-go/internal/cache"
	"github.com/colthorp/limitless-cli-go/internal/core"
)

// MCP Protocol types
type MCPRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type MCPResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *MCPError   `json:"error,omitempty"`
}

type MCPError struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

type MCPToolInfo struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	InputSchema map[string]interface{} `json:"inputSchema"`
}

type MCPServerInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type MCPInitializeResult struct {
	ProtocolVersion string        `json:"protocolVersion"`
	ServerInfo      MCPServerInfo `json:"serverInfo"`
	Capabilities    interface{}   `json:"capabilities"`
}

// FetchDayParams are the parameters for the fetch_day tool
type FetchDayParams struct {
	DateSpec        string `json:"date_spec"`
	Timezone        string `json:"timezone"`
	IncludeMarkdown bool   `json:"include_markdown"`
	IncludeHeadings bool   `json:"include_headings"`
	Raw             bool   `json:"raw"`
}

// FetchRangeParams are the parameters for the fetch_range tool
type FetchRangeParams struct {
	StartDatetime   string `json:"start_datetime"`
	EndDatetime     string `json:"end_datetime"`
	Timezone        string `json:"timezone"`
	IncludeMarkdown bool   `json:"include_markdown"`
	IncludeHeadings bool   `json:"include_headings"`
	Raw             bool   `json:"raw"`
}

// runMCPServer starts the MCP server on stdio
func runMCPServer() error {
	scanner := bufio.NewScanner(os.Stdin)
	// Increase buffer size for large messages
	const maxCapacity = 10 * 1024 * 1024 // 10MB
	buf := make([]byte, maxCapacity)
	scanner.Buffer(buf, maxCapacity)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var req MCPRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			// For parse errors, we can't know the ID, so we log to stderr
			// but don't send a response (which would have id: null and confuse clients)
			fmt.Fprintf(os.Stderr, "[MCP] Parse error: %v\n", err)
			continue
		}

		handleMCPRequest(&req)
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scanner error: %w", err)
	}

	return nil
}

func handleMCPRequest(req *MCPRequest) {
	switch req.Method {
	case "initialize":
		handleInitialize(req)
	case "initialized", "notifications/initialized":
		// Notifications don't get responses - silently ignore
		return
	case "tools/list":
		handleToolsList(req)
	case "tools/call":
		handleToolsCall(req)
	default:
		// Only send error for requests (those with an ID)
		// Notifications (no ID) should be silently ignored per JSON-RPC spec
		if req.ID != nil {
			sendError(req.ID, -32601, "Method not found", req.Method)
		}
	}
}

func handleInitialize(req *MCPRequest) {
	result := MCPInitializeResult{
		ProtocolVersion: "2024-11-05",
		ServerInfo: MCPServerInfo{
			Name:    "limitless-cli",
			Version: core.Version,
		},
		Capabilities: map[string]interface{}{
			"tools": map[string]interface{}{},
		},
	}
	sendResponse(req.ID, result)
}

func handleToolsList(req *MCPRequest) {
	tools := []MCPToolInfo{
		{
			Name:        "fetch_day",
			Description: "Fetch Limitless AI logs for a specific date.\n\nArgs:\n    date_spec: Date specification - either YYYY-MM-DD format or shorthand ('today', 'yesterday')\n    timezone: Timezone for date calculations (default: UTC)\n    include_markdown: Include markdown content in results\n    include_headings: Include headings in markdown output\n    raw: Return raw JSON instead of formatted results\n    \nReturns:\n    Dictionary containing the logs and metadata for the requested date",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"date_spec": map[string]interface{}{
						"type":        "string",
						"description": "Date specification - YYYY-MM-DD format or shorthand ('today', 'yesterday')",
					},
					"timezone": map[string]interface{}{
						"type":        "string",
						"description": "Timezone for date calculations",
						"default":     core.DefaultTZ,
					},
					"include_markdown": map[string]interface{}{
						"type":        "boolean",
						"description": "Include markdown content in results",
						"default":     true,
					},
					"include_headings": map[string]interface{}{
						"type":        "boolean",
						"description": "Include headings in markdown output",
						"default":     true,
					},
					"raw": map[string]interface{}{
						"type":        "boolean",
						"description": "Return raw JSON instead of formatted results",
						"default":     false,
					},
				},
				"required": []string{"date_spec"},
			},
		},
		{
			Name:        "fetch_range",
			Description: "Fetch Limitless AI logs for a specific datetime range.\n\nArgs:\n    start_datetime: Start datetime in \"YYYY-MM-DD HH:MM:SS\" format or relative shorthand\n    end_datetime: End datetime in \"YYYY-MM-DD HH:MM:SS\" format or relative shorthand\n    timezone: IANA timezone specifier (default: America/Detroit)\n    include_markdown: Include markdown content in results\n    include_headings: Include headings in markdown output\n    raw: Return raw JSON instead of formatted output\n\nReturns:\n    Dictionary containing the filtered logs and metadata for the requested range",
			InputSchema: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"start_datetime": map[string]interface{}{
						"type":        "string",
						"description": "Start datetime in YYYY-MM-DD HH:MM:SS format",
					},
					"end_datetime": map[string]interface{}{
						"type":        "string",
						"description": "End datetime in YYYY-MM-DD HH:MM:SS format",
					},
					"timezone": map[string]interface{}{
						"type":        "string",
						"description": "IANA timezone specifier",
						"default":     core.DefaultTZ,
					},
					"include_markdown": map[string]interface{}{
						"type":        "boolean",
						"description": "Include markdown content in results",
						"default":     true,
					},
					"include_headings": map[string]interface{}{
						"type":        "boolean",
						"description": "Include headings in markdown output",
						"default":     true,
					},
					"raw": map[string]interface{}{
						"type":        "boolean",
						"description": "Return raw JSON instead of formatted output",
						"default":     false,
					},
				},
				"required": []string{"start_datetime", "end_datetime"},
			},
		},
	}

	sendResponse(req.ID, map[string]interface{}{"tools": tools})
}

func handleToolsCall(req *MCPRequest) {
	var params struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}

	if err := json.Unmarshal(req.Params, &params); err != nil {
		sendError(req.ID, -32602, "Invalid params", err.Error())
		return
	}

	switch params.Name {
	case "fetch_day":
		handleFetchDay(req.ID, params.Arguments)
	case "fetch_range":
		handleFetchRange(req.ID, params.Arguments)
	default:
		sendError(req.ID, -32602, "Unknown tool", params.Name)
	}
}

func handleFetchDay(id interface{}, argsJSON json.RawMessage) {
	var args FetchDayParams
	if err := json.Unmarshal(argsJSON, &args); err != nil {
		sendToolError(id, fmt.Sprintf("Invalid arguments: %v", err))
		return
	}

	// Set defaults
	if args.Timezone == "" {
		args.Timezone = core.DefaultTZ
	}

	loc := core.GetTZ(args.Timezone)

	// Parse date specification
	targetDate, err := parseDateSpec(args.DateSpec, loc)
	if err != nil {
		sendToolResult(id, map[string]interface{}{
			"error":         fmt.Sprintf("Invalid date specification: %s", args.DateSpec),
			"valid_formats": []string{"YYYY-MM-DD", "today", "yesterday"},
			"date_spec":     args.DateSpec,
			"timezone":      args.Timezone,
		})
		return
	}

	// Set up API and cache manager
	limitlessAPI := api.NewLimitlessAPIWithVerbose(false)
	cm := cache.NewManager(limitlessAPI, nil, false)

	// Prepare common parameters
	common := map[string]string{
		"timezone":  args.Timezone,
		"direction": "desc",
	}
	if !args.IncludeMarkdown {
		common["includeMarkdown"] = "false"
	}
	if !args.IncludeHeadings {
		common["includeHeadings"] = "false"
	}

	// Fetch logs
	logs, maxDate := cm.FetchDay(targetDate, common, true, false)

	// Format response
	var maxDateStr *string
	if maxDate != nil {
		s := core.FormatDate(*maxDate)
		maxDateStr = &s
	}

	formattedLogs := logs
	if !args.Raw {
		formattedLogs = formatLogsForDisplay(logs)
	}

	result := map[string]interface{}{
		"date":             core.FormatDate(targetDate),
		"timezone":         args.Timezone,
		"logs_count":       len(logs),
		"logs":             formattedLogs,
		"max_date_in_logs": maxDateStr,
	}

	sendToolResult(id, result)
}

func handleFetchRange(id interface{}, argsJSON json.RawMessage) {
	var args FetchRangeParams
	if err := json.Unmarshal(argsJSON, &args); err != nil {
		sendToolError(id, fmt.Sprintf("Invalid arguments: %v", err))
		return
	}

	// Set defaults
	if args.Timezone == "" {
		args.Timezone = core.DefaultTZ
	}

	loc := core.GetTZ(args.Timezone)

	// Parse datetimes
	startDt, err := core.ParseDatetime(args.StartDatetime, loc)
	if err != nil {
		sendToolResult(id, map[string]interface{}{
			"error":          fmt.Sprintf("Failed to fetch range: %v", err),
			"start_datetime": args.StartDatetime,
			"end_datetime":   args.EndDatetime,
			"timezone":       args.Timezone,
		})
		return
	}

	endDt, err := core.ParseDatetime(args.EndDatetime, loc)
	if err != nil {
		sendToolResult(id, map[string]interface{}{
			"error":          fmt.Sprintf("Failed to fetch range: %v", err),
			"start_datetime": args.StartDatetime,
			"end_datetime":   args.EndDatetime,
			"timezone":       args.Timezone,
		})
		return
	}

	if endDt.Before(startDt) {
		sendToolResult(id, map[string]interface{}{
			"error":          "end_datetime must be after start_datetime",
			"start_datetime": args.StartDatetime,
			"end_datetime":   args.EndDatetime,
		})
		return
	}

	// Set up API and cache manager
	limitlessAPI := api.NewLimitlessAPIWithVerbose(false)
	cm := cache.NewManager(limitlessAPI, nil, false)

	// Prepare common parameters
	common := map[string]string{
		"timezone":  args.Timezone,
		"direction": "asc",
	}
	if !args.IncludeMarkdown {
		common["includeMarkdown"] = "false"
	}
	if !args.IncludeHeadings {
		common["includeHeadings"] = "false"
	}

	// Fetch logs
	logsCh := cm.StreamRange(core.DateOnly(startDt), core.DateOnly(endDt), common, 0, true, false, 1)

	// Filter logs to requested time range
	filteredLogs := make([]map[string]interface{}, 0)
	for log := range logsCh {
		if core.LogOverlapsRange(log, startDt, endDt, loc) {
			filteredLogs = append(filteredLogs, log)
		}
	}

	formattedLogs := filteredLogs
	if !args.Raw {
		formattedLogs = formatLogsForDisplay(filteredLogs)
	}

	result := map[string]interface{}{
		"start_datetime": startDt.Format("2006-01-02 15:04:05"),
		"end_datetime":   endDt.Format("2006-01-02 15:04:05"),
		"timezone":       args.Timezone,
		"logs_count":     len(filteredLogs),
		"logs":           formattedLogs,
	}

	sendToolResult(id, result)
}

func parseDateSpec(dateSpec string, loc *time.Location) (time.Time, error) {
	switch dateSpec {
	case "today":
		return core.DateOnly(time.Now().In(loc)), nil
	case "yesterday":
		return core.DateOnly(time.Now().In(loc).AddDate(0, 0, -1)), nil
	default:
		return core.ParseDate(dateSpec)
	}
}

func formatLogsForDisplay(logs []map[string]interface{}) []map[string]interface{} {
	formatted := make([]map[string]interface{}, 0, len(logs))

	for _, log := range logs {
		formattedLog := map[string]interface{}{
			"id":         log["id"],
			"title":      log["title"],
			"start_time": log["startTime"],
			"end_time":   log["endTime"],
			"markdown":   log["markdown"],
		}

		// Include content summary if available
		if contents, ok := log["contents"].([]interface{}); ok && len(contents) > 0 {
			summary := map[string]interface{}{
				"sections": len(contents),
			}
			if first, ok := contents[0].(map[string]interface{}); ok {
				summary["first_section_type"] = first["type"]
				if content, ok := first["content"].(string); ok {
					if len(content) > 200 {
						content = content[:200] + "..."
					}
					summary["preview"] = content
				}
			}
			formattedLog["content_summary"] = summary
		}

		formatted = append(formatted, formattedLog)
	}

	return formatted
}

func sendResponse(id interface{}, result interface{}) {
	resp := MCPResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  result,
	}
	data, _ := json.Marshal(resp)
	fmt.Println(string(data))
}

func sendError(id interface{}, code int, message, data string) {
	resp := MCPResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error: &MCPError{
			Code:    code,
			Message: message,
			Data:    data,
		},
	}
	data2, _ := json.Marshal(resp)
	fmt.Println(string(data2))
}

func sendToolResult(id interface{}, result interface{}) {
	sendResponse(id, map[string]interface{}{
		"content": []map[string]interface{}{
			{
				"type": "text",
				"text": mustMarshal(result),
			},
		},
	})
}

func sendToolError(id interface{}, message string) {
	sendResponse(id, map[string]interface{}{
		"content": []map[string]interface{}{
			{
				"type": "text",
				"text": message,
			},
		},
		"isError": true,
	})
}

func mustMarshal(v interface{}) string {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Sprintf("error: %v", err)
	}
	return string(data)
}

