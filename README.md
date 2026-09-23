# LinkedIn Personal Archive

Docker worker for your own LinkedIn posts: regular API sync, MariaDB,
permanently stored images, and preserved person, company and other links.
Post text is stored both as plain text and as sanitized HTML. An HTTP API and a
WordPress shortcode make approved posts usable on your own website. The worker
itself never publishes anything.

## What's included

- Initial historical import via the Member Snapshot API (`MEMBER_SHARE_INFO`).
- Ongoing new/changed/deleted own posts via the Changelog API.
- Additional daily snapshot sync; page enrichment for new, changed, failed and
  older posts.
- Direct fetch of the public post page; Chromium/Playwright as fallback.
- HTML with real links instead of guessed profile matches. Tracking parameters
  are stripped from LinkedIn links; hashtag sign-in links are resolved to the
  actual LinkedIn hashtag target where possible.
- Images, directly offered MP4/WebM videos and PDF files. File hash, file type,
  order, alt text, origin and download status are stored.
- Reactions and comment counts from the public post page, with the timestamp
  of the last successful fetch. For manually fetched posts, the publication
  date is filled in from the page's structured data.
- Read API for approved posts and images, plus a protected raw data endpoint.
- WordPress plugin with responsive post cards and preserved links.
- Repeatable imports, transactions, a lock against parallel workers, resume
  after restarts and limited retries on API errors.
- CLI for single fetch, JSON import, status and export.

## Quick start

Requirement: Docker Engine/Desktop with Docker Compose v2 or newer.

```bash
cp docker-compose.yml-example docker-compose.yml
cp .env-example .env
chmod 600 .env
mkdir -p secrets
```

Edit `.env`: enter a **new** LinkedIn access token, two different random
database passwords and a separate `API_READ_KEY`. For example,
`openssl rand -hex 32` produces a suitable password. If a local `.env` with
generated passwords already exists, use it and do not overwrite it.

```dotenv
LINKEDIN_ACCESS_TOKEN=YOUR_OAUTH_ACCESS_TOKEN
MARIADB_PASSWORD=YOUR_RANDOM_DATABASE_PASSWORD
MARIADB_ROOT_PASSWORD=A_DIFFERENT_RANDOM_ROOT_PASSWORD
API_READ_KEY=A_THIRD_RANDOM_VALUE
SYNC_INTERVAL_SECONDS=3600
```

Then:

```bash
docker compose up -d --build
docker compose logs -f archive
docker compose exec archive python -m linkedin_archiver status
curl http://127.0.0.1:8080/health
```

MariaDB is only reachable inside the Compose network; no database port is
published on the host. By default the website API only listens on
`127.0.0.1:8080`. The image runs as `pwuser`, not as root. Chromium needs some
memory; Compose reserves 512 MB of shared memory.

The first import may take several runs: by default, at most 20 post pages are
enriched per run. API metadata is read in full regardless. There are at least
five seconds between page requests. A cycle starts immediately and then after
each configured pause; cycles never overlap.

## LinkedIn: how do I get API access?

What you need is an **OAuth access token**, not the client ID or client secret.
For your own profile in Switzerland or the EU/EEA, LinkedIn provides the
**Member Data Portability API (Member)** product.

