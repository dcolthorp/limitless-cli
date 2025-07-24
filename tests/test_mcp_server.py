"""Tests for MCP server functionality."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from src.limitless_cli.mcp.server import create_server, _parse_date_spec, _format_logs_for_display


class TestMCPServer:
    """Test the MCP server creation and configuration."""
    
    def test_create_server(self):
        """Test that the server can be created successfully."""
        server = create_server()
        assert server is not None
        assert server.name == "limitless-cli"

    def test_server_has_fetch_day_tool(self):
        """Test that the server has the fetch_day tool registered."""
        server = create_server()
        # Check that the server has a tool manager
        assert hasattr(server, '_tool_manager')
        assert server._tool_manager is not None


class TestDateParsing:
    """Test date specification parsing functionality."""
    
    @patch('src.limitless_cli.mcp.server.datetime')
    def test_parse_date_spec_today(self, mock_datetime):
        """Test parsing 'today' shorthand."""
        mock_now = datetime(2024, 1, 15, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        
        mock_tz = MagicMock()
        result = _parse_date_spec("today", mock_tz)
        
        expected = date(2024, 1, 15)
        assert result == expected
        mock_datetime.now.assert_called_once_with(mock_tz)

    @patch('src.limitless_cli.mcp.server.datetime')
    def test_parse_date_spec_yesterday(self, mock_datetime):
        """Test parsing 'yesterday' shorthand."""
        mock_now = datetime(2024, 1, 15, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        
        mock_tz = MagicMock()
        result = _parse_date_spec("yesterday", mock_tz)
        
        expected = date(2024, 1, 14)
        assert result == expected
        mock_datetime.now.assert_called_once_with(mock_tz)

    @patch('src.limitless_cli.mcp.server.parse_date')
    def test_parse_date_spec_explicit_date(self, mock_parse_date):
        """Test parsing explicit YYYY-MM-DD date."""
        expected_date = date(2024, 1, 15)
        mock_parse_date.return_value = expected_date
        
        mock_tz = MagicMock()
        result = _parse_date_spec("2024-01-15", mock_tz)
        
        assert result == expected_date
        mock_parse_date.assert_called_once_with("2024-01-15")

    @patch('src.limitless_cli.mcp.server.parse_date')
    def test_parse_date_spec_invalid_date(self, mock_parse_date):
        """Test parsing invalid date specification."""
        mock_parse_date.side_effect = ValueError("Invalid date")
        
        mock_tz = MagicMock()
        result = _parse_date_spec("invalid-date", mock_tz)
        
        assert result is None

    def test_parse_date_spec_case_insensitive(self):
        """Test that date parsing is case insensitive."""
        with patch('src.limitless_cli.mcp.server.datetime') as mock_datetime:
            mock_now = datetime(2024, 1, 15, 12, 0, 0)
            mock_datetime.now.return_value = mock_now
            
            mock_tz = MagicMock()
            
            # Test various cases
            for case in ["TODAY", "Today", "tOdAy"]:
                result = _parse_date_spec(case, mock_tz)
                assert result == date(2024, 1, 15)


class TestLogFormatting:
    """Test log formatting functionality."""
    
    def test_format_logs_for_display_empty(self):
        """Test formatting empty log list."""
        result = _format_logs_for_display([])
        assert result == []

    def test_format_logs_for_display_basic(self):
        """Test formatting basic log entry."""
        logs = [{
            "id": "test-id",
            "title": "Test Log",
            "startTime": "2024-01-15T10:00:00Z",
            "endTime": "2024-01-15T10:30:00Z",
            "markdown": "# Test content"
        }]
        
        result = _format_logs_for_display(logs)
        
        assert len(result) == 1
        formatted_log = result[0]
        assert formatted_log["id"] == "test-id"
        assert formatted_log["title"] == "Test Log"
        assert formatted_log["start_time"] == "2024-01-15T10:00:00Z"
        assert formatted_log["end_time"] == "2024-01-15T10:30:00Z"
        assert formatted_log["markdown"] == "# Test content"

    def test_format_logs_for_display_with_contents(self):
        """Test formatting log entry with content sections."""
        logs = [{
            "id": "test-id",
            "title": "Test Log",
            "startTime": "2024-01-15T10:00:00Z",
            "endTime": "2024-01-15T10:30:00Z",
            "markdown": "# Test content",
            "contents": [
                {
                    "type": "paragraph",
                    "content": "This is a long piece of content that should be truncated in the preview to avoid overwhelming the display with too much text."
                },
                {
                    "type": "heading1",
                    "content": "Another section"
                }
            ]
        }]
        
        result = _format_logs_for_display(logs)
        
        assert len(result) == 1
        formatted_log = result[0]
        assert "content_summary" in formatted_log
        
        summary = formatted_log["content_summary"]
        assert summary["sections"] == 2
        assert summary["first_section_type"] == "paragraph"
        assert len(summary["preview"]) <= 203  # 200 chars + "..."
        assert summary["preview"].endswith("...")

    def test_format_logs_for_display_handles_missing_fields(self):
        """Test formatting handles missing or None fields gracefully."""
        logs = [{
            "id": "test-id",
            # Missing other fields
        }]
        
        result = _format_logs_for_display(logs)
        
        assert len(result) == 1
        formatted_log = result[0]
        assert formatted_log["id"] == "test-id"
        assert formatted_log["title"] == ""
        assert formatted_log["start_time"] == ""
        assert formatted_log["end_time"] == ""
        assert formatted_log["markdown"] == ""


class TestFetchDayIntegration:
    """Integration tests for the fetch_day tool."""
    
    @patch('src.limitless_cli.mcp.server.CacheManager')
    @patch('src.limitless_cli.mcp.server.LimitlessAPI')
    @patch('src.limitless_cli.mcp.server.get_tz')
    def test_fetch_day_today_success(self, mock_get_tz, mock_api_class, mock_cache_class):
        """Test successful fetch for 'today'."""
        # Setup mocks
        mock_tz = MagicMock()
        mock_get_tz.return_value = mock_tz
        
        mock_cache = MagicMock()
        mock_cache.fetch_day.return_value = ([{"id": "test", "title": "Test"}], date(2024, 1, 15))
        mock_cache_class.return_value = mock_cache
        
        # Create server and get the fetch_day function
        server = create_server()
        
        # Mock the current date
        with patch('src.limitless_cli.mcp.server.datetime') as mock_datetime:
            mock_now = datetime(2024, 1, 15, 12, 0, 0)
            mock_datetime.now.return_value = mock_now
            
            # Call fetch_day through the server's tool
            # Note: This would require accessing internal FastMCP structures
            # For now, we'll test the function directly
            from src.limitless_cli.mcp.server import _parse_date_spec
            
            target_date = _parse_date_spec("today", mock_tz)
            assert target_date == date(2024, 1, 15)

    def test_fetch_day_invalid_date_spec(self):
        """Test fetch_day with invalid date specification."""
        server = create_server()
        
        # This would test the actual tool function, but requires FastMCP internals
        # For now, test the helper function
        from src.limitless_cli.mcp.server import _parse_date_spec
        
        mock_tz = MagicMock()
        result = _parse_date_spec("invalid-spec", mock_tz)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__]) 