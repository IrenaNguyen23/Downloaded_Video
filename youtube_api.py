from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time
import logging
import json
import os

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
        self.cache_file = "youtube_cache.json"
        self.cache_ttl = 86400  # 24 hours

    def _load_cache(self, cache_key):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                if (cache_key in cache_data and
                        time.time() - cache_data[cache_key].get("timestamp", 0) < self.cache_ttl):
                    return cache_data[cache_key]["data"], cache_data[cache_key].get("etag")
            return None, None
        except Exception as e:
            logger.error(f"Lỗi khi đọc cache: {str(e)}")
            return None, None

    def _save_cache(self, cache_key, data, etag=None):
        try:
            cache_data = {}
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            cache_data[cache_key] = {
                "timestamp": time.time(),
                "data": data,
                "etag": etag
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Đã lưu cache cho {cache_key}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu cache: {str(e)}")

    def get_channel_id(self, url_or_handle):
        try:
            if "watch?v=" in url_or_handle:
                # Xử lý link video
                video_id = url_or_handle.split("watch?v=")[-1].split("&")[0]
                return video_id, "video"
            if "channel/" in url_or_handle:
                return url_or_handle.split("channel/")[1].split("/")[0], "channel"
            if "@" in url_or_handle:
                handle = url_or_handle.split("@")[-1].strip("/")
                cache_key = f"channel_{handle}"
                cached_data, _ = self._load_cache(cache_key)
                if cached_data:
                    return cached_data, "channel"
                resp = self.youtube.channels().list(
                    part="id",
                    forHandle=handle
                ).execute()
                if not resp.get("items"):
                    raise Exception(f"Không tìm thấy channel với handle {handle}")
                channel_id = resp["items"][0]["id"]
                self._save_cache(cache_key, channel_id, resp.get("etag"))
                return channel_id, "channel"
            if "/c/" in url_or_handle:
                custom_url = url_or_handle.split("/c/")[-1].strip("/")
                cache_key = f"channel_{custom_url}"
                cached_data, _ = self._load_cache(cache_key)
                if cached_data:
                    return cached_data, "channel"
                resp = self.youtube.channels().list(
                    part="id",
                    forUsername=custom_url
                ).execute()
                if not resp.get("items"):
                    raise Exception(f"Không tìm thấy channel với custom URL {custom_url}")
                channel_id = resp["items"][0]["id"]
                self._save_cache(cache_key, channel_id, resp.get("etag"))
                return channel_id, "channel"
            raise Exception("URL hoặc handle không hợp lệ")
        except HttpError as e:
            raise Exception(f"Lỗi API: {str(e)}")

    def fetch_all_videos(self, channel_id):
        cache_key = f"videos_{channel_id}"
        cached_data, cached_etag = self._load_cache(cache_key)
        if cached_data:
            logger.info(f"Đã sử dụng cache cho danh sách video của channel {channel_id}")
            return cached_data

        items = []
        token = None
        retries = 3
        try:
            channel_resp = self.youtube.channels().list(
                part="contentDetails",
                id=channel_id
            ).execute()
            if not channel_resp.get("items"):
                raise Exception("Không tìm thấy kênh")
            playlist_id = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

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
                            time.sleep(2 ** attempt)
                            continue
                        raise Exception(f"Lỗi API sau {retries} lần thử: {str(e)}")
                if not token:
                    break
            self._save_cache(cache_key, items, resp.get("etag"))
        except HttpError as e:
            raise Exception(f"Lỗi API: {str(e)}")
        return items

    def fetch_single_video(self, video_id):
        cache_key = f"video_{video_id}"
        cached_data, cached_etag = self._load_cache(cache_key)
        if cached_data:
            logger.info(f"Đã sử dụng cache cho video {video_id}")
            return cached_data

        try:
            resp = self.youtube.videos().list(
                part="snippet,statistics",
                id=video_id,
                maxResults=1
            ).execute()
            if not resp.get("items"):
                raise Exception(f"Không tìm thấy video với ID {video_id}")
            item = resp["items"][0]
            self._save_cache(cache_key, item, resp.get("etag"))
            return item
        except HttpError as e:
            raise Exception(f"Lỗi API: {str(e)}")

    def get_video_stats(self, video_ids):
        cache_key = f"stats_{','.join(video_ids[:50])}"
        cached_data, _ = self._load_cache(cache_key)
        if cached_data:
            return cached_data

        view_counts = {}
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
                self._save_cache(cache_key, view_counts, response.get("etag"))
            except Exception as e:
                logger.error(f"Lỗi khi lấy viewCount cho batch {batch_ids}: {str(e)}")
        return view_counts