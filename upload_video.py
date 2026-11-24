"""
DON OF VICE CITY — YouTube Upload Module (Refactored)
Supports multi-channel, quota tracking, scheduling, and resumable uploads.
"""
import os
import sys
import pickle
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Local imports
from config_loader import get_config, get_channel_config, ChannelConfig
from utils import load_db, save_db, QuotaTracker, setup_logging, run_with_lock

log = setup_logging("upload_video")


# ============================================================================
# AUTHENTICATION
# ============================================================================
def get_authenticated_service(channel_key: Optional[str] = None) -> Any:
    """
    Get authenticated YouTube service for a channel.

    Args:
        channel_key: Channel key from config.yaml (uses default if None)

    Returns:
        Authenticated YouTube API service object
    """
    channel = get_channel_config(channel_key)
    token_path = channel.token_file

    # Resolve relative to project root
    if not os.path.isabs(token_path):
        cfg = get_config()
        token_path = str(Path(cfg.base_dir) / token_path)

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Token file not found: {token_path}. Run setup_auth.py first."
        )

    with open(token_path, 'rb') as f:
        creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired credentials...")
            creds.refresh(Request())
            with open(token_path, 'wb') as f:
                pickle.dump(creds, f)
            log.info("Credentials refreshed and saved.")
        else:
            raise Exception("Credentials expired or invalid. Run setup_auth.py to re-authenticate.")

    return build('youtube', 'v3', credentials=creds)


def verify_channel(channel_key: Optional[str] = None) -> Dict[str, Any]:
    """Verify the authenticated channel and return channel info."""
    youtube = get_authenticated_service(channel_key)
    req = youtube.channels().list(part="snippet,statistics", mine=True)
    res = req.execute()
    items = res.get('items', [])
    if not items:
        raise Exception("No channel found for this account.")
    return items[0]


