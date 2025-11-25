// Package cli implements the command-line interface for the Limitless CLI.
package cli

import (
	"fmt"
	"os"

	"github.com/colthorp/limitless-cli-go/internal/core"
	"github.com/spf13/cobra"
)

// Global flags
var (
	verbose         bool
	quiet           bool
	raw             bool
	includeMarkdown bool
	includeHeadings bool
	forceCache      bool
	timezone        string
	limit           int
)

// rootCmd represents the base command when called without any subcommands
var rootCmd = &cobra.Command{
	Use:     "limitless",
	Short:   "Limitless CLI – interact with the API",
	Long:    `A command-line utility for interacting with data from your Limitless AI device.`,
	Version: core.Version,
}

// Execute adds all child commands to the root command and sets flags appropriately.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func init() {
	// Persistent flags available to all commands
	rootCmd.PersistentFlags().BoolVarP(&verbose, "verbose", "v", false, "Verbose debug output to stderr")
	rootCmd.PersistentFlags().BoolVar(&quiet, "quiet", false, "Suppress progress messages")
	rootCmd.PersistentFlags().BoolVar(&raw, "raw", false, "Emit raw JSON instead of markdown")
	rootCmd.PersistentFlags().BoolVar(&includeMarkdown, "include-markdown", true, "Include markdown in output")
	rootCmd.PersistentFlags().BoolVar(&includeHeadings, "include-headings", true, "Include headings in markdown output")
	rootCmd.PersistentFlags().BoolVarP(&forceCache, "force-cache", "f", false, "Use cache only; skip API requests")
	rootCmd.PersistentFlags().StringVar(&timezone, "timezone", "", fmt.Sprintf("Timezone for date calculations (default: %s)", core.DefaultTZ))
	rootCmd.PersistentFlags().IntVar(&limit, "limit", 0, "Maximum number of results to return")
}

