// Package api provides the HTTP client and types for the Limitless API.
package api

// ContentNode represents a content node in a lifelog entry.
type ContentNode struct {
	Type              string        `json:"type"`
	Content           string        `json:"content"`
	StartTime         string        `json:"startTime,omitempty"`
	EndTime           string        `json:"endTime,omitempty"`
	StartOffsetMs     int           `json:"startOffsetMs,omitempty"`
	EndOffsetMs       int           `json:"endOffsetMs,omitempty"`
	SpeakerName       string        `json:"speakerName,omitempty"`
	SpeakerIdentifier *string       `json:"speakerIdentifier,omitempty"`
	Children          []ContentNode `json:"children,omitempty"`
}

// Lifelog represents a single lifelog entry from the API.
type Lifelog struct {
	ID        string        `json:"id"`
	Title     string        `json:"title"`
	Markdown  string        `json:"markdown,omitempty"`
	StartTime string        `json:"startTime"`
	EndTime   string        `json:"endTime"`
	Contents  []ContentNode `json:"contents,omitempty"`
	// Convenience field for date-based operations
	Date string `json:"date,omitempty"`
}

// LifelogMeta contains pagination metadata for lifelog responses.
type LifelogMeta struct {
	NextCursor *string `json:"nextCursor"`
	Count      int     `json:"count"`
}

// LifelogData wraps the lifelogs array in the response.
type LifelogData struct {
	Lifelogs []map[string]interface{} `json:"lifelogs"`
	Lifelog  *map[string]interface{}  `json:"lifelog,omitempty"`
}

// MetaWrapper wraps the meta section of the response.
type MetaWrapper struct {
	Lifelogs LifelogMeta `json:"lifelogs"`
}

// LifelogResponse represents the full API response for lifelogs.
type LifelogResponse struct {
	Data LifelogData `json:"data"`
	Meta MetaWrapper `json:"meta"`
}

// SingleLifelogResponse represents the API response for a single lifelog.
type SingleLifelogResponse struct {
	Data struct {
		Lifelog map[string]interface{} `json:"lifelog"`
	} `json:"data"`
}

// Transport is the interface for making API requests.
type Transport interface {
	Request(endpoint string, params map[string]string) (map[string]interface{}, error)
}

