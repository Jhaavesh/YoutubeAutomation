"""
DON OF VICE CITY — OAuth 2.0 Authentication Setup (Multi-Channel)
Run this once per channel to authenticate and store token.pickle.

Required scopes:
* youtube.upload          — upload videos
* youtube.force-ssl       — edit metadata, delete videos, set thumbnails
* yt-analytics.readonly   — read YouTube Analytics in later phases

The flow uses an ephemeral localhost port and validates the OAuth ``state``
parameter through google-auth-oauthlib's local server helper.
"""
from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Local imports
from config_loader import get_config, get_channel_config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

SCOPE_LABELS = {
    "https://www.googleapis.com/auth/youtube.upload": "Upload videos",
    "https://www.googleapis.com/auth/youtube.force-ssl": "Edit metadata / thumbnails / delete",
    "https://www.googleapis.com/auth/youtube.readonly": "Read channel data",
    "https://www.googleapis.com/auth/yt-analytics.readonly": "Read YouTube Analytics",
}


def authenticate_channel(channel_key: str) -> bool:
    """Authenticate a specific channel from config."""
    cfg = get_config()

    try:
        channel = get_channel_config(channel_key)
    except KeyError:
        print(f"Channel '{channel_key}' not found in config.yaml")
        print(f"Available channels: {list(cfg.channels.keys())}")
        return False

    client_secret_path = channel.client_secret_file
    token_path = channel.token_file

    if not os.path.isabs(client_secret_path):
        client_secret_path = os.path.join(cfg.base_dir, client_secret_path)
    if not os.path.isabs(token_path):
        token_path = os.path.join(cfg.base_dir, token_path)

    if not os.path.exists(client_secret_path):
        print(f"client_secret.json not found at: {client_secret_path}")
        print("Download it from Google Cloud Console and place it there,")
        print("or update channels.accounts.<key>.client_secret_file in config.yaml.")
        return False

    print(f"\n{'=' * 60}")
    print(f"  YOUTUBE OAUTH 2.0 — {channel.name} ({channel_key})")
    print(f"{'=' * 60}")
    print("Requested permissions:")
    for scope in SCOPES:
        print(f"  - {SCOPE_LABELS.get(scope, scope)}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_path,
        scopes=SCOPES,
    )

    try:
        # port=0 asks the OS for a free port; state is generated and verified
        # by google-auth-oauthlib's local server helper.
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true",
            open_browser=True,
            authorization_prompt_message=(
                "Open this URL to authorize the channel:\n{url}\n"
            ),
            success_message=(
                "Authentication successful. You may close this window and "
                "return to the terminal."
            ),
        )
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return False

    granted = set(creds.scopes or [])
    missing = [scope for scope in SCOPES if scope not in granted]
    if missing:
        print("\nWARNING: Google did not grant every requested permission:")
        for scope in missing:
            print(f"  - {SCOPE_LABELS.get(scope, scope)}")
        print("Re-run with prompt=consent, or check the Google Cloud OAuth consent screen.")
    else:
        print("\nAll required permissions granted.")

    token_dir = Path(token_path).parent
    token_dir.mkdir(parents=True, exist_ok=True)
    with open(token_path, "wb") as handle:
        pickle.dump(creds, handle)
    print(f"Token saved to: {token_path}")

    try:
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        request = youtube.channels().list(part="snippet,statistics", mine=True)
        response = request.execute()
        items = response.get("items", [])
        if items:
            info = items[0]
            print(f"\nConnected to: {info['snippet']['title']}")
            print(f"   Channel ID: {info['id']}")
            print(
                "   Subscribers: "
                f"{info['statistics'].get('subscriberCount', 'hidden')}"
            )
        else:
            print("Connected but no channel was found for this account.")
    except Exception as exc:
        print(f"Channel verification note: {exc}")

    print(f"\nAuthentication complete for {channel.name}.")
    print(f"You can now run: python master_autopilot.py --channel {channel_key}")
    return True


def print_scopes() -> None:
    print("Required OAuth scopes:")
    for scope in SCOPES:
        print(f"  - {scope}")
        print(f"    {SCOPE_LABELS.get(scope, '')}")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="YouTube OAuth Setup for DON OF VICE CITY"
    )
    parser.add_argument("--channel", type=str, help="Channel key to authenticate")
    parser.add_argument("--list", action="store_true", help="List configured channels")
    parser.add_argument("--all", action="store_true", help="Authenticate all channels")
    parser.add_argument("--scopes", action="store_true", help="Show required scopes")

    args = parser.parse_args()
    cfg = get_config()

    if args.scopes:
        print_scopes()
        return

    if args.list:
        print("\nConfigured channels:")
        for key, channel in cfg.channels.items():
            default_marker = " (DEFAULT)" if key == cfg.default_channel else ""
            token_path = channel.token_file
            if not os.path.isabs(token_path):
                token_path = os.path.join(cfg.base_dir, token_path)
            token_exists = "OK" if os.path.exists(token_path) else "MISSING"
            print(f"  {key}{default_marker} — {channel.name} [Token: {token_exists}]")
        return

    if args.all:
        print(f"Authenticating all {len(cfg.channels)} channels...")
        failures = 0
        for key in cfg.channels:
            if not authenticate_channel(key):
                failures += 1
        sys.exit(1 if failures else 0)

    channel_key = args.channel or cfg.default_channel
    sys.exit(0 if authenticate_channel(channel_key) else 1)


if __name__ == "__main__":
    main()