1. Open the [Developer Portal](https://www.linkedin.com/developers/) with your
   own LinkedIn account and create a new app.
2. In the "LinkedIn Page" field, select exactly the designated
   [Member Data Portability Default Company](https://www.linkedin.com/company/member-data-portability-member-default-company).
   LinkedIn requires this special page; do not create a new company.
3. Fill in the remaining required fields of the form.
4. Under "Products", select **Member Data Portability API (Member)** and apply
   via "Request access"; read the associated terms.
5. Under "Docs and tools", open the
   [OAuth Token Tools](https://www.linkedin.com/developers/tools/oauth).
6. Choose "Create token", the app you just created and the scope
   **`r_dma_portability_self_serve`**; run "Request access token" and consent
   to access to your own data.
7. Enter the generated token only locally in `LINKEDIN_ACCESS_TOKEN` in `.env`.

The [official setup guide](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/)
describes these steps. LinkedIn determines regional eligibility from the
profile location. Access is intended for your own member data.

### Token expiry and replacement

Tokens can expire or be revoked. On HTTP 401/403 the worker reports an error;
already stored data is kept. Create a new token via the token tool, update
`.env` and **recreate** the container:

```bash
docker compose up -d --force-recreate archive
```

`docker compose restart` does not pick up changed environment variables.
Automatic token renewal is not assumed; member access does not necessarily
provide a refresh token. Client secrets are not needed for this manual token
workflow.

`.env`, cookies and data are excluded from Git and Docker builds. Tokens are
never written to the database or export files. A token that was previously
pasted into a chat should be revoked and replaced.

## Configuration in .env

| Variable | Default | Meaning |
|---|---:|---|
| `LINKEDIN_ACCESS_TOKEN` | required | OAuth token for the Member Portability API |
| `SYNC_INTERVAL_SECONDS` | 3600 | Pause between completed runs |
| `SNAPSHOT_INTERVAL_SECONDS` | 86400 | Interval for the historical sync |
| `POST_REFRESH_DAYS` | 1 | Shortest interval between two page visits |
| `MAX_POST_REFRESH_DAYS` | 30 | Longest interval; in between it grows with the post's age |
| `RETRY_INTERVAL_SECONDS` | 3600 | First retry interval after an error; doubles with each attempt |
| `MAX_RETRY_INTERVAL_SECONDS` | 86400 | Upper bound for this growing interval |
| `MAX_POSTS_PER_CYCLE` | 20 | Maximum page enrichments per run |
| `PAGE_DELAY_SECONDS` | 5 | Delay between post pages |
| `REQUEST_TIMEOUT_SECONDS` | 45 | Timeout per network/browser operation |
| `MAX_API_PAGES` | 10000 | Guard against endless API pagination |
| `PAGE_ENRICHMENT_ENABLED` | true | Read pages for links and media |
| `BROWSER_FALLBACK_ENABLED` | true | Try Chromium when HTTP is not enough |
| `BROWSER_STORAGE_STATE` | empty | Optional `/run/secrets/linkedin-state.json` |
| `AUTO_PUBLISH` | false | Approve newly imported posts immediately instead of individually with `publish` |
| `DOWNLOAD_MEDIA` | true | Permanently download reachable media files |
| `MAX_MEDIA_SIZE_MB` | 100 | Size limit per file |
| `MEDIA_ALLOWED_HOSTS` | licdn.com,linkedin.com | Allowed media hosts, including subdomains |
| `LOG_LEVEL` | INFO | Python log level |
| `DB_HOST` / `DB_PORT` | db / 3306 | MariaDB connection |
| `MARIADB_DATABASE` / `MARIADB_USER` | linkedin_archive / linkedin | Database and user |
| `MARIADB_PASSWORD` | required | Password of the application user |
| `MARIADB_ROOT_PASSWORD` | required | Password for initializing the Compose DB |
| `API_READ_KEY` | required for raw data | Secret for `X-Archive-Key`; do not use in the browser |
| `API_BIND_ADDRESS` / `API_PORT` | 127.0.0.1 / 8080 | Bind address and host port of the website API |
| `API_PUBLIC_BASE_URL` | http://localhost:8080 | Public base URL from which image URLs are built |
| `API_ALLOWED_ORIGIN` | https://www.example.net | Allowed browser origin for CORS |

For example, to download external preview images from Credly or a linked PDF,
add the respective host to the list, such as `images.credly.com`. The list
controls both: media from unlisted hosts is not recorded as an attachment at
all, rather than failing to download again on every run. They are still kept
as links in the post text. OAuth headers are sent exclusively to
`api.linkedin.com`, never to media hosts.

## How are person and company links preserved?

The snapshot alone often provides only text. The public post page, however,
contains real `<a href="…">Name</a>` elements. The following is stored:

- `posts.content_html`: sanitized post with these links and paragraphs.
- `posts.content_text`: plain text for search and previews.
- `post_links`: target, label, order and type (`person`, `organization`,
  `hashtag`, `external`).

The HTML is reduced to text, paragraphs, simple emphasis and HTTP(S) links.
Event handlers, scripts, embedded frames and `javascript:` links are removed.
To preserve line breaks later, use for example `.post-body { white-space: pre-wrap; }`.
Only render `content_html`, not `raw_page_fragment` or raw API data.

### How often are counters updated?

The interval depends on the post's age: roughly a tenth of it, bounded below by
`POST_REFRESH_DAYS` and above by `MAX_POST_REFRESH_DAYS`. A post from yesterday
is checked daily, one from three months ago every nine days, a post that is
years old every 30 days. This matches the actual pattern: reactions and
comments arrive almost exclusively in the first few days.

If a fetch fails, the interval doubles with each further failed attempt for the
same post (1 h, 2 h, 4 h … up to `MAX_RETRY_INTERVAL_SECONDS`). A successful
fetch resets the counter. Without this backoff, permanently unreadable posts
would occupy the same slots in every cycle and crowd out refreshing the rest.

The counters are total LinkedIn *reactions*, not just "Like" reactions. Where
possible, exact numbers are read from the structured post data. If a counter
is also missing from the public HTML, its database field stays `NULL`; the API
does not invent a zero. `engagement_updated_at` shows the last detected state.
With `POST_REFRESH_DAYS=1`, successfully read posts are queued again after one
day; processing happens up to `MAX_POSTS_PER_CYCLE` per cycle.

## Media and limitations

In the account data examined here, `MediaUrl` or `Media Link` was often empty.
The worker therefore uses the actual media attributes of the post page. Images
are loaded from the post's image container, including `data-delayed-url` and
`srcset`, instead of collecting all images on a page.

Files are stored under `/data/media/<hash prefix>/<SHA256>.<extension>`;
identical bytes are stored only once. The SQL mapping contains the original
URL, position and download status. Signed CDN URLs may expire; a successfully
stored local file remains available regardless.

**No guarantee of original resolution:** the largest directly offered image
variant is saved. For example, the public page of the cat litter box post
delivered 800 × 600 pixels. Signatures and size parameters are not tampered
with. Already stored files are not downloaded again on repeat runs, unless the
local file is missing or the asset ID changes.

Videos/PDFs are only downloaded if the page exposes direct, supported file
URLs. HLS/DASH, hidden carousel pages, internal document viewers, external
embeds and protected original files are not fully supported media archives.
`complete` means the **detected** media was processed; it does not prove that
LinkedIn delivers all attachments. Native long-form LinkedIn articles/newsletters
(`/pulse/`) are not imported as complete articles in this version; the focus is
on feed posts.

Posts without their own text — such as a shared article or a certificate —
have no commentary field on the page. They are archived anyway: the article's
title and target go into `post_links`, the preview image into `post_media`
with the role `preview`, and `content_text` stays empty rather than being made
up. LinkedIn's click redirect `/redir/redirect?url=…` is resolved to the
actual target address.

LinkedIn may restrict public pages or change their HTML. In that case the API
texts are kept, and the error is visible via `status`. A missing snapshot or a
login page is not treated as a deletion. Only a matching own DELETE event marks
a post as deleted; its archive remains, but it disappears from exports.

Page fetching falls under LinkedIn's rules for automated access.
[LinkedIn prohibits scraping tools](https://www.linkedin.com/help/lms/answer/a1341387).
With `PAGE_ENRICHMENT_ENABLED=false`, operation can be limited to the official
API; if the API media fields are empty, images and mention links will then be
missing.

## API pagination and ongoing sync

The [Snapshot API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api)
requires the header `Linkedin-Version: 202312`. The value is fixed on purpose.
Its `start` parameter is a page index; the reported total is not always
complete. The worker keeps reading until an empty response or "No data found
for this memberId" and treats repeated pages as an error.

The [Changelog API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-changelog-api)
delivers events from the time of consent with a 28-day lookback window. The
worker uses `processedAt` as an inclusive checkpoint, deduplicates events and
only writes the checkpoint after all result pages have been processed
successfully. Comments, likes and events by other authors are not stored as
own posts. Outages longer than 28 days may lead to changes/deletion events that
cannot be reconstructed.

The initial snapshot may still be empty right after consent. New or edited
posts may become available at LinkedIn with a delay. Polling intervals are
therefore no guarantee of up-to-the-second freshness.

## Commands

Single API run or forced snapshot (stop the running worker first if needed; a
database lock prevents parallel processing):

```bash
docker compose run --rm archive sync
docker compose run --rm archive sync --force-snapshot
docker compose run --rm archive enrich
```

Read a specific own post directly, even without an API token:

```bash
docker compose run --rm archive fetch \
  'https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A6978966287410470912'
```

Import an existing API JSON response (JSON only, no terminal transcript):

```bash
docker compose run --rm \
  -v "$PWD/linkedin-posts.json:/import/posts.json:ro" \
  archive import-json /import/posts.json
docker compose run --rm archive enrich
```

## Data for your own website

A private full export contains all posts not marked as deleted:

```bash
docker compose exec archive python -m linkedin_archiver export
docker compose cp archive:/data/export/archive.json ./archive.json
docker compose cp archive:/data/media ./media
```

Select posts before publishing. `MEMBER_NETWORK` is not a reliable approval for
a public website. That is why there is an additional, separate
`publish_enabled` flag that is disabled by default:

```bash
docker compose exec archive python -m linkedin_archiver publish 'urn:li:share:6978966287410470912'
docker compose exec archive python -m linkedin_archiver export --published-only
docker compose cp archive:/data/export/website.json ./website.json
```

`publish` only changes the selection in your own database. It publishes nothing
on LinkedIn or on a website. Undo with `publish <URN> --disable`.

### Automatically approve all new posts

If you don't want to select posts individually, set `AUTO_PUBLISH=true` in
`.env` and recreate the container. Every post imported **afterwards** is
immediately available via the website endpoints and `export --published-only`.

This removes per-post control: posts with `MEMBER_NETWORK` visibility, which
on LinkedIn only your own network can see, will then also end up on the public
website automatically.

The setting only applies when a post is first created:

- Already archived posts remain unchanged and still need `publish`.
- A post withdrawn with `publish <URN> --disable` is not re-approved by a later
  snapshot or changelog sync.
- Deleted posts are never approved.

`AUTO_PUBLISH` does not retroactively approve existing posts. If you want that,
run this once in MariaDB:

```bash
docker compose exec -T db sh -c \
  'exec mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' <<'SQL'
UPDATE posts SET publish_enabled = TRUE WHERE deleted_at IS NULL;
SQL
```

Each JSON post contains `post_key`, URLs, timestamp, visibility, `content_html`,
`content_text`, `links` and `media`. Media entries have a `local_url` such as
`/media/ab/abcdef….jpg`. The website can serve the media directory under
`/media/` or copy the files to its own object storage.

Alternatively, read directly from MariaDB:

```sql
SELECT post_key, published_at, content_text, content_html
FROM posts
WHERE publish_enabled = TRUE AND deleted_at IS NULL
ORDER BY published_at DESC;
```

For a direct MariaDB connection from the website, set up a separate user with
SELECT privileges only.
Never deliver OAuth tokens, browser cookies or raw data to the frontend. The
raw data is meant for later reprocessing, not as ready-made HTML.

## HTTP API for the website

The Compose service `api` only reads data. By default it shows **no** posts:
only `publish <URN>` approves a post for the website endpoints and media files
— or `AUTO_PUBLISH=true` for all newly imported ones. Deleted posts do not
appear there. Initially the API is only reachable on the Docker host at
`http://127.0.0.1:8080`.

| Endpoint | Result |
|---|---|
| `GET /health` | Check the database connection |
| `GET /api/v1/posts?limit=12&offset=0` | Approved posts, paginated, ready for display |
| `GET /api/v1/posts/urn%3Ali%3Ashare%3A6978966287410470912` | A single approved post |
| `GET /media/<path>` | Locally stored file of an approved post |
| `GET /api/v1/raw/posts?limit=20&offset=0` | Full raw fields of all non-deleted posts; `X-Archive-Key` required |

Examples:

```bash
curl 'http://127.0.0.1:8080/api/v1/posts?limit=12&offset=0'
curl -H 'X-Archive-Key: YOUR_API_READ_KEY' \
  'http://127.0.0.1:8080/api/v1/raw/posts?limit=20&offset=0'
```

`limit` is 1–100, `offset` 0–1000000. The response contains `total`, `limit`,
`offset` and `posts`. Formatted posts include, among others, `content_html`,
`content_text`, `links`, `media`, `reaction_count`, `comment_count` and
`engagement_updated_at`. `media[].media_url` is an absolute URL to the local
file if the download succeeded. The private raw data endpoint additionally
returns `raw_snapshot`, `raw_event`, `raw_page_fragment` and technical media
fields. Only use the raw data key server-side, never in WordPress HTML or
JavaScript. If `API_READ_KEY` is missing or still a `REPLACE_` placeholder,
the raw data endpoint responds with 503.

### Integration in WordPress Page

The current page [glogger.ch/linkedin/](https://www.glogger.ch/linkedin/) is now using the
bundled plugin [`wordpress/linkedin-archive.php`](wordpress/linkedin-archive.php) uses it
with its own post cards in a multi-column masonry layout:

- Header with profile picture and name on the left, compact time label on the
  right (`25d`, `3mo`, as on LinkedIn). The full date is shown in the tooltip.
- Below that the images, then the post text.
- Footer with reaction and comment counts and the LinkedIn logo at the bottom
  right, which opens the post on LinkedIn.
- Mentions and external links stay clickable and open in a new tab. Bare URLs
  and `#hashtags` are linked even if the post has not been enriched yet and its
  text therefore contains no links at all.
- The post text is always shown in full, never truncated.
- Posts are distributed across the columns alternately (left, right, left, …).
  Each card sits directly below the one above it in the same column; there is
  no alignment to shared row heights.

It fetches the approved JSON data server-side and caches the response for five
minutes in the WordPress cache. On narrow screens the grid becomes single-column.

1. Build the installation package and upload it in the admin area under
   "Plugins → Add New → Upload Plugin", then activate it:

   ```bash
   ./wordpress/build-plugin.sh
   ```

   The script creates `dist/linkedin-archive-feed-<version>.zip`. It reads the
   version from the plugin header; WordPress only detects an update if it was
   bumped there. Alternatively, place `wordpress/linkedin-archive.php` manually
   as `wp-content/plugins/linkedin-archive-feed/linkedin-archive.php`.
2. In `wp-config.php`, set the API base reachable from the WordPress server and
   configure the name and profile picture:

   ```php
   define('LINKEDIN_ARCHIVE_API_BASE',     'https://<api_url>.example.net');
   define('LINKEDIN_ARCHIVE_AUTHOR_NAME',  'Steven Glogger');
   define('LINKEDIN_ARCHIVE_AUTHOR_IMAGE', 'https://www.example.net/logo.jpg');
   define('LINKEDIN_ARCHIVE_AUTHOR_URL',   'http://linkedin.com/in/stevenglogger/');
   ```

   Name and profile picture are deliberately set here and not in the database:
   the archive stores only your own posts and does not download profile
   pictures. All posts come from the same person anyway. Without
   `AUTHOR_IMAGE`, the header shows a circle with the initials.
3. On `/linkedin/`, replace the existing Juicer embed with the shortcode
   `[linkedin_archive limit="12" columns="2"]` and clear the WordPress page
   cache.
4. Approve the desired posts with `docker compose exec archive python -m linkedin_archiver publish '<URN>'`.
   Only then do they become visible in the feed. With `AUTO_PUBLISH=true` this
   step is not needed for new posts.

All shortcode attributes:

| Attribute | Default | Meaning |
|---|---:|---|
| `limit` | 12 | Posts per page, 1–100 |
| `columns` | 2 | Columns, 1–4; below 860 px single-column in chronological order |
| `author` | constant | Overrides `LINKEDIN_ARCHIVE_AUTHOR_NAME` |
| `avatar` | constant | Overrides `LINKEDIN_ARCHIVE_AUTHOR_IMAGE` |
| `profile` | constant | Overrides `LINKEDIN_ARCHIVE_AUTHOR_URL` |

Reaction and comment counts only appear if they exist in the archive; missing
values are omitted and not shown as zero.

If WordPress and Docker run on the same host, WordPress can use
`http://127.0.0.1:8080` internally. Images in the browser additionally require
a public HTTPS base. An Nginx reverse proxy on the same host can forward the
path before the WordPress rewrite rules:

```nginx
location = /linkedin-api/api/v1/raw/posts {
    return 403;
}

location /linkedin-api/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host $host;
}
```

Then set `API_PUBLIC_BASE_URL=https://www.example.net/linkedin-api` in `.env`
and run `docker compose up -d --force-recreate api`. Also set the
`LINKEDIN_ARCHIVE_API_BASE` constant to this URL. If WordPress runs on a
different server, that server must be able to reach the API via an accessible
HTTPS address; set up Nginx and network access on the Docker host accordingly.
The Nginx block shown blocks the private raw data endpoint for external access.
The browser origin `API_ALLOWED_ORIGIN` is intended for direct JavaScript
integration; the WordPress shortcode does not need CORS.

The template does not change the existing website automatically. WordPress
access, server location and reverse proxy configuration are required for that.

## Optional: logged-in browser

No browser login is needed for publicly readable posts. For your own restricted
posts, a Playwright storage state can be created locally:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/playwright codegen --save-storage=secrets/linkedin-state.json https://www.linkedin.com/login
```

Log in yourself in the opened browser, then close the window. The file contains
credentials and belongs only locally in `secrets/`. On Linux it must be
readable by the container user. Then set:

```dotenv
BROWSER_STORAGE_STATE=/run/secrets/linkedin-state.json
```

Recreate the container. No CAPTCHAs are solved and no access or login blocks
are bypassed. The parser supports the public feed HTML structure; LinkedIn's
logged-in view may deliver a different structure, which is then logged as
unsupported. Logging in is therefore no promise that private posts can be
fully extracted.

## Database, backups, updates

Tables: `posts`, `post_links`, `post_media`, `post_events`, `sync_state`.
All text fields use utf8mb4, including emojis. Dates are stored in UTC; UTC is
assumed for snapshot date strings, matching the examined GMT upload data. Raw
data is archived unchanged.

MariaDB lives in the `mariadb-data` volume, media and exports in `archive-data`.
Back up both; an SQL dump alone does not contain the image files.

```bash
mkdir -p backup
docker compose exec -T db sh -c \
  'exec mariadb-dump --single-transaction -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  > backup/archive.sql
docker compose cp archive:/data/media backup/media
```

Normal stop: `docker compose down`. **`down -v` deletes the data volumes.**
The MariaDB image's password variables only take effect when an empty volume is
first initialized. Later password changes must also be made in MariaDB.

For source code updates, run `docker compose up -d --build`. This first version
creates the schema with `CREATE TABLE IF NOT EXISTS`; future schema changes
require explicit migrations. Image and library versions are pinned and should
be updated regularly in a controlled way.

## Development and tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The WordPress plugin's text processing is tested separately:

```bash
docker run --rm -v "$PWD/wordpress:/w:ro" php:8.3-cli php /w/tests.php
```

`build-plugin.sh` runs these checks before packaging and aborts on failure,
provided PHP is available.

The MariaDB integration tests only run when `TEST_DB_HOST`, `TEST_DB_PORT` and
`TEST_DB_PASSWORD` are set. **Only use an empty test database**
`linkedin_archive` with user `linkedin`: the tests empty the application
tables. Covered areas include link preservation, separation from comments, HTML
sanitization, pagination, checkpoint rollback, duplicates and media errors.

Sources: [LinkedIn member access](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/),
[Snapshot](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api),
[Changelog](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-changelog-api),
[Playwright Docker](https://playwright.dev/python/docs/docker),
[MariaDB Docker Image](https://hub.docker.com/_/mariadb).
