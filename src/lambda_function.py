import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.parse

import urllib.request

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_YOUTUBE_PATTERN = re.compile(
    r"^https?://(www\.|m\.)?youtube\.com/watch\?.*v=|^https?://youtu\.be/"
)

_WEBSHARE_USERNAME = (os.environ.get("WEBSHARE_USERNAME") or "").strip()
_WEBSHARE_PASSWORD = (os.environ.get("WEBSHARE_PASSWORD") or "").strip()

_OAUTH_SECRET_NAME = (os.environ.get("OAUTH_SECRET_NAME") or "").strip()
_oauth_secret: str | None = None


# ---------------------------------------------------------------------------
# YouTube extraction
# ---------------------------------------------------------------------------

def _validate_youtube_url(url: str) -> None:
    if not url or not _YOUTUBE_PATTERN.match(url):
        raise ValueError(f"Not a valid YouTube URL: {url!r}")


def _get_metadata(url: str) -> dict:
    # YouTube oEmbed API: no auth, no bot detection, returns title/channel/thumbnail
    oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"})
    with urllib.request.urlopen(oembed_url, timeout=10) as resp:
        data = json.loads(resp.read())
    return {
        "title": data.get("title"),
        "channel": data.get("author_name"),
        "thumbnail": data.get("thumbnail_url"),
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
    if _WEBSHARE_USERNAME and _WEBSHARE_PASSWORD:
        proxy_config = WebshareProxyConfig(_WEBSHARE_USERNAME, _WEBSHARE_PASSWORD)
    else:
        proxy_config = None
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

    try:
        transcript = _get_transcript(video_id)
    except Exception as exc:
        logger.error("Transcript fetch failed: %s", exc)
        return _jsonrpc_error(id_, -32603, f"Transcript unavailable: {exc}")

    payload = {"url": url, "metadata": metadata, "transcript": transcript}
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }


def _extract_video_id(url: str) -> str:
    m = re.search(r"youtu\.be/([^?&/]+)", url)
    if m:
        return m.group(1)
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
# OAuth 2.0 (Authorization Code + PKCE S256, stateless HMAC tokens)
# ---------------------------------------------------------------------------

def _load_oauth_secret() -> str:
    global _oauth_secret
    if _oauth_secret is None:
        import boto3
        _oauth_secret = boto3.client("secretsmanager").get_secret_value(
            SecretId=_OAUTH_SECRET_NAME
        )["SecretString"]
    return _oauth_secret


def _sign(payload: str) -> str:
    key = _load_oauth_secret().encode()
    return hmac.new(key, payload.encode(), digestmod=hashlib.sha256).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _make_code(client_id: str, redirect_uri: str, code_challenge: str) -> str:
    payload = json.dumps(
        {"c": client_id, "r": redirect_uri, "k": code_challenge, "e": int(time.time()) + 300},
        separators=(",", ":"),
    )
    return _b64url((payload + "." + _sign(payload)).encode())


def _verify_code(code: str, redirect_uri: str, code_verifier: str) -> tuple[str | None, str | None]:
    try:
        raw = _b64url_decode(code).decode()
        payload_str, sig = raw.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload_str)):
            return None, "invalid_grant"
        p = json.loads(payload_str)
        if int(time.time()) > p["e"]:
            return None, "invalid_grant"
        if p["r"] != redirect_uri:
            return None, "invalid_grant"
        challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
        if not hmac.compare_digest(challenge, p["k"]):
            return None, "invalid_grant"
        return p["c"], None
    except Exception:
        return None, "invalid_grant"


def _make_token(client_id: str) -> str:
    payload = json.dumps({"c": client_id, "e": int(time.time()) + 3600}, separators=(",", ":"))
    return _b64url((payload + "." + _sign(payload)).encode())


def _verify_token(token: str) -> bool:
    try:
        raw = _b64url_decode(token).decode()
        payload_str, sig = raw.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload_str)):
            return False
        return int(time.time()) <= json.loads(payload_str)["e"]
    except Exception:
        return False


def _oauth_protected_resource(base_url: str) -> dict:
    return _response(200, {"resource": base_url, "authorization_servers": [base_url]})


def _oauth_authorization_server(base_url: str) -> dict:
    return _response(200, {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


def _oauth_register(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "invalid_request"})
    return _response(201, {
        "client_id": "claude-ai",
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })


def _oauth_authorize(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    if qs.get("code_challenge_method", "") != "S256":
        return _response(400, {"error": "invalid_request", "error_description": "Only S256 PKCE is supported"})
    code = _make_code(
        qs.get("client_id", ""),
        qs.get("redirect_uri", ""),
        qs.get("code_challenge", ""),
    )
    location = qs.get("redirect_uri", "") + "?" + urllib.parse.urlencode(
        {"code": code, "state": qs.get("state", "")}
    )
    return {"statusCode": 302, "headers": {"Location": location}, "body": ""}


def _oauth_token(event: dict) -> dict:
    body_raw = event.get("body") or ""
    ct = (event.get("headers") or {}).get("content-type", "")
    if "application/x-www-form-urlencoded" in ct:
        params = dict(urllib.parse.parse_qsl(body_raw))
    else:
        try:
            params = json.loads(body_raw)
        except (json.JSONDecodeError, TypeError):
            params = {}
    if params.get("grant_type") != "authorization_code":
        return _response(400, {"error": "unsupported_grant_type"})
    client_id, err = _verify_code(
        params.get("code", ""),
        params.get("redirect_uri", ""),
        params.get("code_verifier", ""),
    )
    if err:
        return _response(400, {"error": err})
    return _response(200, {
        "access_token": _make_token(client_id),
        "token_type": "Bearer",
        "expires_in": 3600,
    })


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    # Lambda Function URL base64-encodes bodies with non-text content types (e.g. application/x-www-form-urlencoded)
    if event.get("isBase64Encoded") and event.get("body"):
        event = {**event, "body": base64.b64decode(event["body"]).decode("utf-8", errors="replace"), "isBase64Encoded": False}

    headers_raw = event.get("headers") or {}
    http_method = (event.get("requestContext", {}).get("http", {}).get("method")
                   or event.get("httpMethod") or "POST")
    path = (event.get("requestContext", {}).get("http", {}).get("path")
            or event.get("rawPath") or "/")
    host = headers_raw.get("host", "")
    base_url = f"https://{host}"

    logger.info("REQ %s %s body=%s", http_method, path, (event.get("body") or "")[:500])

    # OAuth 2.0 endpoints (no Bearer required)
    if _OAUTH_SECRET_NAME:
        if http_method == "GET" and path == "/.well-known/oauth-protected-resource":
            return _oauth_protected_resource(base_url)
        if http_method == "GET" and path == "/.well-known/oauth-authorization-server":
            return _oauth_authorization_server(base_url)
        if http_method == "POST" and path == "/register":
            return _oauth_register(event)
        if http_method == "GET" and path == "/authorize":
            return _oauth_authorize(event)
        if http_method == "POST" and path == "/token":
            return _oauth_token(event)

    # MCP endpoint
    if http_method != "POST" or path != "/":
        return _response(404, {"error": "Not found"})

    # Bearer token validation
    if _OAUTH_SECRET_NAME:
        auth = headers_raw.get("authorization", "")
        if not auth.startswith("Bearer ") or not _verify_token(auth[7:]):
            return _response(401, {"error": "Unauthorized"})

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
