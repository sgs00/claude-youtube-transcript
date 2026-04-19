import json
import logging
import os
import re

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_YOUTUBE_PATTERN = re.compile(
    r"^https?://(www\.|m\.)?youtube\.com/watch\?.*v=|^https?://youtu\.be/"
)

_PROXY_URL = (os.environ.get("PROXY_URL") or "").rstrip("/") or None
if _PROXY_URL:
    os.environ.setdefault("HTTP_PROXY", _PROXY_URL)
    os.environ.setdefault("HTTPS_PROXY", _PROXY_URL)


# ---------------------------------------------------------------------------
# YouTube extraction
# ---------------------------------------------------------------------------

def _validate_youtube_url(url: str) -> None:
    if not url or not _YOUTUBE_PATTERN.match(url):
        raise ValueError(f"Not a valid YouTube URL: {url!r}")


def _get_metadata(url: str) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if _PROXY_URL:
        opts["proxy"] = _PROXY_URL
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title"),
        "channel": info.get("uploader"),
        "duration": info.get("duration"),
        "views": info.get("view_count"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail"),
    }


def _seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _get_transcript(video_id: str) -> list:
    languages = ["en", "en-US", "en-GB", "a.en", "de", "fr", "es", "it", "pt", "ja", "ko", "zh"]
    proxy_config = GenericProxyConfig(_PROXY_URL, _PROXY_URL) if _PROXY_URL else None
    api = YouTubeTranscriptApi(proxy_config=proxy_config)
    transcript = api.fetch(video_id, languages)
    return [
        {
            "timestamp": _seconds_to_timestamp(snippet.start),
            "start_seconds": snippet.start,
            "duration_seconds": snippet.duration,
            "text": snippet.text,
        }
        for snippet in transcript
    ]


# ---------------------------------------------------------------------------
# MCP protocol (JSON-RPC 2.0, Streamable HTTP, spec 2025-03-26)
# ---------------------------------------------------------------------------

_TOOL_SCHEMA = {
    "name": "get_youtube_transcript",
    "description": (
        "Fetches the transcript and metadata of a YouTube video. "
        "Returns title, channel, duration, view count, description, thumbnail, "
        "and the full transcript as timestamped segments."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full YouTube video URL (youtube.com/watch?v=... or youtu.be/...)",
            }
        },
        "required": ["url"],
    },
}


def _jsonrpc_error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _mcp_initialize(request: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {
            "protocolVersion": "2025-11-25",
            "serverInfo": {"name": "claude-youtube-transcript", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        },
    }


def _mcp_tools_list(request: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {"tools": [_TOOL_SCHEMA]},
    }


def _mcp_tools_call(request: dict) -> dict:
    id_ = request.get("id")
    params = request.get("params", {})
    tool_name = params.get("name")

    if tool_name != "get_youtube_transcript":
        return _jsonrpc_error(id_, -32601, f"Unknown tool: {tool_name!r}")

    args = params.get("arguments", {})
    url = args.get("url", "")

    try:
        _validate_youtube_url(url)
    except ValueError as exc:
        return _jsonrpc_error(id_, -32602, str(exc))

    video_id = _extract_video_id(url)

    try:
        metadata = _get_metadata(url)
    except Exception as exc:
        logger.warning("Metadata fetch failed (bot detection?): %s", exc)
        metadata = {}

    transcript = _get_transcript(video_id)

    payload = {"url": url, "metadata": metadata, "transcript": transcript}
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }


def _extract_video_id(url: str) -> str:
    # youtu.be/<id>
    m = re.search(r"youtu\.be/([^?&/]+)", url)
    if m:
        return m.group(1)
    # youtube.com/watch?v=<id>
    m = re.search(r"[?&]v=([^?&/]+)", url)
    if m:
        return m.group(1)
    return url


def _handle_mcp(request: dict) -> dict:
    method = request.get("method")
    if method == "initialize":
        return _mcp_initialize(request)
    if method == "tools/list":
        return _mcp_tools_list(request)
    if method == "tools/call":
        return _mcp_tools_call(request)
    return _jsonrpc_error(request.get("id"), -32601, f"Method not found: {method!r}")


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    headers_raw = event.get("headers") or {}
    http_method = (event.get("requestContext", {}).get("http", {}).get("method")
                   or event.get("httpMethod") or "POST")
    path = (event.get("requestContext", {}).get("http", {}).get("path")
            or event.get("rawPath") or "/")
    logger.info("REQ %s %s body=%s", http_method, path, (event.get("body") or "")[:500])

    # Only handle POST to /; return 404 for OAuth discovery probes and other paths
    if http_method != "POST" or path != "/":
        return _response(404, {"error": "Not found"})

    body_raw = event.get("body") or ""
    try:
        body = json.loads(body_raw)
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Request body must be valid JSON"})

    try:
        result = _handle_mcp(body)
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, result)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
