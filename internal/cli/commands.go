package cli

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/colthorp/limitless-cli-go/internal/api"
	"github.com/colthorp/limitless-cli-go/internal/cache"
	"github.com/colthorp/limitless-cli-go/internal/core"
	"github.com/colthorp/limitless-cli-go/internal/output"
	"github.com/spf13/cobra"
)

func init() {
	// Add all subcommands
	rootCmd.AddCommand(listCmd)
	rootCmd.AddCommand(getLifelogByIDCmd)
	rootCmd.AddCommand(getCmd)
	rootCmd.AddCommand(weekCmd)
	rootCmd.AddCommand(rangeCmd)
	rootCmd.AddCommand(mcpCmd)

	// Add relative period commands
	for _, period := range []string{"today", "yesterday", "this-week", "last-week", "this-month", "last-month", "this-quarter", "last-quarter"} {
		cmd := createRelativePeriodCmd(period)
		rootCmd.AddCommand(cmd)
	}

	// List command flags
	listCmd.Flags().IntP("parallel", "p", 5, "Max days to fetch in parallel")
	listCmd.Flags().String("date", "", "Single date to fetch (YYYY-MM-DD)")
	listCmd.Flags().String("start", "", "Start datetime (requires --end)")
	listCmd.Flags().String("end", "", "End datetime (requires --start)")
	listCmd.Flags().String("direction", "desc", "Sort direction (asc/desc)")

	// Get command flags
	getCmd.Flags().IntP("parallel", "p", 5, "Max days to fetch in parallel")

	// Week command flags
	weekCmd.Flags().IntP("parallel", "p", 5, "Max days to fetch in parallel")
	weekCmd.Flags().String("direction", "", "Sort direction (asc default)")

	// Range command flags
	rangeCmd.Flags().IntP("parallel", "p", 5, "Max days to fetch in parallel")
}

// listCmd handles the list subcommand
var listCmd = &cobra.Command{
	Use:   "list",
	Short: "List lifelogs for a date or datetime range",
	RunE:  handleList,
}

// getLifelogByIDCmd handles fetching a single lifelog by ID
var getLifelogByIDCmd = &cobra.Command{
	Use:   "get-lifelog-by-id [id]",
	Short: "Retrieve a lifelog by its ID",
	Args:  cobra.ExactArgs(1),
	RunE:  handleGetByID,
}

// getCmd handles flexible date specifications
var getCmd = &cobra.Command{
	Use:   "get [date_spec]",
	Short: "Get logs for a flexible date spec (e.g. d-1, 7/15)",
	Args:  cobra.ExactArgs(1),
	RunE:  handleGetDate,
}

// weekCmd handles week specifications
var weekCmd = &cobra.Command{
	Use:   "week [week_spec]",
	Short: "Get logs for a specific ISO week number",
	Args:  cobra.ExactArgs(1),
	RunE:  handleWeek,
}

// rangeCmd handles datetime range queries
var rangeCmd = &cobra.Command{
	Use:   "range [start] [end]",
	Short: "Fetch logs for a datetime range",
	Args:  cobra.ExactArgs(2),
	RunE:  handleRange,
}

// mcpCmd starts the MCP server
var mcpCmd = &cobra.Command{
	Use:   "mcp",
	Short: "Start MCP server for AI integration",
	RunE:  handleMCP,
}

func handleList(cmd *cobra.Command, args []string) error {
	parallel, _ := cmd.Flags().GetInt("parallel")
	dateStr, _ := cmd.Flags().GetString("date")
	startStr, _ := cmd.Flags().GetString("start")
	endStr, _ := cmd.Flags().GetString("end")
	direction, _ := cmd.Flags().GetString("direction")

	// Validate start/end
	if (startStr != "" && endStr == "") || (endStr != "" && startStr == "") {
		return fmt.Errorf("--start and --end must be used together")
	}

	tzName := timezone
	if tzName == "" {
		tzName = core.DefaultTZ
	}
	loc := core.GetTZ(tzName)

	common := buildCommonParams(tzName, direction)

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	cm := cache.NewManager(limitlessAPI, nil, verbose)

	if dateStr != "" || (startStr != "" && endStr != "") {
		var startDate, endDate time.Time
		var err error

		if dateStr != "" {
			startDate, err = core.ParseDate(dateStr)
			if err != nil {
				return err
			}
			endDate = startDate
		} else {
			startDt, err := core.ParseDatetime(startStr, loc)
			if err != nil {
				return err
			}
			endDt, err := core.ParseDatetime(endStr, loc)
			if err != nil {
				return err
			}
			startDate = core.DateOnly(startDt)
			endDate = core.DateOnly(endDt)
		}

		if !quiet {
			core.ProgressPrint(fmt.Sprintf("Processing logs from %s to %s…", core.FormatDate(startDate), core.FormatDate(endDate)), quiet)
		}

		maxResults := limit
		logsCh := cm.StreamRange(startDate, endDate, common, maxResults, quiet, forceCache, parallel)

		if raw {
			output.StreamJSON(logsCh)
		} else {
			output.PrintMarkdown(logsCh)
		}
	} else {
		// Unbounded date range
		if !quiet {
			core.ProgressPrint("Fetching logs (unbounded date range)…", quiet)
		}

		client := api.NewClient("", verbose)
		logsCh := client.Paginate("lifelogs", common, limit)

		if raw {
			output.StreamJSON(logsCh)
		} else {
			output.PrintMarkdown(logsCh)
		}
	}

	return nil
}

