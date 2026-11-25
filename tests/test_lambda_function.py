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


class TestWebshareProxy:
    def _run(self, secret_name, secret_value=None):
        from src.lambda_function import _get_transcript

        fake_transcript = MagicMock()
        fake_transcript.__iter__ = MagicMock(return_value=iter([]))
        mock_api = MagicMock()
        mock_api.fetch.return_value = fake_transcript

        with patch("src.lambda_function._WEBSHARE_SECRET_NAME", secret_name), \
             patch("src.lambda_function._webshare_credentials", None), \
             patch("src.lambda_function._get_secret_string", return_value=secret_value) as mock_secret, \
             patch("src.lambda_function.WebshareProxyConfig") as mock_proxy, \
             patch("src.lambda_function.YouTubeTranscriptApi", return_value=mock_api) as mock_cls:
            _get_transcript("abc")
            _get_transcript("abc")
        return mock_secret, mock_proxy, mock_cls

    def test_no_secret_name_disables_proxy(self):
        mock_secret, mock_proxy, mock_cls = self._run("")
        mock_secret.assert_not_called()
        mock_proxy.assert_not_called()
        assert mock_cls.call_args.kwargs["proxy_config"] is None

    def test_uses_credentials_from_secret(self):
        value = json.dumps({"username": "user", "password": "pass"})
        mock_secret, mock_proxy, mock_cls = self._run("fn-webshare", value)
        mock_secret.assert_called_once_with("fn-webshare")  # cached across calls
        mock_proxy.assert_called_with("user", "pass")
        assert mock_cls.call_args.kwargs["proxy_config"] is mock_proxy.return_value

    def test_incomplete_secret_disables_proxy(self):
        value = json.dumps({"username": "user", "password": ""})
        mock_secret, mock_proxy, mock_cls = self._run("fn-webshare", value)
        mock_proxy.assert_not_called()
        assert mock_cls.call_args.kwargs["proxy_config"] is None


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
        assert [t["name"] for t in tools] == ["get_youtube_transcript", "get_youtube_playlist"]
        for tool in tools:
            assert "inputSchema" in tool
            assert "description" in tool
            assert tool["inputSchema"]["required"] == ["url"]

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


# ---------------------------------------------------------------------------
# Playlists (YouTube Data API v3)
# ---------------------------------------------------------------------------

def _pl_item(position, video_id, title="T", channel="Ch"):
    snippet = {"position": position, "title": title, "resourceId": {"videoId": video_id}}
    if channel:
        snippet["videoOwnerChannelTitle"] = channel
    return {"snippet": snippet, "contentDetails": {"videoId": video_id, "videoPublishedAt": "2026-01-01T00:00:00Z"}}


_PL_INFO = {"items": [{
    "snippet": {"title": "My list", "channelTitle": "Owner", "description": "d"},
    "contentDetails": {"itemCount": 3},
}]}


def _fake_api(pages):
    """Return a _youtube_api replacement: 'playlists' -> _PL_INFO, 'playlistItems' -> pages by token."""
    calls = []

    def api(resource, params):
        calls.append((resource, dict(params)))
        if resource == "playlists":
            return _PL_INFO
        return pages[params.get("pageToken")]
    return api, calls


class TestExtractPlaylistId:
    @pytest.mark.parametrize("url", [
        "https://youtube.com/playlist?list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd&si=mjWs9lnmjRn531Y4",
        "https://www.youtube.com/playlist?list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd",
        "https://m.youtube.com/playlist?list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd",
        "https://www.youtube.com/watch?v=abc&list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd&index=2",
        "https://youtu.be/abc?list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd",
    ])
    def test_accepts_playlist_urls(self, url):
        from src.lambda_function import _extract_playlist_id
        assert _extract_playlist_id(url) == "PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd"

    @pytest.mark.parametrize("url", [
        "", "https://www.youtube.com/watch?v=abc", "https://evil.com/playlist?list=PLx",
        "https://youtube.com.evil.com/playlist?list=PLx",
    ])
    def test_rejects_other_urls(self, url):
        from src.lambda_function import _extract_playlist_id
        with pytest.raises(ValueError, match="playlist"):
            _extract_playlist_id(url)


