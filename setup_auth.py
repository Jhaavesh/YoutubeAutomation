"""
DON OF VICE CITY — OAuth 2.0 Authentication Setup (Multi-Channel)
Run this once per channel to authenticate and store token.pickle.
"""
import os
import sys
import pickle
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Local imports
from config_loader import get_config, get_channel_config, ConfigLoader

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]

auth_code = None


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding-top: 50px; background: #0f172a; color: #f8fafc;">
                <h1 style="color: #22c55e;">Authentication Successful!</h1>
                <p>Your YouTube channel is now connected.</p>
                <p>You may close this browser window and return to the terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: No authorization code received.")

    def log_message(self, format, *args):
        pass


def authenticate_channel(channel_key: str) -> bool:
    """Authenticate a specific channel from config."""
    cfg = get_config()

    try:
        channel = get_channel_config(channel_key)
    except KeyError:
        print(f"❌ Channel '{channel_key}' not found in config.yaml")
        print(f"Available channels: {list(cfg.channels.keys())}")
        return False

    client_secret_path = channel.client_secret_file
    token_path = channel.token_file

    # Resolve paths relative to project root
    if not os.path.isabs(client_secret_path):
        client_secret_path = os.path.join(cfg.base_dir, client_secret_path)
    if not os.path.isabs(token_path):
        token_path = os.path.join(cfg.base_dir, token_path)

    if not os.path.exists(client_secret_path):
        print(f"❌ client_secret.json not found at: {client_secret_path}")
        print(f"Please download from Google Cloud Console and place it there.")
        print(f"Or update config.yaml with correct path.")
        return False

    print(f"\n{'='*60}")
    print(f"  YOUTUBE OAUTH 2.0 — {channel.name} ({channel_key})")
    print(f"{'='*60}")

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_path,
        scopes=SCOPES,
        redirect_uri='http://localhost:8080/'
    )

    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    print(f"\nOpening authorization page in browser...")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    global auth_code
    auth_code = None

    server = HTTPServer(('localhost', 8080), OAuthHandler)
    print("Waiting for callback on http://localhost:8080/ ...")
    sys.stdout.flush()

    while auth_code is None:
        server.handle_request()

    print("Authorization code received! Exchanging for tokens...")
    flow.fetch_token(code=auth_code)
    creds = flow.credentials

    with open(token_path, 'wb') as f:
        pickle.dump(creds, f)

    print(f"✅ Token saved to: {token_path}")

    # Verify channel
    try:
        youtube = build('youtube', 'v3', credentials=creds)
        req = youtube.channels().list(part="snippet,statistics", mine=True)
        res = req.execute()
        items = res.get('items', [])
        if items:
            info = items[0]
            title = info['snippet']['title']
            channel_id = info['id']
            subs = info['statistics'].get('subscriberCount', 'hidden')
            print(f"\n✅ Connected to: {title}")
            print(f"   Channel ID: {channel_id}")
            print(f"   Subscribers: {subs}")

            # Update config with channel_id (optional, for reference)
            # This would require writing back to config.yaml
        else:
            print("⚠️ Connected but no channel found for this account.")
    except Exception as e:
        print(f"Channel verification note: {e}")

    print(f"\n✅ Authentication complete for {channel.name}!")
    print(f"You can now run: python master_autopilot.py --channel {channel_key}")
    return True


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="YouTube OAuth Setup for DON OF VICE CITY")
    parser.add_argument('--channel', type=str, help='Channel key to authenticate (from config.yaml)')
    parser.add_argument('--list', action='store_true', help='List available channels')
    parser.add_argument('--all', action='store_true', help='Authenticate all channels')

    args = parser.parse_args()

    cfg = get_config()

    if args.list:
        print("\nConfigured channels:")
        for key, ch in cfg.channels.items():
            default_marker = " (DEFAULT)" if key == cfg.default_channel else ""
            token_exists = "✅" if os.path.exists(os.path.join(cfg.base_dir, ch.token_file)) else "❌"
            print(f"  {key}{default_marker} — {ch.name} [Token: {token_exists}]")
        return

    if args.all:
        print(f"Authenticating all {len(cfg.channels)} channels...")
        for key in cfg.channels.keys():
            authenticate_channel(key)
        return

    # Default: authenticate default channel or specified channel
    channel_key = args.channel or cfg.default_channel
    authenticate_channel(channel_key)


if __name__ == '__main__':
    main()