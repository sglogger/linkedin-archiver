CREATE TABLE IF NOT EXISTS posts (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    post_key VARCHAR(255) NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    canonical_url TEXT NULL,
    activity_urn VARCHAR(255) NULL,
    author_urn VARCHAR(255) NULL,
    published_at DATETIME(3) NULL,
    visibility VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    content_text LONGTEXT NOT NULL,
    content_html LONGTEXT NOT NULL,
    content_source VARCHAR(20) NOT NULL DEFAULT 'snapshot',
    api_text LONGTEXT NULL,
    raw_snapshot JSON NULL,
    raw_event JSON NULL,
    raw_page_fragment LONGTEXT NULL,
    publicly_accessible BOOLEAN NOT NULL DEFAULT FALSE,
    publish_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    reaction_count INT UNSIGNED NULL,
    comment_count INT UNSIGNED NULL,
    engagement_updated_at DATETIME(3) NULL,
    reshare_author VARCHAR(255) NULL,
    reshare_author_url TEXT NULL,
    reshare_text LONGTEXT NULL,
    reshare_html LONGTEXT NULL,
    deleted_at DATETIME(3) NULL,
    enrichment_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    enrichment_error VARCHAR(255) NULL,
    enrichment_attempts INT UNSIGNED NOT NULL DEFAULT 0,
    enriched_at DATETIME(3) NULL,
    next_enrichment_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    INDEX enrichment_queue (next_enrichment_at, deleted_at),
    INDEX publication_date (published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS post_links (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    post_id BIGINT UNSIGNED NOT NULL,
    position INT UNSIGNED NOT NULL,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    kind VARCHAR(30) NOT NULL,
    UNIQUE KEY post_position (post_id, position),
    FOREIGN KEY (post_id) REFERENCES posts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS post_media (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    post_id BIGINT UNSIGNED NOT NULL,
    media_key CHAR(64) NOT NULL,
    position INT UNSIGNED NOT NULL,
    kind VARCHAR(30) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'attachment',
    alt_text TEXT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT NULL,
    content_type VARCHAR(100) NULL,
    sha256 CHAR(64) NULL,
    size_bytes BIGINT UNSIGNED NULL,
    download_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    last_error VARCHAR(255) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    downloaded_at DATETIME(3) NULL,
    UNIQUE KEY media_per_post (post_id, media_key, role),
    FOREIGN KEY (post_id) REFERENCES posts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS post_events (
    event_key CHAR(64) PRIMARY KEY,
    post_key VARCHAR(255) NOT NULL,
    processed_at BIGINT NOT NULL,
    method VARCHAR(30) NULL,
    payload JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sync_state (
    state_key VARCHAR(100) PRIMARY KEY,
    state_value LONGTEXT NOT NULL,
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
