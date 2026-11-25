# claude-youtube-transcript

A remote MCP server that adds YouTube video comprehension to [Claude](https://claude.ai) — something Gemini has natively but Claude doesn't. Paste a YouTube URL in a Claude chat, and Claude fetches the transcript + metadata to reason about the video.

Runs as a single AWS Lambda function exposed via a Function URL, protected by OAuth2 (Authorization Code + PKCE S256).

See [SPEC.md](SPEC.md) for the full contract and [CLAUDE.md](CLAUDE.md) for implementation notes.

## Architecture

```
Claude Web
  └─ MCP (Streamable HTTP over HTTPS)
       └─ Lambda Function URL (eu-south-1)
            ├─ OAuth2 Authorization Code + PKCE S256
            │    └─ signing secret in AWS Secrets Manager
            ├─ YouTube oEmbed API       → metadata (title, channel, thumbnail)
            ├─ youtube-transcript-api  → timestamped transcript (via Webshare proxy)
            │    └─ proxy credentials in AWS Secrets Manager
            └─ YouTube Data API v3      → playlist contents
                 └─ API key in AWS Secrets Manager
```

The handler is a single file: [`src/lambda_function.py`](src/lambda_function.py).

## MCP tools

| Tool | Input | Output |
|---|---|---|
| `get_youtube_transcript` | `url: string` | `{ url, metadata, transcript[] }` |
| `get_youtube_playlist` | `url: string`, `max_videos?: integer` (default 50, max 500) | `{ playlist, videos[], unavailable_skipped, truncated }` |

For a playlist, Claude first lists the videos with `get_youtube_playlist`, then calls `get_youtube_transcript` on the ones it needs. Private and deleted videos are skipped.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (Python package manager)
- `aws` CLI (authenticated)
- `zip`, `openssl`

## Local development

```bash
uv sync           # install deps
uv run pytest     # run the test suite
```

## First-time deploy

```bash
bash scripts/bootstrap.sh
```

Creates in order: IAM role, S3 deploy bucket, OAuth signing secret, Webshare proxy secret and YouTube API key secret (Secrets Manager), Lambda function, Function URL, resource-based policies.

## Update code

```bash
bash scripts/deploy.sh
```

Syncs the Webshare and YouTube API key secrets from `.env`, rebuilds the zip, uploads to S3, updates Lambda code and environment variables.

## Tear down

```bash
bash scripts/destroy.sh          # asks you to type the function name to confirm
bash scripts/destroy.sh --yes    # no prompt
```

Deletes everything `bootstrap.sh` created: Lambda function and Function URL, the OAuth, Webshare and YouTube API key secrets, the IAM role with its policies, and the S3 deploy bucket. The Webshare credentials and the YouTube API key stay in `.env`.

> **The Claude connector stops working and must be set up again.** A new `bootstrap.sh` creates a new Function URL and a new OAuth signing key, so existing tokens are invalid. In Claude, remove the connector and add it again with the new URL (see [Connect to Claude](#connect-to-claude)).

## Connect to Claude

1. In Claude → **Settings → Connectors → Add custom connector**.
2. URL: the Function URL printed by `bootstrap.sh`.
3. Click **Connect** — Claude opens an OAuth consent flow, which auto-approves (single-user server).
4. In a chat: _"summarize https://www.youtube.com/watch?v=..."_ or _"which videos in https://www.youtube.com/playlist?list=... cover X?"_.

## Configuration

All values live in `.env` (gitignored). Copy `.env.example`, restrict it to your user (it holds the Webshare credentials and the YouTube API key), and fill in:

```bash
cp .env.example .env && chmod 600 .env
```


| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_DEFAULT_REGION` | no | `eu-south-1` | AWS region |
| `FUNCTION_NAME` | yes | — | Lambda function name |
| `LAMBDA_ROLE_NAME` | yes | — | IAM execution role name |
| `DEPLOY_BUCKET` | no | `<FUNCTION_NAME>-deploy-<account-id>` | S3 bucket for deployment zips |
| `LAMBDA_MEMORY` | no | `256` | Lambda memory in MB |
| `ACCESS_TOKEN_TTL_HOURS` | no | `4` | OAuth access token lifetime in hours; Claude refreshes it automatically |
| `REFRESH_TOKEN_TTL_DAYS` | no | `30` | OAuth refresh token lifetime in days; a new one is issued on every renewal, so you only reconnect after this many days of inactivity |
| `WEBSHARE_USERNAME` | recommended on AWS | `` | Webshare **Residential** proxy username, stored in Secrets Manager by the scripts (see below) |
| `WEBSHARE_PASSWORD` | recommended on AWS | `` | Webshare **Residential** proxy password, stored in Secrets Manager by the scripts (see below) |
| `YOUTUBE_API_KEY` | for playlists | `` | YouTube Data API v3 key, stored in Secrets Manager by the scripts (see below) |

### Webshare proxy

YouTube blocks most requests for transcripts that come from cloud-provider IPs (AWS included). Without a proxy, the transcript tool on Lambda typically fails with `RequestBlocked` / `IpBlocked`. `youtube-transcript-api` has built-in support for [Webshare](https://www.webshare.io/) rotating residential proxies.

1. Create a Webshare account and buy a **Residential** plan. The "Proxy Server" (datacenter) and "Static Residential" plans do **not** work: YouTube blocks those IPs too.
2. In the dashboard, open **Residential → Proxy Settings** and copy **Proxy Username** and **Proxy Password**. These are proxy credentials, *not* your Webshare account login.
3. Put them in `.env` as `WEBSHARE_USERNAME` / `WEBSHARE_PASSWORD` and run `bash scripts/bootstrap.sh` (first time) or `bash scripts/deploy.sh`.

The scripts store the credentials in the Secrets Manager secret `<FUNCTION_NAME>-webshare` as JSON `{"username": ..., "password": ...}` and grant the Lambda role read access to it. The Lambda only receives the secret name (`WEBSHARE_SECRET_NAME`). It reads the secret on the first transcript request and caches it per container.

Notes:

- **Set both variables or neither.** The scripts stop with an error if only one is set.
- **Keep the credentials in `.env`.** They are read only by `bootstrap.sh` and `deploy.sh`, which write them to the secret on every run, and are never passed to the Lambda. To rotate, change the values in `.env` and run `deploy.sh` again.
- If there is no secret, the proxy is disabled and a warning is logged at cold start (visible in CloudWatch). The same happens if the secret is missing `username` or `password`.
- Only transcript fetches go through the proxy. Metadata comes from the oEmbed API directly.

### YouTube Data API key (playlists)

`get_youtube_playlist` uses the [YouTube Data API v3](https://developers.google.com/youtube/v3), which needs an API key. Transcripts don't, so this is optional: without a key the playlist tool returns an error and everything else works.

1. In the [Google Cloud Console](https://console.cloud.google.com/), create (or pick) a project and enable **YouTube Data API v3** (APIs & Services → Library).
2. APIs & Services → **Credentials → Create credentials → API key**. Edit the key and, under **API restrictions**, restrict it to YouTube Data API v3. Leave application restrictions at "None": Lambda has no fixed IP.
3. Put it in `.env` as `YOUTUBE_API_KEY` and run `bash scripts/deploy.sh`.

The scripts store it in the Secrets Manager secret `<FUNCTION_NAME>-youtube-api-key` and grant the Lambda role read access; the Lambda only receives the secret name (`YOUTUBE_API_KEY_SECRET_NAME`) and sends the key in a request header, never in the URL. The free quota is 10,000 units per day, and listing a playlist costs 1 unit plus 1 per 50 videos.

## Gotchas

- **Public Function URL requires two resource-policy statements**: both `lambda:InvokeFunction` and `lambda:InvokeFunctionUrl` must be granted to principal `*`. Missing the first yields a generic 403 with no CloudWatch trace.
- **`boto3` is not a deployment dependency**: it ships with the Lambda runtime. It's dev-only so tests can mock it.
- **Lambda base64-encodes `application/x-www-form-urlencoded` bodies**: the OAuth `/token` endpoint decodes them automatically via `isBase64Encoded`.
- **OAuth tokens are stateless**: signed with HMAC-SHA256 using a secret in Secrets Manager. No database required. Claude renews the access token with the refresh token, so you only reconnect if the refresh token expires or the OAuth secret changes. The flip side of statelessness: tokens can't be revoked individually, only all at once by rotating the OAuth secret.
- **Secrets are cached per Lambda container**: after rotating the Webshare credentials or the YouTube API key, `deploy.sh` updates the function configuration, which forces fresh containers. If you change the secret by hand instead, warm containers keep the old value until they are recycled.

## License

MIT.