class TestGetPlaylist:
    def test_returns_playlist_and_videos(self):
        from src.lambda_function import _get_playlist
        api, _ = _fake_api({None: {"items": [_pl_item(0, "v1", "First"), _pl_item(1, "v2", "Second")]}})
        with patch("src.lambda_function._youtube_api", side_effect=api):
            result = _get_playlist("PLx", 50)
        assert result["playlist"] == {
            "id": "PLx", "url": "https://www.youtube.com/playlist?list=PLx",
            "title": "My list", "channel": "Owner", "description": "d", "video_count": 3,
        }
        assert result["videos"][0] == {
            "position": 1, "title": "First", "channel": "Ch",
            "url": "https://www.youtube.com/watch?v=v1", "published_at": "2026-01-01T00:00:00Z",
        }
        assert [v["position"] for v in result["videos"]] == [1, 2]
        assert result["truncated"] is False
        assert result["unavailable_skipped"] == 0

    def test_skips_private_and_deleted_videos(self):
        from src.lambda_function import _get_playlist
        api, _ = _fake_api({None: {"items": [
            _pl_item(0, "v1"), _pl_item(1, "gone", "Private video", channel=None), _pl_item(2, "v3"),
        ]}})
        with patch("src.lambda_function._youtube_api", side_effect=api):
            result = _get_playlist("PLx", 50)
        assert [v["position"] for v in result["videos"]] == [1, 3]
        assert result["unavailable_skipped"] == 1

    def test_follows_pages(self):
        from src.lambda_function import _get_playlist
        api, calls = _fake_api({
            None: {"items": [_pl_item(0, "v1")], "nextPageToken": "p2"},
            "p2": {"items": [_pl_item(1, "v2")]},
        })
        with patch("src.lambda_function._youtube_api", side_effect=api):
            result = _get_playlist("PLx", 50)
        assert len(result["videos"]) == 2
        assert result["truncated"] is False
        assert [c[1].get("pageToken") for c in calls if c[0] == "playlistItems"] == [None, "p2"]

    def test_truncates_within_page(self):
        from src.lambda_function import _get_playlist
        api, _ = _fake_api({None: {"items": [_pl_item(i, f"v{i}") for i in range(3)]}})
        with patch("src.lambda_function._youtube_api", side_effect=api):
            result = _get_playlist("PLx", 2)
        assert len(result["videos"]) == 2
        assert result["truncated"] is True

    def test_stops_before_next_page_when_full(self):
        from src.lambda_function import _get_playlist
        api, calls = _fake_api({None: {"items": [_pl_item(0, "v1")], "nextPageToken": "p2"}})
        with patch("src.lambda_function._youtube_api", side_effect=api):
            result = _get_playlist("PLx", 1)
        assert result["truncated"] is True
        assert sum(1 for c in calls if c[0] == "playlistItems") == 1

    def test_not_found(self):
        from src.lambda_function import PlaylistError, _get_playlist
        with patch("src.lambda_function._youtube_api", return_value={"items": []}):
            with pytest.raises(PlaylistError, match="not found"):
                _get_playlist("PLx", 50)


class TestYouTubeApi:
    def test_sends_key_in_header_not_url(self):
        from src.lambda_function import _youtube_api
        resp = MagicMock()
        resp.read.return_value = b'{"items": []}'
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch("src.lambda_function._YOUTUBE_API_KEY_SECRET_NAME", "fn-yt"), \
             patch("src.lambda_function._youtube_api_key", None), \
             patch("src.lambda_function._get_secret_string", return_value="SECRETKEY\n") as mock_secret, \
             patch("urllib.request.urlopen", return_value=resp) as mock_open:
            _youtube_api("playlists", {"id": "PLx"})
            _youtube_api("playlists", {"id": "PLx"})
        mock_secret.assert_called_once_with("fn-yt")  # cached across calls
        req = mock_open.call_args[0][0]
        assert req.get_header("X-goog-api-key") == "SECRETKEY"
        assert "SECRETKEY" not in req.full_url
        assert req.full_url.startswith("https://www.googleapis.com/youtube/v3/playlists?")

    def test_http_error_message_is_surfaced(self):
        import io
        import urllib.error
        from src.lambda_function import PlaylistError, _youtube_api
        body = io.BytesIO(b'{"error": {"message": "API key not valid"}}')
        err = urllib.error.HTTPError("https://x", 400, "Bad Request", {}, body)
        with patch("src.lambda_function._YOUTUBE_API_KEY_SECRET_NAME", "fn-yt"), \
             patch("src.lambda_function._youtube_api_key", "k"), \
             patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(PlaylistError, match="400: API key not valid"):
                _youtube_api("playlists", {})

    def test_not_configured(self):
        from src.lambda_function import PlaylistError, _youtube_api
        with patch("src.lambda_function._YOUTUBE_API_KEY_SECRET_NAME", ""):
            with pytest.raises(PlaylistError, match="not configured"):
                _youtube_api("playlists", {})


class TestMcpPlaylistCall:
    def _call(self, args):
        from src.lambda_function import _handle_mcp
        return _handle_mcp({
            "jsonrpc": "2.0", "method": "tools/call", "id": 7,
            "params": {"name": "get_youtube_playlist", "arguments": args},
        })

    def test_returns_playlist_payload(self):
        fake = {"playlist": {"id": "PLx"}, "videos": [], "unavailable_skipped": 0, "truncated": False}
        with patch("src.lambda_function._get_playlist", return_value=fake) as mock_get:
            response = self._call({"url": "https://www.youtube.com/playlist?list=PLx", "max_videos": 10})
        mock_get.assert_called_once_with("PLx", 10)
        assert json.loads(response["result"]["content"][0]["text"]) == fake

    def test_default_max_videos(self):
        with patch("src.lambda_function._get_playlist", return_value={}) as mock_get:
            self._call({"url": "https://www.youtube.com/playlist?list=PLx"})
        mock_get.assert_called_once_with("PLx", 50)

    @pytest.mark.parametrize("args", [
        {"url": "https://www.youtube.com/watch?v=abc"},
        {"url": "https://www.youtube.com/playlist?list=PLx", "max_videos": 0},
        {"url": "https://www.youtube.com/playlist?list=PLx", "max_videos": 501},
        {"url": "https://www.youtube.com/playlist?list=PLx", "max_videos": "many"},
    ])
    def test_invalid_arguments(self, args):
        with patch("src.lambda_function._get_playlist") as mock_get:
            response = self._call(args)
        mock_get.assert_not_called()
        assert response["error"]["code"] == -32602

    def test_api_error_is_returned(self):
        from src.lambda_function import PlaylistError
        with patch("src.lambda_function._get_playlist", side_effect=PlaylistError("quota exceeded")):
            response = self._call({"url": "https://www.youtube.com/playlist?list=PLx"})
        assert response["error"]["code"] == -32603
        assert "quota exceeded" in response["error"]["message"]


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


