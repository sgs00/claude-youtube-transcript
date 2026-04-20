import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# T2: YouTube extraction
# ---------------------------------------------------------------------------

class TestValidateYouTubeUrl:
    def test_accepts_watch_url(self):
        from src.lambda_function import _validate_youtube_url
        _validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_accepts_short_url(self):
        from src.lambda_function import _validate_youtube_url
        _validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")

    def test_accepts_mobile_url(self):
        from src.lambda_function import _validate_youtube_url
        _validate_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_non_youtube(self):
        from src.lambda_function import _validate_youtube_url
        with pytest.raises(ValueError, match="YouTube"):
            _validate_youtube_url("https://vimeo.com/123456")

    def test_rejects_example_com(self):
        from src.lambda_function import _validate_youtube_url
        with pytest.raises(ValueError):
            _validate_youtube_url("https://example.com/watch?v=abc")

    def test_rejects_empty_string(self):
        from src.lambda_function import _validate_youtube_url
        with pytest.raises(ValueError):
            _validate_youtube_url("")


class TestGetMetadata:
    def _mock_oembed(self, data: dict):
        import io
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_returns_expected_fields(self):
        from src.lambda_function import _get_metadata

        fake_oembed = {
            "title": "Rick Astley - Never Gonna Give You Up",
            "author_name": "RickAstleyVEVO",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        }

        with patch("urllib.request.urlopen", return_value=self._mock_oembed(fake_oembed)):
            result = _get_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert result["title"] == "Rick Astley - Never Gonna Give You Up"
        assert result["channel"] == "RickAstleyVEVO"
        assert result["thumbnail"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"

    def test_calls_oembed_with_correct_url(self):
        from src.lambda_function import _get_metadata

        fake_oembed = {"title": "t", "author_name": "c", "thumbnail_url": ""}

        with patch("urllib.request.urlopen", return_value=self._mock_oembed(fake_oembed)) as mock_open:
            _get_metadata("https://www.youtube.com/watch?v=abc")

        called_url = mock_open.call_args[0][0]
        assert "youtube.com/oembed" in called_url
        assert "watch%3Fv%3Dabc" in called_url or "watch?v=abc" in called_url


class TestGetTranscript:
    def _make_snippet(self, text, start, duration):
        from youtube_transcript_api._transcripts import FetchedTranscriptSnippet
        return FetchedTranscriptSnippet(text=text, start=start, duration=duration)

    def test_returns_expected_shape(self):
        from src.lambda_function import _get_transcript
        from youtube_transcript_api._transcripts import FetchedTranscript

        snippets = [
            self._make_snippet("Hello world", 0.0, 2.5),
            self._make_snippet("How are you", 2.5, 3.0),
        ]
        fake_transcript = MagicMock()
        fake_transcript.__iter__ = MagicMock(return_value=iter(snippets))

        mock_api = MagicMock()
        mock_api.fetch.return_value = fake_transcript

        with patch("src.lambda_function.YouTubeTranscriptApi", return_value=mock_api):
            result = _get_transcript("dQw4w9WgXcQ")

        assert len(result) == 2
        assert result[0]["text"] == "Hello world"
        assert result[0]["start_seconds"] == 0.0
        assert result[0]["duration_seconds"] == 2.5
        assert "timestamp" in result[0]
        assert result[1]["text"] == "How are you"

    def test_timestamp_format(self):
        from src.lambda_function import _get_transcript

        snippets = [self._make_snippet("Test", 3661.0, 1.0)]
        fake_transcript = MagicMock()
        fake_transcript.__iter__ = MagicMock(return_value=iter(snippets))

        mock_api = MagicMock()
        mock_api.fetch.return_value = fake_transcript

        with patch("src.lambda_function.YouTubeTranscriptApi", return_value=mock_api):
            result = _get_transcript("abc")

        # 3661s = 1h 1m 1s
        assert result[0]["timestamp"] == "1:01:01"

    def test_fetches_multiple_languages(self):
        from src.lambda_function import _get_transcript

        fake_transcript = MagicMock()
        fake_transcript.__iter__ = MagicMock(return_value=iter([]))

        mock_api = MagicMock()
        mock_api.fetch.return_value = fake_transcript

        with patch("src.lambda_function.YouTubeTranscriptApi", return_value=mock_api):
            _get_transcript("abc")

        # Should pass a list of languages, not just English
        call_args = mock_api.fetch.call_args
        assert call_args[0][0] == "abc"
        languages_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("languages", [])
        assert len(languages_arg) > 1


# ---------------------------------------------------------------------------
# T3: MCP protocol handler
# ---------------------------------------------------------------------------

class TestMcpInitialize:
    def test_returns_server_info(self):
        from src.lambda_function import _handle_mcp
        request = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        response = _handle_mcp(request)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "serverInfo" in response["result"]
        assert "capabilities" in response["result"]
        assert "protocolVersion" in response["result"]

    def test_protocol_version(self):
        from src.lambda_function import _handle_mcp
        request = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        response = _handle_mcp(request)
        assert response["result"]["protocolVersion"] == "2025-11-25"


class TestMcpToolsList:
    def test_returns_tool_list(self):
        from src.lambda_function import _handle_mcp
        request = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}
        response = _handle_mcp(request)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "get_youtube_transcript"
        assert "inputSchema" in tools[0]
        assert "description" in tools[0]

    def test_tool_schema_has_url_property(self):
        from src.lambda_function import _handle_mcp
        request = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}
        response = _handle_mcp(request)
        schema = response["result"]["tools"][0]["inputSchema"]
        assert schema["type"] == "object"
        assert "url" in schema["properties"]
        assert "url" in schema.get("required", [])


