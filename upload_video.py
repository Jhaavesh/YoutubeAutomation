"""
DON OF VICE CITY — YouTube Upload Module (Refactored)
Supports multi-channel, quota tracking, scheduling, and resumable uploads.
"""
import os
import sys
import pickle
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Local imports
from config_loader import get_config, get_channel_config
from utils import (
    QuotaTracker,
    build_upload_key,
    find_ledger_entry,
    load_db,
    now_local,
    record_ledger_entry,
    run_with_lock,
    setup_logging,
    validate_video_file,
)

log = setup_logging("upload_video")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
UPLOAD_SCOPES = {
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}
UPDATE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtubepartner",
}
ANALYTICS_SCOPES = {"https://www.googleapis.com/auth/yt-analytics.readonly"}


# ============================================================================
# AUTHENTICATION
# ============================================================================
def _resolve_token_path(channel_key: Optional[str] = None) -> str:
    channel = get_channel_config(channel_key)
    token_path = channel.token_file
    if not os.path.isabs(token_path):
        token_path = str(Path(get_config().base_dir) / token_path)
    return token_path


def read_token_scopes(channel_key: Optional[str] = None) -> List[str]:
    """Read the stored token's granted scopes without refreshing it."""
    token_path = _resolve_token_path(channel_key)
    if not os.path.isfile(token_path):
        return []
    with open(token_path, "rb") as handle:
        creds = pickle.load(handle)
    return sorted(set(creds.scopes or []))


def _load_credentials(channel_key: Optional[str] = None) -> Tuple[Any, str]:
    """Load and, if needed, refresh OAuth credentials for a channel."""
    token_path = _resolve_token_path(channel_key)
    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Token file not found: {token_path}. Run setup_auth.py first."
        )

    with open(token_path, "rb") as handle:
        creds = pickle.load(handle)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired credentials...")
            creds.refresh(Request())
            with open(token_path, "wb") as handle:
                pickle.dump(creds, handle)
            log.info("Credentials refreshed and saved.")
        else:
            raise RuntimeError(
                "Credentials expired or invalid. Run setup_auth.py to re-authenticate."
            )

    return creds, token_path


def _require_scope(youtube: Any, allowed: set, action: str) -> None:
    """Fail clearly when the stored token cannot perform an operation.

    Google's ``videos.update``, ``videos.delete`` and ``thumbnails.set`` need
    broader scopes than ``youtube.upload``.  A clear local error is better
    than a confusing 403 halfway through a scheduled run.
    """
    granted = set(getattr(youtube, "_autopilot_scopes", set()) or set())
    if granted and not (granted & allowed):
        raise PermissionError(
            f"The stored token cannot {action}. Required scope: one of "
            f"{sorted(allowed)}. Current scopes: {sorted(granted)}. "
            "Run: python setup_auth.py --channel <key>"
        )


def get_authenticated_service(channel_key: Optional[str] = None) -> Any:
    """Get an authenticated YouTube service for a channel."""
    creds, _ = _load_credentials(channel_key)
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    # Keep the granted scopes on the client so callers can fail fast.
    service._autopilot_scopes = set(creds.scopes or [])
    return service


def _retry_settings() -> Tuple[int, int]:
    cfg = get_config().retry
    attempts = max(1, int(cfg.get("max_attempts", 3)))
    base_delay = max(1, int(cfg.get("backoff_base", 60)))
    return attempts, base_delay


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        try:
            return int(exc.resp.status) in RETRYABLE_STATUS
        except Exception:
            return False
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _execute_with_retry(request: Any, action: str) -> Any:
    """Execute a Google API request with bounded exponential backoff."""
    attempts, base_delay = _retry_settings()
    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except Exception as exc:
            if attempt >= attempts or not _is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), 300)
            log.warning(
                "%s failed (%s). Retry %s/%s in %ss...",
                action,
                exc,
                attempt,
                attempts - 1,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"{action} exhausted retries")


