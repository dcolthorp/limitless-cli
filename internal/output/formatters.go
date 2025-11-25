// Package output provides output formatting utilities for the Limitless CLI.
package output

import (
	"encoding/json"
	"fmt"
	"os"
)

// StreamJSON writes an iterator of JSON-able maps as a compact JSON array.
func StreamJSON(logs <-chan map[string]interface{}) {
	fmt.Print("[")
	first := true
	for item := range logs {
		if !first {
			fmt.Print(",")
		}
		data, err := json.Marshal(item)
		if err != nil {
			continue
		}
		os.Stdout.Write(data)
		first = false
	}
	fmt.Println("]")
}

// StreamJSONSlice writes a slice of maps as a compact JSON array.
func StreamJSONSlice(logs []map[string]interface{}) {
	fmt.Print("[")
	for i, item := range logs {
		if i > 0 {
			fmt.Print(",")
		}
		data, err := json.Marshal(item)
		if err != nil {
			continue
		}
		os.Stdout.Write(data)
	}
	fmt.Println("]")
}

// PrintMarkdown extracts and prints the markdown field of each lifelog.
func PrintMarkdown(logs <-chan map[string]interface{}) {
	for item := range logs {
		md := ""
		if m, ok := item["markdown"].(string); ok && m != "" {
			md = m
		} else if data, ok := item["data"].(map[string]interface{}); ok {
			if m, ok := data["markdown"].(string); ok {
				md = m
			}
		}
		if md != "" {
			fmt.Println(md)
		}
	}
}

// PrintMarkdownSlice extracts and prints the markdown field from a slice.
func PrintMarkdownSlice(logs []map[string]interface{}) {
	for _, item := range logs {
		md := ""
		if m, ok := item["markdown"].(string); ok && m != "" {
			md = m
		} else if data, ok := item["data"].(map[string]interface{}); ok {
			if m, ok := data["markdown"].(string); ok {
				md = m
			}
		}
		if md != "" {
			fmt.Println(md)
		}
	}
}

// PrintJSON prints a single item as formatted JSON.
func PrintJSON(item interface{}) {
	data, err := json.MarshalIndent(item, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error encoding JSON: %v\n", err)
		return
	}
	fmt.Println(string(data))
}