# ============================================================================
# UPLOAD FUNCTIONS
# ============================================================================
def _build_status_body(
    publish_at: Optional[str] = None,
    privacy_status: Optional[str] = None
) -> Dict[str, Any]:
    """Build video status body for upload."""
    channel = get_channel_config()
    defaults = channel.upload_defaults

    status = {
        'selfDeclaredMadeForKids': defaults.get('self_declared_made_for_kids', False)
    }

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
    default_language: Optional[str] = None
) -> Dict[str, Any]:
    """Build video snippet body for upload."""
    channel = get_channel_config()
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
    track_quota: bool = True
) -> Dict[str, Any]:
    """
    Upload a video to YouTube with resumable upload and quota tracking.

    Args:
        file_path: Path to video file
        title: Video title
        description: Video description
        tags: List of tags
        publish_at: RFC3339 timestamp for scheduled publish (e.g., "2026-11-24T18:00:00+05:30")
        privacy_status: Override privacy status (public, private, unlisted)
        category_id: YouTube category ID
        channel_key: Channel to upload to (from config)
        chunk_size_mb: Upload chunk size in MB
        track_quota: Whether to track quota usage

    Returns:
        Upload response dict with video ID
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    log.info(f"Uploading '{os.path.basename(file_path)}' ({file_size_mb:.1f} MB)")

    # Quota check before upload
    if track_quota:
        db = load_db()
        tracker = QuotaTracker(db)
        upload_cost = get_config().quota.video_upload_cost

        if not tracker.can_afford(upload_cost):
            raise Exception(
                f"Insufficient quota: need {upload_cost}, have {tracker.remaining} remaining. "
                f"Used today: {tracker.used_today}/{tracker.limit}"
            )

        safe, msg = tracker.check_and_warn(upload_cost)
        if not safe:
            raise Exception(msg)
        log.info(f"Quota: {msg}")

    # Authenticate
    youtube = get_authenticated_service(channel_key)

    # Build request body
    status_body = _build_status_body(publish_at, privacy_status)
    snippet_body = _build_snippet_body(title, description, tags, category_id)

    body = {
        'snippet': snippet_body,
        'status': status_body
    }

    # Media upload
    media = MediaFileUpload(
        file_path,
        mimetype='video/mp4',
        chunksize=chunk_size_mb * 1024 * 1024,
        resumable=True
    )

    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    # Execute resumable upload
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            log.info(f"Upload progress: {progress}%")

    video_id = response.get('id')
    log.info(f"✅ Upload successful! Video ID: {video_id}")
    log.info(f"URL: https://www.youtube.com/watch?v={video_id}")

    if publish_at:
        log.info(f"Scheduled for: {publish_at}")

    # Track quota usage
    if track_quota:
        db = load_db()
        tracker = QuotaTracker(db)
        tracker.add_usage(upload_cost, 'video_upload', video_id)

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
        track_quota=True
    )


def upload_long_video(
    file_path: str,
    thumb_path: Optional[str],
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    publish_at: Optional[str] = None,
    channel_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload a long-form video with optional custom thumbnail.
    """
    # Upload video
    response = upload_video(
        file_path=file_path,
        title=title,
        description=description,
        tags=tags,
        publish_at=publish_at,
        channel_key=channel_key,
        chunk_size_mb=4,
        track_quota=True
    )

    video_id = response.get('id')

    # Set custom thumbnail if provided and supported
    if thumb_path and os.path.exists(thumb_path):
        try:
            log.info("Setting custom thumbnail...")
            youtube = get_authenticated_service(channel_key)
            thumb_media = MediaFileUpload(thumb_path, mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            log.info("✅ Custom thumbnail set!")

            # Track thumbnail quota
            db = load_db()
            tracker = QuotaTracker(db)
            tracker.add_usage(get_config().quota.thumbnail_set_cost, 'thumbnail_set', video_id)

        except Exception as e:
            log.warning(f"Thumbnail upload failed (channel may need verification): {e}")

    return response


def set_video_thumbnail(video_id: str, thumb_path: str, channel_key: Optional[str] = None) -> bool:
    """Set custom thumbnail for an existing video."""
    if not os.path.exists(thumb_path):
        log.error(f"Thumbnail not found: {thumb_path}")
        return False

    try:
        youtube = get_authenticated_service(channel_key)
        thumb_media = MediaFileUpload(thumb_path, mimetype='image/jpeg')
        youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        log.info(f"Thumbnail set for {video_id}")
        return True
    except Exception as e:
        log.error(f"Failed to set thumbnail: {e}")
        return False


def update_video_metadata(
    video_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    privacy_status: Optional[str] = None,
    channel_key: Optional[str] = None
) -> Dict[str, Any]:
    """Update video metadata after upload."""
    youtube = get_authenticated_service(channel_key)

    # Get current video
    req = youtube.videos().list(part="snippet,status", id=video_id)
    res = req.execute()
    items = res.get('items', [])
    if not items:
        raise Exception(f"Video not found: {video_id}")

    video = items[0]
    snippet = video['snippet']
    status = video['status']

    # Update fields
    if title:
        snippet['title'] = title[:100]
    if description:
        snippet['description'] = description[:5000]
    if tags is not None:
        snippet['tags'] = tags
    if privacy_status:
        status['privacyStatus'] = privacy_status

    # Update
    body = {'id': video_id, 'snippet': snippet, 'status': status}
    req = youtube.videos().update(part="snippet,status", body=body)
    response = req.execute()

    # Track quota
    db = load_db()
    tracker = QuotaTracker(db)
    tracker.add_usage(get_config().quota.video_update_cost, 'video_update', video_id)

    log.info(f"Updated video {video_id}")
    return response


def delete_video(video_id: str, channel_key: Optional[str] = None) -> bool:
    """Delete a video from YouTube."""
    youtube = get_authenticated_service(channel_key)
    try:
        youtube.videos().delete(id=video_id).execute()
        log.info(f"Deleted video {video_id}")
        return True
    except Exception as e:
        log.error(f"Failed to delete video: {e}")
        return False


# ============================================================================
# QUOTA REPORTING
# ============================================================================
def get_quota_report() -> Dict[str, Any]:
    """Get current quota usage report."""
    db = load_db()
    tracker = QuotaTracker(db)
    cfg = get_config()

    today = datetime.now().strftime("%Y-%m-%d")
    usage_today = db.get('quota_usage', {}).get(today, {'used': 0, 'operations': []})

    return {
        'date': today,
        'limit': tracker.limit,
        'used': tracker.used_today,
        'remaining': tracker.remaining,
        'percent_used': round(tracker.percent_used, 1),
        'alert_threshold': round(tracker.alert_threshold * 100),
        'operations': usage_today.get('operations', []),
        'estimated_daily_cost': cfg.quota.estimate_daily_usage(),
        'is_safe': tracker.used_today < tracker.limit * tracker.alert_threshold
    }


def print_quota_report() -> None:
    """Print formatted quota report."""
    report = get_quota_report()
    print("\n" + "=" * 50)
    print("     YOUTUBE API QUOTA REPORT")
    print("=" * 50)
    print(f"Date: {report['date']}")
    print(f"Daily Limit: {report['limit']:,} units")
    print(f"Used Today: {report['used']:,} units ({report['percent_used']}%)")
    print(f"Remaining: {report['remaining']:,} units")
    print(f"Alert Threshold: {report['alert_threshold']}%")
    print(f"Estimated Daily Cost: {report['estimated_daily_cost']:,} units")
    print(f"Status: {'✅ SAFE' if report['is_safe'] else '⚠️  WARNING'}")
    print("-" * 50)
    if report['operations']:
        print("Recent Operations:")
        for op in report['operations'][-10:]:
            print(f"  {op['timestamp'][:19]} | {op['units']:>5} units | {op['operation']} | {op['video_id']}")
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
    parser.add_argument('--channel', type=str, help='Channel key to use')

    args = parser.parse_args()

    if args.quota:
        print_quota_report()
    elif args.verify:
        try:
            info = verify_channel(args.channel)
            print(f"✅ Connected to: {info['snippet']['title']} ({info['id']})")
            print(f"Subscribers: {info['statistics'].get('subscriberCount', 'hidden')}")
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            sys.exit(1)
    else:
        print("Usage: python upload_video.py [--quota|--verify] [--channel KEY]")