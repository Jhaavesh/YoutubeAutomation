import os
import sys
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, 'token.pickle')

def get_authenticated_service():
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"token.pickle not found at {TOKEN_PATH}")
    
    with open(TOKEN_PATH, 'rb') as f:
        creds = pickle.load(f)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, 'wb') as f:
                pickle.dump(creds, f)
        else:
            raise Exception("Credentials expired or invalid.")
            
    return build('youtube', 'v3', credentials=creds)

def upload_short(file_path, title, description, tags=None, publish_at=None):
    """
    Uploads a vertical short to YouTube.
    If publish_at is provided (RFC 3339 string, e.g. '2026-11-19T21:00:00+05:30'),
    privacyStatus will be set to 'private' and scheduled.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Video file not found: {file_path}")
        
    youtube = get_authenticated_service()
    
    status_body = {
        'selfDeclaredMadeForKids': False
    }
    
    if publish_at:
        status_body['privacyStatus'] = 'private'
        status_body['publishAt'] = publish_at
    else:
        status_body['privacyStatus'] = 'public'
        
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags or ['gta6', 'shorts', 'gaming', 'vicecity', 'gta5'],
            'categoryId': '20'  # Gaming
        },
        'status': status_body
    }
    
    media = MediaFileUpload(
        file_path,
        mimetype='video/mp4',
        chunksize=1024*1024*2,
        resumable=True
    )
    
    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )
    
    print(f"Uploading '{os.path.basename(file_path)}'...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")
            sys.stdout.flush()
            
    video_id = response.get('id')
    print(f"SUCCESS! Video uploaded. ID: {video_id}")
    print(f"URL: https://youtube.com/shorts/{video_id}")
    if publish_at:
        print(f"Scheduled for publish at: {publish_at}")
    sys.stdout.flush()
    return response

if __name__ == '__main__':
    # Test uploading Video 2 scheduled for 9:00 PM tonight
    video_2_path = r'c:\Ajfiles\Youtube\GTA6_Shorts\Short_9PM\gta6_florida_9pm.mp4'
    title_2 = "GTA 6 is Real Florida! 🐊💀 #shorts #gta6 #gaming #grandtheftauto"
    desc_2 = "Wait till the end to see the real Florida madness in GTA 6! 🐊🤯\n\nSubscribe to @donofvicecity2026 for daily GTA 6 leaks, comparisons and gameplay!\n\n#gta6 #shorts #gaming #vicecity #gta5 #florida"
    tags_2 = ["gta 6", "gta 6 trailer", "florida joker", "gta 6 leak", "shorts", "gaming", "don of vice city"]
    
    # 9:00 PM IST is 2026-11-19T21:00:00+05:30
    publish_time_9pm = "2026-11-19T21:00:00+05:30"
    
    upload_short(video_2_path, title_2, desc_2, tags_2, publish_time_9pm)

