from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", mode="a", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)
class YouTubeAPIWrapper:
    def __init__(self, api_key):
        self.youtube = build('youtube', 'v3', developerKey=api_key)

    def get_channel_id(self, url_or_handle):
        try:
            if "channel/" in url_or_handle:
                return url_or_handle.split("channel/")[1].split("/")[0]
            if "@" in url_or_handle:
                handle = url_or_handle.split("@")[-1].strip("/")
                resp = self.youtube.search().list(part="snippet", q=handle, type="channel", maxResults=1).execute()
                if not resp.get("items"):
                    raise Exception(f"Không tìm thấy channel với handle {handle}")
                return resp["items"][0]["snippet"]["channelId"]
            raise Exception("URL hoặc handle không hợp lệ")
        except HttpError as e:
            raise Exception(f"Lỗi API: {str(e)}")

    def fetch_all_videos(self, channel_id):
        items = []
        token = None
        retries = 3
        try:
            # Lấy playlistId của uploads
            channel_resp = self.youtube.channels().list(part="contentDetails", id=channel_id).execute()
            if not channel_resp.get("items"):
                raise Exception("Không tìm thấy kênh")
            playlist_id = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # Lấy video từ playlist
            while True:
                for attempt in range(retries):
                    try:
                        resp = self.youtube.playlistItems().list(
                            part="snippet",
                            playlistId=playlist_id,
                            maxResults=50,
                            pageToken=token
                        ).execute()
                        items += resp.get("items", [])
                        token = resp.get("nextPageToken")
                        break
                    except HttpError as e:
                        if attempt < retries - 1:
                            time.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        raise Exception(f"Lỗi API sau {retries} lần thử: {str(e)}")
                if not token:
                    break
        except HttpError as e:
            raise Exception(f"Lỗi API: {str(e)}")
        return items
    
    def get_video_stats(self, video_ids):
        view_counts = {}
        # Chia video_ids thành batch tối đa 50 ID mỗi lần (giới hạn API)
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i + 50]
            try:
                response = self.youtube.videos().list(
                    part="statistics",
                    id=",".join(batch_ids),
                    maxResults=50
                ).execute()
                for item in response.get("items", []):
                    vid = item["id"]
                    view_count = int(item["statistics"].get("viewCount", 0))
                    view_counts[vid] = view_count
            except Exception as e:
                logger.error(f"Lỗi khi lấy viewCount cho batch {batch_ids}: {str(e)}")
        return view_counts