func handleGetByID(cmd *cobra.Command, args []string) error {
	id := args[0]

	core.Eprint(fmt.Sprintf("Fetching lifelog ID '%s'…", id), verbose)

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	result, err := limitlessAPI.FetchLifelogByID(id, includeMarkdown, includeHeadings)
	if err != nil {
		return err
	}

	if raw {
		output.PrintJSON(result)
	} else {
		md := ""
		if m, ok := result["markdown"].(string); ok {
			md = m
		} else if data, ok := result["data"].(map[string]interface{}); ok {
			if m, ok := data["markdown"].(string); ok {
				md = m
			}
		}
		if md != "" {
			fmt.Println(md)
		} else {
			output.PrintJSON(result)
		}
	}

	return nil
}

func handleGetDate(cmd *cobra.Command, args []string) error {
	dateSpec := args[0]
	parallel, _ := cmd.Flags().GetInt("parallel")

	tzName := timezone
	if tzName == "" {
		tzName = core.DefaultTZ
	}
	loc := core.GetTZ(tzName)

	targetDate, err := core.ParseDateSpec(dateSpec, loc)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: Invalid date specification '%s'\n", dateSpec)
		os.Exit(1)
	}

	if !quiet {
		core.ProgressPrint(fmt.Sprintf("Fetching logs for date: %s", core.FormatDate(targetDate)), quiet)
	}

	common := buildCommonParams(tzName, "desc")

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	cm := cache.NewManager(limitlessAPI, nil, verbose)

	logsCh := cm.StreamRange(targetDate, targetDate, common, limit, quiet, forceCache, parallel)

	if raw {
		output.StreamJSON(logsCh)
	} else {
		output.PrintMarkdown(logsCh)
	}

	return nil
}

func handleWeek(cmd *cobra.Command, args []string) error {
	weekSpec := args[0]
	parallel, _ := cmd.Flags().GetInt("parallel")
	direction, _ := cmd.Flags().GetString("direction")

	if direction == "" {
		direction = "asc"
	}

	tzName := timezone
	if tzName == "" {
		tzName = core.DefaultTZ
	}

	startDate, endDate, err := core.ParseWeekSpec(weekSpec)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: Invalid week specification '%s'\n", weekSpec)
		os.Exit(1)
	}

	if !quiet {
		core.ProgressPrint(fmt.Sprintf("Fetching logs for week: %s (%s to %s)", weekSpec, core.FormatDate(startDate), core.FormatDate(endDate)), quiet)
	}

	common := buildCommonParams(tzName, direction)

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	cm := cache.NewManager(limitlessAPI, nil, verbose)

	logsCh := cm.StreamRange(startDate, endDate, common, limit, quiet, forceCache, parallel)

	if raw {
		output.StreamJSON(logsCh)
	} else {
		output.PrintMarkdown(logsCh)
	}

	return nil
}

func handleRange(cmd *cobra.Command, args []string) error {
	startStr := args[0]
	endStr := args[1]
	parallel, _ := cmd.Flags().GetInt("parallel")

	tzName := timezone
	if tzName == "" {
		tzName = core.DefaultTZ
	}
	loc := core.GetTZ(tzName)

	startDt, err := core.ParseDatetime(startStr, loc)
	if err != nil {
		return err
	}
	endDt, err := core.ParseDatetime(endStr, loc)
	if err != nil {
		return err
	}

	if endDt.Before(startDt) {
		return fmt.Errorf("end must be after start")
	}

	common := buildCommonParams(tzName, "asc")

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	cm := cache.NewManager(limitlessAPI, nil, verbose)

	logsCh := cm.StreamRange(core.DateOnly(startDt), core.DateOnly(endDt), common, limit, quiet, forceCache, parallel)

	// Filter logs to the requested time range
	filteredLogs := make([]map[string]interface{}, 0)
	for log := range logsCh {
		if core.LogOverlapsRange(log, startDt, endDt, loc) {
			filteredLogs = append(filteredLogs, log)
		}
	}

	if raw {
		output.StreamJSONSlice(filteredLogs)
	} else {
		output.PrintMarkdownSlice(filteredLogs)
	}

	return nil
}

func createRelativePeriodCmd(period string) *cobra.Command {
	cmd := &cobra.Command{
		Use:   period,
		Short: fmt.Sprintf("Fetch logs for %s", period),
		RunE: func(cmd *cobra.Command, args []string) error {
			return handleTimeRelative(cmd, period)
		},
	}
	cmd.Flags().IntP("parallel", "p", 1, "Max days to fetch in parallel")
	return cmd
}

func handleTimeRelative(cmd *cobra.Command, period string) error {
	parallel, _ := cmd.Flags().GetInt("parallel")

	tzName := timezone
	if tzName == "" {
		tzName = core.DefaultTZ
	}
	loc := core.GetTZ(tzName)

	startDt, endDt, err := core.GetTimeRange(period, loc)
	if err != nil {
		return err
	}

	common := buildCommonParams(tzName, "asc")

	limitlessAPI := api.NewLimitlessAPIWithVerbose(verbose)
	cm := cache.NewManager(limitlessAPI, nil, verbose)

	logsCh := cm.StreamRange(core.DateOnly(startDt), core.DateOnly(endDt), common, limit, quiet, forceCache, parallel)

	if raw {
		output.StreamJSON(logsCh)
	} else {
		output.PrintMarkdown(logsCh)
	}

	return nil
}

func handleMCP(cmd *cobra.Command, args []string) error {
	return runMCPServer()
}

// buildCommonParams creates the common API parameters map.
func buildCommonParams(tzName, direction string) map[string]string {
	common := map[string]string{
		"timezone":  tzName,
		"direction": direction,
	}

	if !includeMarkdown {
		common["includeMarkdown"] = "false"
	}
	if !includeHeadings {
		common["includeHeadings"] = "false"
	}
	if limit > 0 {
		common["limit"] = strconv.Itoa(limit)
	}

	return common
}