# ---------------------------------------------------------------------------
# T5: OAuth token endpoint (authorization_code + refresh_token)
# ---------------------------------------------------------------------------

import base64
import hashlib
import urllib.parse


@pytest.fixture
def oauth():
    with patch("src.lambda_function._OAUTH_SECRET_NAME", "test-secret"), \
         patch("src.lambda_function._oauth_secret", "k" * 64):
        yield


def _token_request(params: dict) -> dict:
    from src.lambda_function import handler
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/token"}},
        "headers": {"content-type": "application/x-www-form-urlencoded", "host": "example.test"},
        "body": urllib.parse.urlencode(params),
    }
    result = handler(event, {})
    return result["statusCode"], json.loads(result["body"])


def _auth_code(verifier: str = "v" * 43) -> str:
    from src.lambda_function import _make_code
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return _make_code("claude-ai", "https://claude.ai/cb", challenge)


def _exchange_code() -> dict:
    status, body = _token_request({
        "grant_type": "authorization_code", "code": _auth_code(),
        "redirect_uri": "https://claude.ai/cb", "code_verifier": "v" * 43,
    })
    assert status == 200
    return body


class TestOAuthTokens:
    def test_code_exchange_returns_access_and_refresh_token(self, oauth):
        from src.lambda_function import _ACCESS_TOKEN_TTL_SECONDS, _verify_token
        body = _exchange_code()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == _ACCESS_TOKEN_TTL_SECONDS
        assert _verify_token(body["access_token"])
        assert body["refresh_token"]

    def test_refresh_returns_new_tokens(self, oauth):
        from src.lambda_function import _verify_token
        first = _exchange_code()
        status, body = _token_request({"grant_type": "refresh_token", "refresh_token": first["refresh_token"]})
        assert status == 200
        assert _verify_token(body["access_token"])
        assert body["refresh_token"]

    def test_refresh_token_is_not_an_access_token(self, oauth):
        from src.lambda_function import _verify_token
        body = _exchange_code()
        assert not _verify_token(body["refresh_token"])

    def test_access_token_cannot_be_used_to_refresh(self, oauth):
        body = _exchange_code()
        status, err = _token_request({"grant_type": "refresh_token", "refresh_token": body["access_token"]})
        assert status == 400 and err["error"] == "invalid_grant"

    def test_tampered_refresh_token_rejected(self, oauth):
        status, err = _token_request({"grant_type": "refresh_token", "refresh_token": "garbage"})
        assert status == 400 and err["error"] == "invalid_grant"

    def test_expired_refresh_token_rejected(self, oauth):
        body = _exchange_code()
        with patch("src.lambda_function.time.time", return_value=10**12):
            status, err = _token_request({"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        assert status == 400 and err["error"] == "invalid_grant"

    def test_refresh_with_wrong_client_id_rejected(self, oauth):
        body = _exchange_code()
        status, err = _token_request({
            "grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": "other",
        })
        assert status == 400 and err["error"] == "invalid_grant"

    def test_legacy_access_token_without_type_still_valid(self, oauth):
        import time as _time
        from src.lambda_function import _sign, _b64url, _verify_token
        payload = json.dumps({"c": "claude-ai", "e": int(_time.time()) + 60}, separators=(",", ":"))
        assert _verify_token(_b64url((payload + "." + _sign(payload)).encode()))

    def test_unsupported_grant_type(self, oauth):
        status, err = _token_request({"grant_type": "password"})
        assert status == 400 and err["error"] == "unsupported_grant_type"

    def test_metadata_advertises_refresh(self, oauth):
        from src.lambda_function import handler
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/.well-known/oauth-authorization-server"}},
            "headers": {"host": "example.test"},
        }
        meta = json.loads(handler(event, {})["body"])
        assert "refresh_token" in meta["grant_types_supported"]
        assert "offline_access" in meta["scopes_supported"]

    def test_token_body_is_not_logged(self, oauth, caplog):
        import logging
        body = _exchange_code()
        with caplog.at_level(logging.INFO):
            _token_request({"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
        assert body["refresh_token"] not in caplog.text
        assert "grant_type=refresh_token" in caplog.text