def verify_channel(channel_key: Optional[str] = None) -> Dict[str, Any]:
    """Verify the authenticated channel and return channel info."""
    youtube = get_authenticated_service(channel_key)
    req = youtube.channels().list(part="snippet,statistics", mine=True)
    res = _execute_with_retry(req, "Channel verification")
    items = res.get('items', [])
    if not items:
        raise RuntimeError("No channel found for this account.")
    return items[0]


# ============================================================================
# UPLOAD FUNCTIONS
# ============================================================================
def approval_hold_active() -> bool:
    """Return True when the configured approval flow requires a private draft.

    ``approval.required: true`` always wins, even if ``auto_approve`` is also
    true.  This is deliberate: a half-configured approval section must fail
    closed rather than publish without review.
    """
    return bool(get_config().approval.get("required", False))


def _build_status_body(
    publish_at: Optional[str] = None,
    privacy_status: Optional[str] = None,
    channel_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Build video status body for upload."""
    channel = get_channel_config(channel_key)
    defaults = channel.upload_defaults

    status = {
        'selfDeclaredMadeForKids': defaults.get('self_declared_made_for_kids', False)
    }

    if approval_hold_active():
        # Never attach publishAt or a public privacy status while review is
        # required.  The video is uploaded as a private draft and must be
        # approved out of band before it can go live.
        status['privacyStatus'] = 'private'
        return status

    if publish_at:
        status['privacyStatus'] = 'private'
        status['publishAt'] = publish_at
    else:
        status['privacyStatus'] = privacy_status or defaults.get('privacy_status', 'private')

    return status


def _build_snippet_body(
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    category_id: Optional[str] = None,
    default_language: Optional[str] = None,
    channel_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Build video snippet body for upload."""
    channel = get_channel_config(channel_key)
    defaults = channel.upload_defaults

    snippet = {
        'title': title[:100],  # YouTube title limit
        'description': description[:5000],  # YouTube description limit
        'tags': (tags or []) + defaults.get('default_tags', []),
        'categoryId': category_id or defaults.get('category_id', '20'),
    }

    if default_language or defaults.get('language'):
        snippet['defaultLanguage'] = default_language or defaults.get('language')

    # Deduplicate tags and limit to 500 chars total
    seen = set()
    unique_tags = []
    for tag in snippet['tags']:
        tag = tag.strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            unique_tags.append(tag)
    snippet['tags'] = unique_tags[:30]  # Reasonable limit

    return snippet


def upload_video(
    file_path: str,
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    publish_at: Optional[str] = None,
    privacy_status: Optional[str] = None,
    category_id: Optional[str] = None,
    channel_key: Optional[str] = None,
    chunk_size_mb: int = 4,
    track_quota: bool = True,
    force_reupload: bool = False,
) -> Dict[str, Any]:
    """
    Upload a video to YouTube with validation, idempotency, and quota tracking.

    The file is hashed and checked against ``upload_ledger.json`` before any
    network call.  Re-running the same pipeline therefore returns the existing
    video instead of uploading a duplicate.  Use ``force_reupload=True`` only
    when you deliberately want a second copy.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")

    cfg = get_config()
    channel = channel_key or cfg.default_channel

    ok, message, media_info = validate_video_file(
        file_path, min_duration=1.0, require_audio=False
    )
    if not ok:
        raise ValueError(f"Upload validation failed: {message}")

    file_size_mb = media_info["size_bytes"] / (1024 * 1024)
    log.info(
        "Validated '%s' (%.1f MB, %.1fs, %sx%s)",
        os.path.basename(file_path),
        file_size_mb,
        media_info["duration"],
        media_info["width"],
        media_info["height"],
    )

    # Idempotency: same bytes + same channel = same upload.
    upload_key, digest = build_upload_key(file_path, channel)
    if not force_reupload:
        existing = find_ledger_entry(upload_key)
        if existing and existing.get("video_id"):
            video_id = existing["video_id"]
            log.info(
                "Skipping duplicate upload; already uploaded as %s (%s)",
                video_id,
                existing.get("uploaded_at", "unknown time"),
            )
            response = dict(existing.get("response") or {})
            response.setdefault("id", video_id)
            response["duplicate"] = True
            return response

    # Quota check before upload. Uploads use their own 100/day bucket.
    upload_cost = cfg.quota.video_upload_cost
    if track_quota:
        tracker = QuotaTracker(load_db())
        if not tracker.can_upload():
            raise RuntimeError(
                f"Daily upload bucket exhausted: {tracker.uploads_today}/"
                f"{tracker.upload_limit}. YouTube resets it at midnight Pacific."
            )
        safe, msg = tracker.check_and_warn(upload_cost)
        if not safe:
            raise RuntimeError(msg)
        log.info(
            "Quota: %s; uploads today %s/%s",
            msg,
            tracker.uploads_today,
            tracker.upload_limit,
        )

    youtube = get_authenticated_service(channel)
    _require_scope(youtube, UPLOAD_SCOPES, "upload videos")

    status_body = _build_status_body(publish_at, privacy_status, channel)
    snippet_body = _build_snippet_body(
        title, description, tags, category_id, channel_key=channel
    )
    body = {"snippet": snippet_body, "status": status_body}

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        chunksize=chunk_size_mb * 1024 * 1024,
        resumable=True,
    )
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    attempts, base_delay = _retry_settings()
    response = None
    retry_count = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                log.info("Upload progress: %s%%", progress)
        except Exception as exc:
            if retry_count >= attempts - 1 or not _is_retryable(exc):
                raise
            retry_count += 1
            delay = min(base_delay * (2 ** (retry_count - 1)), 300)
            log.warning(
                "Upload interrupted (%s). Resuming in %ss (retry %s/%s)...",
                exc,
                delay,
                retry_count,
                attempts - 1,
            )
            time.sleep(delay)

    video_id = response.get("id")
    log.info("Upload successful: %s", video_id)
    log.info("URL: https://www.youtube.com/watch?v=%s", video_id)
    if approval_hold_active():
        log.warning(
            "approval.required is enabled: the video is a private draft and "
            "was NOT scheduled for publication. Approve it manually, then "
            "set approval.required to false for normal automated runs."
        )
        response["_approval_required"] = True
    elif publish_at:
        log.info("Scheduled for: %s", publish_at)

    if track_quota:
        try:
            tracker = QuotaTracker(load_db())
            tracker.add_usage(upload_cost, "video_upload", video_id)
        except Exception as exc:
            log.error("Could not record quota usage after upload: %s", exc)

    # Record the ledger after YouTube accepted the upload.  If this write
    # fails, report it loudly: the next run could otherwise create a duplicate.
    try:
        record_ledger_entry(
            upload_key,
            {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet_body.get("title", title),
                "channel": channel,
                "file": os.path.basename(file_path),
                "size_bytes": media_info["size_bytes"],
                "sha256": digest,
                "uploaded_at": now_local().isoformat(timespec="seconds"),
                "publish_at": publish_at,
                "privacy_status": status_body.get("privacyStatus"),
                "response": response,
            },
        )
    except Exception as exc:
        log.error(
            "Upload succeeded but the ledger could not be written: %s. "
            "Record this video ID manually before rerunning: %s",
            exc,
            video_id,
        )

    return response


def upload_short(
    file_path: str,
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    publish_at: Optional[str] = None,
    channel_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload a YouTube Short (vertical video ≤ 60 seconds).

    Shorts are detected automatically by YouTube based on aspect ratio and duration.
    """
    return upload_video(
        file_path=file_path,
        title=title,
        description=description,
        tags=tags,
        publish_at=publish_at,
        channel_key=channel_key,
        chunk_size_mb=2,  # Smaller chunks for shorts
        track_quota=True,
    )


def upload_long_video(
    file_path: str,
    thumb_path: Optional[str],
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    publish_at: Optional[str] = None,
    channel_key: Optional[str] = None,
    force_reupload: bool = False,
) -> Dict[str, Any]:
    """Upload a long-form video with an optional custom thumbnail."""
    response = upload_video(
        file_path=file_path,
        title=title,
        description=description,
        tags=tags,
        publish_at=publish_at,
        channel_key=channel_key,
        chunk_size_mb=4,
        track_quota=True,
        force_reupload=force_reupload,
    )

    video_id = response.get("id")

    if thumb_path and os.path.exists(thumb_path) and video_id:
        try:
            log.info("Setting custom thumbnail...")
            youtube = get_authenticated_service(channel_key)
            _require_scope(youtube, UPLOAD_SCOPES, "set a thumbnail")
            thumb_media = MediaFileUpload(thumb_path, mimetype="image/jpeg")
            request = youtube.thumbnails().set(
                videoId=video_id, media_body=thumb_media
            )
            _execute_with_retry(request, "Thumbnail upload")
            log.info("Custom thumbnail set.")

            tracker = QuotaTracker(load_db())
            tracker.add_usage(
                get_config().quota.thumbnail_set_cost,
                "thumbnail_set",
                video_id,
            )
        except Exception as exc:
            # The channel may not be verified for custom thumbnails yet.
            log.warning("Thumbnail upload failed: %s", exc)

    return response


def set_video_thumbnail(
    video_id: str,
    thumb_path: str,
    channel_key: Optional[str] = None,
) -> bool:
    """Set a custom thumbnail for an existing video."""
    if not os.path.exists(thumb_path):
        log.error("Thumbnail not found: %s", thumb_path)
        return False

    try:
        youtube = get_authenticated_service(channel_key)
        _require_scope(youtube, UPLOAD_SCOPES, "set a thumbnail")
        thumb_media = MediaFileUpload(thumb_path, mimetype="image/jpeg")
        request = youtube.thumbnails().set(videoId=video_id, media_body=thumb_media)
        _execute_with_retry(request, "Thumbnail upload")
        log.info("Thumbnail set for %s", video_id)
        return True
    except Exception as exc:
        log.error("Failed to set thumbnail: %s", exc)
        return False


def update_video_metadata(
    video_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    privacy_status: Optional[str] = None,
    channel_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Update video metadata after upload.

    Only writable snippet fields are sent back.  Sending the full read-only
    snippet object returned by ``videos.list`` can make ``videos.update`` fail.
    """
    youtube = get_authenticated_service(channel_key)
    _require_scope(youtube, UPDATE_SCOPES, "update video metadata")

    request = youtube.videos().list(part="snippet,status", id=video_id)
    res = _execute_with_retry(request, "Video lookup")
    items = res.get("items", [])
    if not items:
        raise RuntimeError(f"Video not found: {video_id}")

    video = items[0]
    snippet = video.get("snippet", {})
    status = video.get("status", {})

    new_snippet = {}
    for key in ("categoryId", "defaultLanguage"):
        if key in snippet:
            new_snippet[key] = snippet[key]
    if title:
        new_snippet["title"] = title[:100]
    if description:
        new_snippet["description"] = description[:5000]
    if tags is not None:
        new_snippet["tags"] = tags

    if approval_hold_active() and privacy_status in {"public", "unlisted"}:
        raise PermissionError(
            "approval.required is enabled; refusing to change a video to "
            f"'{privacy_status}'. Approve it manually and disable the hold first."
        )

    body: Dict[str, Any] = {"id": video_id, "snippet": new_snippet}
    parts = ["snippet"]
    if privacy_status:
        body["status"] = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": status.get(
                "selfDeclaredMadeForKids", False
            ),
        }
        parts.append("status")

    request = youtube.videos().update(part=",".join(parts), body=body)
    response = _execute_with_retry(request, "Metadata update")

    try:
        tracker = QuotaTracker(load_db())
        tracker.add_usage(
            get_config().quota.video_update_cost, "video_update", video_id
        )
    except Exception as exc:
        log.warning("Could not record metadata-update quota: %s", exc)

    log.info("Updated video %s", video_id)
    return response


def delete_video(video_id: str, channel_key: Optional[str] = None) -> bool:
    """Delete a video from YouTube."""
    youtube = get_authenticated_service(channel_key)
    _require_scope(youtube, UPDATE_SCOPES, "delete a video")
    try:
        request = youtube.videos().delete(id=video_id)
        _execute_with_retry(request, "Video deletion")
        log.info("Deleted video %s", video_id)
        return True
    except Exception as exc:
        log.error("Failed to delete video: %s", exc)
        return False


# ============================================================================
# QUOTA REPORTING
# ============================================================================
def get_quota_report() -> Dict[str, Any]:
    """Get current quota usage report using YouTube's Pacific-time day."""
    db = load_db()
    tracker = QuotaTracker(db)
    cfg = get_config()
    usage_today = db.get("quota_usage", {}).get(
        tracker.today, {"used": 0, "operations": []}
    )

    general_safe = tracker.used_today < tracker.limit * tracker.alert_threshold
    uploads_safe = tracker.uploads_today < tracker.upload_limit

    return {
        "date": tracker.today,
        "reset_timezone": cfg.quota.reset_timezone,
        "limit": tracker.limit,
        "used": tracker.used_today,
        "remaining": tracker.remaining,
        "percent_used": round(tracker.percent_used, 1),
        "alert_threshold": round(tracker.alert_threshold * 100),
        "operations": usage_today.get("operations", []),
        "uploads": tracker.uploads_today,
        "upload_limit": tracker.upload_limit,
        "searches": tracker.searches_today,
        "search_limit": tracker.search_limit,
        "estimated_daily_cost": cfg.quota.estimate_daily_usage(),
        "is_safe": general_safe and uploads_safe,
    }


def print_quota_report() -> None:
    """Print formatted quota report."""
    report = get_quota_report()
    print("\n" + "=" * 50)
    print("     YOUTUBE API QUOTA REPORT")
    print("=" * 50)
    print(f"Date ({report['reset_timezone']}): {report['date']}")
    print(f"General Limit: {report['limit']:,} units")
    print(f"Used Today: {report['used']:,} units ({report['percent_used']}%)")
    print(f"Remaining: {report['remaining']:,} units")
    print(f"Uploads Today: {report['uploads']}/{report['upload_limit']}")
    print(f"Searches Today: {report['searches']}/{report['search_limit']}")
    print(f"Alert Threshold: {report['alert_threshold']}%")
    print(f"Estimated Daily Cost: {report['estimated_daily_cost']:,} units")
    print(f"Status: {'SAFE' if report['is_safe'] else 'WARNING'}")
    print("-" * 50)
    if report['operations']:
        print("Recent Operations:")
        for op in report['operations'][-10:]:
            print(
                f"  {op['timestamp'][:19]} | {op['units']:>5} units | "
                f"{op['operation']} | {op['video_id']}"
            )
    else:
        print("No operations recorded today.")
    print("=" * 50 + "\n")


# ============================================================================
# MAIN / TESTING
# ============================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="YouTube Upload Module")
    parser.add_argument('--quota', action='store_true', help='Show quota report')
    parser.add_argument('--verify', action='store_true', help='Verify channel auth')
    parser.add_argument('--scopes', action='store_true', help='Show stored OAuth scopes')
    parser.add_argument('--channel', type=str, help='Channel key to use')

    args = parser.parse_args()

    if args.quota:
        print_quota_report()
    elif args.scopes:
        scopes = read_token_scopes(args.channel)
        print("Stored scopes:")
        for scope in scopes or ["(none - run setup_auth.py)"]:
            print(f"  - {scope}")
        missing_update = not (set(scopes) & UPDATE_SCOPES)
        missing_analytics = not (set(scopes) & ANALYTICS_SCOPES)
        if missing_update:
            print("WARNING: metadata updates/deletes will fail until re-authenticated.")
        if missing_analytics:
            print("WARNING: YouTube Analytics is unavailable until re-authenticated.")
    elif args.verify:
        try:
            info = verify_channel(args.channel)
            print(f"Connected to: {info['snippet']['title']} ({info['id']})")
            print(f"Subscribers: {info['statistics'].get('subscriberCount', 'hidden')}")
        except Exception as e:
            print(f"Verification failed: {e}")
            sys.exit(1)
    else:
        print("Usage: python upload_video.py [--quota|--verify|--scopes] [--channel KEY]")