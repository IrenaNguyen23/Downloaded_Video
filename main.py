import os
from dotenv import load_dotenv
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import io
import requests
import yt_dlp
import shutil
import re
import json
import time
import sys
import subprocess
from youtube_api import YouTubeAPIWrapper
from concurrent.futures import ThreadPoolExecutor
import logging
import queue

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", mode="a", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise ValueError("YOUTUBE_API_KEY không được cấu hình trong .env")

class VideoItem(tk.Frame):
    def __init__(self, parent, video_id, title, thumb_url, published_at, view_count):
        super().__init__(parent, bd=1, relief="flat", padx=5, pady=5, bg="white", highlightthickness=1)
        self.video_id = video_id
        self.url = f"https://www.youtube.com/watch?v={video_id}"
        self.selected = tk.BooleanVar()
        self.thumb_url = thumb_url
        self.published_at = published_at
        self.view_count = view_count
        self.title = title.strip()
        self.file_path = None  # Lưu đường dẫn file sau khi tải

        tk.Checkbutton(self, variable=self.selected, bg="white").grid(row=0, column=0, sticky="nw")
        self.thumb_label = tk.Label(self, text="[Đang tải ảnh…]", width=160, height=90, bg="#eee")
        self.thumb_label.grid(row=1, column=0, pady=(0, 5))
        self.lbl_title = tk.Label(
            self, text=self.title, wraplength=160, justify="left",
            font=("Arial", 10, "bold"), bg="white"
        )
        self.lbl_title.grid(row=2, column=0, pady=(0, 5))
        self.lbl_status = tk.Label(self, text="Chưa tải", fg="gray", bg="white", font=("Arial", 10))
        self.lbl_status.grid(row=3, column=0, pady=(0, 5))

        self.bind("<Enter>", lambda e: self.config(bg="#f0f0f0"))
        self.bind("<Leave>", lambda e: self.config(bg="white"))
        for child in self.winfo_children():
            child.bind("<Enter>", lambda e: self.config(bg="#f0f0f0"))
            child.bind("<Leave>", lambda e: self.config(bg="white"))
        
        # Sự kiện nhấp chuột để mở thư mục
        self.bind("<Double-1>", self.open_file_location)
        for child in self.winfo_children():
            child.bind("<Double-1>", self.open_file_location)

    def load_thumbnail(self, executor):
        def load():
            try:
                resp = requests.get(self.thumb_url, timeout=5)
                img = Image.open(io.BytesIO(resp.content)).resize((160, 90), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.thumb_label.after(0, lambda: self.thumb_label.config(image=photo, text=""))
                self.photo = photo
            except Exception as e:
                self.thumb_label.after(0, lambda: self.thumb_label.config(text="[Lỗi ảnh]", bg="#ccc"))
                logger.error(f"Lỗi tải thumbnail {self.thumb_url}: {str(e)}")

        executor.submit(load)

    def is_selected(self):
        return self.selected.get()

    def update_status(self, success, file_path=None):
        if success:
            self.lbl_status.config(text="Đã tải", fg="green")
            self.file_path = file_path  # Lưu đường dẫn file
        else:
            self.lbl_status.config(text="Lỗi", fg="red")

    def open_file_location(self, event):
        if self.lbl_status.cget("text") == "Đã tải" and self.file_path:
            try:
                # Mở thư mục và highlight file trên Windows
                subprocess.run(['explorer', '/select,', os.path.normpath(self.file_path)])
            except Exception as e:
                logger.error(f"Lỗi khi mở thư mục: {str(e)}")
                messagebox.showerror("Lỗi", f"Không thể mở thư mục: {str(e)}")

class YouTubeDownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Channel Downloader")
        self.geometry(self.load_config().get("geometry", "920x720"))
        self.configure(bg="#f5f5f5")
        if sys.platform == 'win32':
            icon_path = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'youtube.ico')
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.yt_api = YouTubeAPIWrapper(API_KEY)
        self.video_items = []
        self.all_video_items = []  # Lưu tất cả video để hỗ trợ tìm kiếm
        self.download_path = os.getcwd()
        self.current_columns = 4
        self.video_item_width = 180
        self.history = self.load_history()  # Tải lịch sử khi khởi động

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TButton", font=("Arial", 10), padding=6)
        self.style.configure("TLabel", font=("Arial", 10), background="#f5f5f5")
        self.style.configure("TCheckbutton", font=("Arial", 10), background="#f5f5f5")
        self.style.configure("TCombobox", font=("Arial", 10))
        self.style.configure("TProgressbar", thickness=20)

        self._build_ui()

    def _build_ui(self):
        top = tk.Frame(self, bg="#f5f5f5")
        top.pack(fill="x", padx=10, pady=10)
        tk.Label(top, text="URL kênh, @handle hoặc video:", font=("Arial", 10), bg="#f5f5f5").pack(side="left")
        self.url_entry = ttk.Entry(top, width=60, font=("Arial", 10))
        self.url_entry.pack(side="left", padx=5)
        self.url_entry.bind("<Enter>", lambda e: self.show_tooltip(self.url_entry, "Nhập link kênh YouTube, @handle hoặc link video"))
        self.url_entry.bind("<Leave>", lambda e: self.hide_tooltip())
        self.fetch_btn = ttk.Button(top, text="Lấy danh sách video", command=self._thread_fetch)
        self.fetch_btn.pack(side="left")
        self.fetch_btn.bind("<Enter>", lambda e: self.show_tooltip(self.fetch_btn, "Tải danh sách video hoặc thông tin video"))
        self.fetch_btn.bind("<Leave>", lambda e: self.hide_tooltip())

        opts = tk.Frame(self, bg="#f5f5f5")
        opts.pack(fill="x", padx=10, pady=5)
        self.folder_btn = ttk.Button(opts, text="Chọn thư mục", command=self.select_folder)
        self.folder_btn.pack(side="left")
        self.folder_btn.bind("<Enter>", lambda e: self.show_tooltip(self.folder_btn, "Chọn thư mục lưu video"))
        self.folder_btn.bind("<Leave>", lambda e: self.hide_tooltip())
        self.path_label = ttk.Label(opts, text=f"Lưu tại: {self.download_path}")
        self.path_label.pack(side="left", padx=10)
        tk.Label(opts, text="Chế độ tải:", font=("Arial", 10), bg="#f5f5f5").pack(side="left", padx=5)
        self.download_mode = tk.StringVar(value="video+audio")
        self.mode_cb = ttk.Combobox(
            opts, textvariable=self.download_mode,
            values=["video+audio", "video", "audio"], width=15, state="readonly"
        )
        self.mode_cb.pack(side="left")
        self.mode_cb.bind("<Enter>", lambda e: self.show_tooltip(self.mode_cb, "Chọn chế độ tải: Video + Âm thanh, Chỉ video, hoặc Chỉ âm thanh"))
        self.mode_cb.bind("<Leave>", lambda e: self.hide_tooltip())
        ttk.Label(opts, text="Sắp xếp:").pack(side="left", padx=5)
        self.sort_var = tk.StringVar(value="latest")
        self.sort_cb = ttk.Combobox(
            opts, textvariable=self.sort_var, values=["latest", "oldest", "popular"], width=10, state="readonly"
        )
        self.sort_cb.pack(side="left")
        self.sort_cb.bind("<<ComboboxSelected>>", lambda e: self.sort_videos())
        self.sort_cb.bind("<Enter>", lambda e: self.show_tooltip(self.sort_cb, "Sắp xếp video theo tiêu chí"))
        self.sort_cb.bind("<Leave>", lambda e: self.hide_tooltip())
        ttk.Label(opts, text="Tìm kiếm:").pack(side="left", padx=5)
        self.search_entry = ttk.Entry(opts, width=20, font=("Arial", 10))
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", self.search_videos)
        self.search_entry.bind("<Enter>", lambda e: self.show_tooltip(self.search_entry, "Nhập từ khóa để tìm video"))
        self.search_entry.bind("<Leave>", lambda e: self.hide_tooltip())

        middle = tk.Frame(self, bg="#f5f5f5")
        middle.pack(fill="both", expand=True, padx=10, pady=5)
        self.canvas = tk.Canvas(middle, highlightthickness=0, bg="#ffffff")
        vsb = ttk.Scrollbar(middle, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.frame_videos = tk.Frame(self.canvas, bg="#ffffff")
        self.canvas.create_window((0, 0), window=self.frame_videos, anchor="nw")
        self.frame_videos.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        bottom = tk.Frame(self, bg="#f5f5f5")
        bottom.pack(fill="x", padx=10, pady=10)
        self.download_btn = ttk.Button(bottom, text="Tải video đã chọn", command=self.download_selected)
        self.download_btn.pack(side="left")
        self.download_btn.bind("<Enter>", lambda e: self.show_tooltip(self.download_btn, "Tải các video được chọn"))
        self.download_btn.bind("<Leave>", lambda e: self.hide_tooltip())
        self.select_all_btn = ttk.Button(bottom, text="Chọn tất cả", command=self.select_all)
        self.select_all_btn.pack(side="left", padx=5)
        self.select_all_btn.bind("<Enter>", lambda e: self.show_tooltip(self.select_all_btn, "Chọn tất cả video"))
        self.select_all_btn.bind("<Leave>", lambda e: self.hide_tooltip())
        self.deselect_all_btn = ttk.Button(bottom, text="Hủy chọn", command=self.deselect_all)
        self.deselect_all_btn.pack(side="left", padx=5)
        self.deselect_all_btn.bind("<Enter>", lambda e: self.show_tooltip(self.deselect_all_btn, "Bỏ chọn tất cả video"))
        self.deselect_all_btn.bind("<Leave>", lambda e: self.hide_tooltip())
        self.status_label = ttk.Label(bottom, text="Trạng thái: sẵn sàng", foreground="blue")
        self.status_label.pack(side="left", padx=20)
        self.progress = ttk.Progressbar(bottom, length=self.winfo_screenwidth() // 3, mode="determinate")
        self.progress.pack(side="left", padx=10)
        self.progress_label = ttk.Label(bottom, text="")
        self.progress_label.pack(side="left")

        self.tooltip = None

    def show_tooltip(self, widget, text):
        if self.tooltip:
            self.tooltip.destroy()
        x, y = widget.winfo_rootx() + 20, widget.winfo_rooty() + 20
        self.tooltip = tk.Toplevel(self)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip, text=text, bg="#ffffe0", relief="solid", borderwidth=1, font=("Arial", 9))
        label.pack()

    def hide_tooltip(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def _on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    def _on_canvas_configure(self, event):
        canvas_width = event.width
        num_columns = max(2, min(10, canvas_width // self.video_item_width))
        if num_columns != self.current_columns:
            self.current_columns = num_columns
            self.update_grid_layout()

    def update_grid_layout(self):
        if not self.video_items:
            return
        for w in self.frame_videos.winfo_children():
            w.grid_forget()
        for index, item in enumerate(self.video_items):
            item.grid(row=index // self.current_columns, column=index % self.current_columns, padx=10, pady=10, sticky="ew")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _thread_fetch(self):
        self.fetch_btn.config(state="disabled")
        threading.Thread(target=self.fetch_videos, daemon=True).start()

    def clean_video_title(self, title):
        return re.sub(r'#\S+', '', title).strip()

    def search_videos(self, event=None):
        query = self.search_entry.get().strip().lower()
        if not query:
            self.video_items = self.all_video_items.copy()
        else:
            self.video_items = [
                item for item in self.all_video_items
                if query in item.title.lower()
            ]
        self.update_grid_layout()
        self._update_status(f"Đã lọc {len(self.video_items)} video")

    def fetch_videos(self):
        try:
            channel_url = self.url_entry.get().strip()
            self._update_status("Đang xác định URL…")
            id_value, id_type = self.yt_api.get_channel_id(channel_url)
            self._update_status("Đang tải thông tin…")
            self.clear_videos()

            thumbnail_executor = ThreadPoolExecutor(max_workers=4)

            if id_type == "video":
                item = self.yt_api.fetch_single_video(id_value)
                v_id = item["id"]
                s = item["snippet"]
                title = s["title"]
                thumb_url = s["thumbnails"].get("medium", {}).get("url") or s["thumbnails"].get("default", {}).get("url")
                published_at = s["publishedAt"]
                view_count = int(item["statistics"].get("viewCount", 0))

                clean_title = self.clean_video_title(title)
                video_item = VideoItem(
                    self.frame_videos, video_id=v_id, title=clean_title, thumb_url=thumb_url,
                    published_at=published_at, view_count=view_count
                )
                video_item.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
                video_item.load_thumbnail(thumbnail_executor)
                self.video_items.append(video_item)
                self.all_video_items.append(video_item)
            else:
                items = self.yt_api.fetch_all_videos(id_value)
                video_ids = [
                    vid["id"]["videoId"] if "videoId" in vid["id"] else vid["snippet"]["resourceId"]["videoId"]
                    for vid in items
                ]

                self._update_status("Đang lấy thông tin lượt xem…")
                view_counts = self.yt_api.get_video_stats(video_ids)
                total_videos = len(video_ids)
                processed = 0
                self.progress["maximum"] = total_videos
                self.progress["value"] = 0

                for index, vid in enumerate(items):
                    s = vid["snippet"]
                    v_id = video_ids[index]
                    title = s["title"]
                    thumb_url = s["thumbnails"].get("medium", {}).get("url") or s["thumbnails"].get("default", {}).get("url")
                    published_at = s["publishedAt"]
                    view_count = view_counts.get(v_id, 0)

                    clean_title = self.clean_video_title(title)
                    item = VideoItem(
                        self.frame_videos, video_id=v_id, title=clean_title, thumb_url=thumb_url,
                        published_at=published_at, view_count=view_count
                    )
                    item.grid(row=index // self.current_columns, column=index % self.current_columns, padx=10, pady=10, sticky="ew")
                    item.load_thumbnail(thumbnail_executor)
                    self.video_items.append(item)
                    self.all_video_items.append(item)

                    processed += 1
                    self.progress["value"] = processed
                    self.progress_label.config(text=f"{int(processed / total_videos * 100)}%")
                    self.update_idletasks()

            self.progress["value"] = 0
            self.progress_label.config(text="")
            self.sort_videos()
            self._update_status(f"Đã tải {len(self.video_items)} video")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            self._update_status("Lỗi khi tải video")
            logger.exception(f"Lỗi khi fetch video: {str(e)}")
        finally:
            self.fetch_btn.config(state="normal")

    def clear_videos(self):
        for w in self.frame_videos.winfo_children():
            w.grid_forget()
            w.destroy()
        self.video_items.clear()
        self.all_video_items.clear()

    def sort_videos(self):
        mode = self.sort_var.get()
        if mode == "latest":
            self.video_items.sort(key=lambda w: w.published_at, reverse=True)
        elif mode == "oldest":
            self.video_items.sort(key=lambda w: w.published_at)
        elif mode == "popular":
            self.video_items.sort(key=lambda w: w.view_count, reverse=True)

        self.update_grid_layout()
        self._update_status(f"Đã sắp xếp theo {mode}")

    def select_folder(self):
        d = filedialog.askdirectory(initialdir=os.path.expanduser("~"))
        if d:
            self.download_path = d
            self.path_label.config(text=f"Lưu tại: {d}")

    def select_all(self):
        for item in self.video_items:
            item.selected.set(True)
        self._update_status("Đã chọn tất cả video")

    def deselect_all(self):
        for item in self.video_items:
            item.selected.set(False)
        self._update_status("Đã hủy chọn tất cả video")

    def download_task(self, video_item, result_queue, progress_queue):
        success, file_path = self._download(video_item.url, progress_queue)
        result_queue.put((video_item, success, file_path))

    def download_selected(self):
        sel = [w for w in self.video_items if w.is_selected()]
        if not sel:
            messagebox.showinfo("Thông báo", "Bạn chưa chọn video nào.")
            return

        self._update_status(f"Đang tải 0/{len(sel)} video…")
        self.download_btn.config(state="disabled")
        self.progress["maximum"] = 100
        self.progress["value"] = 0
        self.progress_label.config(text="0%")

        result_queue = queue.Queue()
        progress_queue = queue.Queue()

        total_bytes = {w.url: 0 for w in sel}
        downloaded_bytes = {w.url: 0 for w in sel}
        completed_videos = 0

        def download_in_thread():
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(self.download_task, w, result_queue, progress_queue) for w in sel]
                for future in futures:
                    future.result()

        def check_queues():
            try:
                while True:
                    msg_type, url, *data = progress_queue.get_nowait()
                    if msg_type == "progress":
                        downloaded, total = data
                        downloaded_bytes[url] = downloaded
                        total_bytes[url] = max(total_bytes[url], total)
                        total_sum = sum(total_bytes.values())
                        downloaded_sum = sum(downloaded_bytes.values())
                        if total_sum > 0:
                            percent = min(100, (downloaded_sum / total_sum) * 100)
                            self.progress["value"] = percent
                            self.progress_label.config(text=f"{int(percent)}%")
                    elif msg_type == "finished":
                        downloaded_bytes[url] = total_bytes.get(url, 0)
            except queue.Empty:
                pass

            try:
                while True:
                    video_item, success, file_path = result_queue.get_nowait()
                    video_item.update_status(success, file_path)
                    nonlocal completed_videos
                    completed_videos = sum(1 for w in sel if w.lbl_status.cget("text") in ["Đã tải", "Lỗi"])
                    self._update_status(f"Đang tải {completed_videos}/{len(sel)} video…")
                    if completed_videos == len(sel):
                        self._update_status("Tải hoàn tất")
                        self.download_btn.config(state="normal")
                        self.progress["value"] = 0
                        self.progress_label.config(text="")
                        return
            except queue.Empty:
                pass

            self.after(100, check_queues)

        threading.Thread(target=download_in_thread, daemon=True).start()
        self.after(100, check_queues)

    def _download(self, url, progress_queue):
        def progress_hook(d):
            if d["status"] == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                if total > 0:
                    progress_queue.put(("progress", url, downloaded, total))
            elif d["status"] == "finished":
                progress_queue.put(("finished", url))

        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
        ffmpeg_path = os.path.join(base_dir, ffmpeg_name)
        if not os.path.exists(ffmpeg_path):
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                logger.error("FFmpeg không tìm thấy trong ứng dụng hoặc PATH")
                return False, None

        mode = self.download_mode.get()
        opts = {
            "outtmpl": os.path.join(self.download_path, "%(title)s.%(ext)s"),
            "quiet": True,
            "noplaylist": True,
            "restrictfilenames": True,
            "retries": 3,
            "fragment_retries": 3,
            "progress_hooks": [progress_hook],
        }

        if mode == "video+audio":
            opts.update({
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4"
            })
            if not shutil.which("ffmpeg"):
                logger.error("FFmpeg không được cài đặt")
                return False, None
        elif mode == "video":
            opts.update({"format": "bestvideo"})
        elif mode == "audio":
            opts.update({
                "format": "bestaudio[ext=m4a]",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }],
            })
            if not shutil.which("ffmpeg"):
                logger.error("FFmpeg không được cài đặt")
                return False, None

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                file_path = ydl.prepare_filename(info)
                if os.path.exists(file_path):
                    logger.info(f"Video đã tồn tại: {file_path}")
                    self.history[url] = {"file_path": file_path, "timestamp": time.time()}
                    self.save_history()
                    return True, file_path
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
            logger.info(f"Tải thành công: {url}")
            self.history[url] = {"file_path": file_path, "timestamp": time.time()}
            self.save_history()
            return True, file_path
        except Exception as e:
            logger.error(f"Lỗi tải video {url}: {str(e)}")
            return False, None

    def load_history(self):
        try:
            with open("download_history.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"Lỗi khi đọc lịch sử tải: {str(e)}")
            return {}

    def save_history(self):
        try:
            with open("download_history.json", "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lỗi khi lưu lịch sử tải: {str(e)}")

    def _update_status(self, msg):
        self.status_label.config(text=f"Trạng thái: {msg}")

    def save_config(self):
        config = {"geometry": self.geometry()}
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lỗi khi lưu config: {str(e)}")

    def load_config(self):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"Lỗi khi đọc config: {str(e)}")
            return {}

    def on_closing(self):
        self.save_config()
        self.destroy()

if __name__ == "__main__":
    app = YouTubeDownloaderApp()
    app.mainloop()