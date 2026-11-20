"""
YouTube API OAuth 2.0 Authentication Setup Script
Runs a temporary local callback server to authenticate channel and store token.pickle.
"""
import os
import sys
import pickle
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET_PATH = os.path.join(BASE_DIR, 'client_secret.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.pickle')

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

def main():
    global auth_code
    if not os.path.exists(CLIENT_SECRET_PATH):
        print(f"ERROR: '{CLIENT_SECRET_PATH}' not found!")
        print("Please download your client_secret.json from Google Cloud Console and place it in the project root.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_PATH,
        scopes=SCOPES,
        redirect_uri='http://localhost:8080/'
    )

    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    print("\n========================================================")
    print("          YOUTUBE OAUTH 2.0 CHANNEL LOGIN               ")
    print("========================================================")
    print("Opening authorization page in your default browser...")
    print(f"\nIf browser does not open automatically, visit this URL:\n{auth_url}\n")
    
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(('localhost', 8080), OAuthHandler)
    print("Waiting for authentication callback on http://localhost:8080/ ...")
    sys.stdout.flush()

    while auth_code is None:
        server.handle_request()

    print("Authorization code received! Exchanging for tokens...")
    flow.fetch_token(code=auth_code)
    creds = flow.credentials

    with open(TOKEN_PATH, 'wb') as f:
        pickle.dump(creds, f)

    print(f"SUCCESS: Token saved to '{TOKEN_PATH}'")

    try:
        youtube = build('youtube', 'v3', credentials=creds)
        req = youtube.channels().list(part="snippet", mine=True)
        res = req.execute()
        items = res.get('items', [])
        if items:
            title = items[0]['snippet']['title']
            print(f"Connected Channel: {title}")
        else:
            print("Connected successfully, but no channel found for this Google Account.")
    except Exception as e:
        print(f"Channel verification note: {e}")

    print("Authentication complete! You are ready to run auto_pilot_bot.py.")

if __name__ == '__main__':
    main()