class TestMcpToolsCall:
    def test_calls_get_youtube_transcript(self):
        from src.lambda_function import _handle_mcp

        fake_metadata = {
            "title": "Test Video", "channel": "TestCh", "duration": 100,
            "views": 1000, "description": "desc", "thumbnail": "http://t.com/t.jpg",
        }
        fake_transcript = [{"timestamp": "0:00:00", "start_seconds": 0.0, "duration_seconds": 2.0, "text": "Hello"}]

        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_youtube_transcript",
                "arguments": {"url": "https://www.youtube.com/watch?v=abc123"},
            },
            "id": 3,
        }

        with patch("src.lambda_function._validate_youtube_url") as mock_validate, \
             patch("src.lambda_function._get_metadata", return_value=fake_metadata) as mock_meta, \
             patch("src.lambda_function._get_transcript", return_value=fake_transcript) as mock_tx:
            response = _handle_mcp(request)

        mock_validate.assert_called_once_with("https://www.youtube.com/watch?v=abc123")
        mock_meta.assert_called_once_with("https://www.youtube.com/watch?v=abc123")
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        content = response["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        payload = json.loads(content[0]["text"])
        assert payload["metadata"] == fake_metadata
        assert payload["transcript"] == fake_transcript

    def test_unknown_tool_returns_error(self):
        from src.lambda_function import _handle_mcp
        request = {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
            "id": 4,
        }
        response = _handle_mcp(request)
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_invalid_url_returns_error(self):
        from src.lambda_function import _handle_mcp
        request = {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "get_youtube_transcript", "arguments": {"url": "https://evil.com"}},
            "id": 5,
        }
        response = _handle_mcp(request)
        assert "error" in response


class TestMcpUnknownMethod:
    def test_unknown_method_returns_32601(self):
        from src.lambda_function import _handle_mcp
        request = {"jsonrpc": "2.0", "method": "notifications/whatever", "params": {}, "id": 6}
        response = _handle_mcp(request)
        assert response["error"]["code"] == -32601
        assert response["id"] == 6


# ---------------------------------------------------------------------------
# T4: Lambda entry point
# ---------------------------------------------------------------------------

def _make_event(body, method="POST", path="/"):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


class TestHandlerRouting:
    def test_post_to_root_returns_200(self):
        from src.lambda_function import handler
        event = _make_event({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = handler(event, {})
        assert result["statusCode"] == 200

    def test_get_to_root_returns_404(self):
        from src.lambda_function import handler
        event = _make_event("", method="GET", path="/")
        result = handler(event, {})
        assert result["statusCode"] == 404

    def test_get_to_oauth_discovery_returns_404(self):
        from src.lambda_function import handler
        event = _make_event("", method="GET", path="/.well-known/oauth-protected-resource")
        result = handler(event, {})
        assert result["statusCode"] == 404

    def test_malformed_json_returns_400(self):
        from src.lambda_function import handler
        event = _make_event("not-json-at-all")
        result = handler(event, {})
        assert result["statusCode"] == 400


class TestHandlerResponse:
    def test_response_has_content_type_json(self):
        from src.lambda_function import handler
        event = _make_event({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = handler(event, {})
        assert "application/json" in result["headers"]["Content-Type"]

    def test_response_body_is_valid_json(self):
        from src.lambda_function import handler
        event = _make_event({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        result = handler(event, {})
        parsed = json.loads(result["body"])
        assert "result" in parsed
