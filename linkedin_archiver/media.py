import hashlib
import os
from pathlib import Path
import tempfile

from .network import FetchError, PublicHttp


MIME_EXT = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
            'image/webp': '.webp', 'image/avif': '.avif', 'video/mp4': '.mp4',
            'video/webm': '.webm', 'application/pdf': '.pdf'}


class MediaDownloader:
    def __init__(self, settings):
        self.settings = settings
        self.http = PublicHttp(settings.request_timeout)

    def download(self, row: dict) -> dict:
        if row['kind'] == 'stream':
            raise FetchError('Streaming manifest requires a separate stream archiver')
        directory = self.settings.media_dir
        directory.mkdir(parents=True, exist_ok=True)
        limit = self.settings.max_media_mb * 1024 * 1024
        temp_path = None
        try:
            with self.http.get(row['source_url'], self.settings.media_hosts) as response:
                mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if mime not in MIME_EXT:
                    raise FetchError('Unsupported media content type; HTML/login pages are not saved as images')
                if int(response.headers.get('Content-Length', '0')) > limit:
                    raise FetchError('Media exceeds MAX_MEDIA_SIZE_MB')
                digest, size = hashlib.sha256(), 0
                with tempfile.NamedTemporaryFile(dir=directory, delete=False, prefix='.partial-') as out:
                    temp_path = Path(out.name)
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > limit:
                            raise FetchError('Media exceeds MAX_MEDIA_SIZE_MB')
                        digest.update(chunk)
                        out.write(chunk)
                if not size:
                    raise FetchError('Empty media response')
                sha = digest.hexdigest()
                relative = Path(sha[:2]) / (sha + MIME_EXT[mime])
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_path, target)
                temp_path = None
                return {'local_path': relative.as_posix(), 'sha256': sha,
                        'content_type': mime, 'size_bytes': size}
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
