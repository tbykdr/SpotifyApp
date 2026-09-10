import os
import io
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from PIL import Image, ImageTk



CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "XXX")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "XXX")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8000/callback")

SCOPE = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative"
)

POLL_INTERVAL_MS = 2000
ALBUM_ART_SIZE = 260



def make_spotify_client() -> spotipy.Spotify:
    if "XXX" in CLIENT_ID or "XXX" in CLIENT_SECRET:
        raise RuntimeError(
            "Fill in credentials"
        )
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=".spotify_token_cache",
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)



class SpotifyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spotify Homebrew App")
        self.geometry("980x600")
        self.minsize(820, 690)
        self.configure(bg="#121212")

        self._album_art_cache = {}  # url -> ImageTk.PhotoImage
        self._current_track_id = None
        self._current_album_url = None
        self._is_playing = False
        self._loaded_playlist_ids = set()  # playlists whose tracks are already loaded

        self._build_style()

        try:
            self.sp = make_spotify_client()
        except Exception as e:
            messagebox.showerror("Spotify Auth Error", str(e))
            self.destroy()
            return

        self._build_layout()
        self._load_playlists()
        self._poll_now_playing()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#121212"
        panel_bg = "#181818"
        fg = "#FFFFFF"
        sub_fg = "#B3B3B3"
        accent = "#1DB954"

        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel_bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Panel.TLabel", background=panel_bg, foreground=fg)
        style.configure("Sub.TLabel", background=panel_bg, foreground=sub_fg, font=("Helvetica", 10))
        style.configure("Title.TLabel", background=panel_bg, foreground=fg, font=("Helvetica", 15, "bold"))
        style.configure("Header.TLabel", background=bg, foreground=fg, font=("Helvetica", 12, "bold"))

        style.configure(
            "Accent.TButton",
            background=accent,
            foreground="#000000",
            borderwidth=0,
            font=("Helvetica", 10, "bold"),
            padding=6,
        )
        style.map("Accent.TButton", background=[("active", "#1ed760")])

        style.configure(
            "Ctrl.TButton",
            background=panel_bg,
            foreground=fg,
            borderwidth=0,
            font=("Helvetica", 12, "bold"),
            padding=8,
        )
        style.map("Ctrl.TButton", background=[("active", "#282828")])

        style.configure(
            "Treeview",
            background=panel_bg,
            fieldbackground=panel_bg,
            foreground=fg,
            borderwidth=0,
            rowheight=26,
            font=("Helvetica", 10),
        )
        style.configure("Treeview.Heading", background="#282828", foreground=fg, borderwidth=0)
        style.map("Treeview", background=[("selected", "#1DB954")], foreground=[("selected", "#000000")])

        style.configure(
            "TScrollbar",
            background=panel_bg,
            troughcolor="#3E3E3E",
        )

        style.configure(
            "Vol.Horizontal.TScale",
            background=panel_bg,
            troughcolor="#3E3E3E",
        )

    def _build_layout(self):
        container = ttk.Frame(self, style="TFrame")
        container.pack(fill="both", expand=True, padx=12, pady=12)

        container.columnconfigure(0, weight=1, minsize=340)
        container.columnconfigure(1, weight=1, minsize=380)
        container.rowconfigure(0, weight=1)

        self._build_left_panel(container)
        self._build_right_panel(container)

    def _build_left_panel(self, parent):
        left = ttk.Frame(parent, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Now Playing", style="Title.TLabel").pack(
            anchor="w", padx=20, pady=(20, 10)
        )

        #Album art
        self.art_label = tk.Label(left, bg="#181818", width=ALBUM_ART_SIZE, height=ALBUM_ART_SIZE)
        self.art_label.pack(padx=20, pady=10)
        self._set_placeholder_art()

        #Track info
        self.track_name_lbl = ttk.Label(
            left, text="Nothing playing", style="Panel.TLabel",
            font=("Helvetica", 14, "bold"), wraplength=300, justify="center"
        )
        self.track_name_lbl.pack(padx=20, pady=(10, 0))

        self.album_lbl = ttk.Label(
            left, text="", style="Sub.TLabel",
            wraplength=300, justify="center")
        self.album_lbl.pack(padx=20, pady=(0, 4))

        self.artist_lbl = ttk.Label(
            left, text="", style="Sub.TLabel", 
            font=("Helvetica", 10, "bold"), wraplength=300, justify="center"
        )
        self.artist_lbl.pack(padx=20, pady=(0, 12))

        #Time/progress bar
        time_frame = ttk.Frame(left, style="Panel.TFrame")
        time_frame.columnconfigure(0, weight=1)
        time_frame.columnconfigure(1, weight=1)
        time_frame.columnconfigure(2, weight=1)
        time_frame.pack(padx=20, fill="x")
        self.elapsed_lbl = ttk.Label(time_frame, text="0:00", style="Sub.TLabel", justify="right")
        self.elapsed_lbl.grid(row=0, column=0, sticky="e")
        self.progress = ttk.Progressbar(time_frame, orient="horizontal", mode="determinate", length=260)
        self.progress.grid(row=0, column=1, sticky="we", padx=5)
        self.duration_lbl = ttk.Label(time_frame, text="0:00", style="Sub.TLabel" , justify="left")
        self.duration_lbl.grid(row=0, column=2, sticky="w")

        #Playback controls
        ctrl_frame = ttk.Frame(left, style="Panel.TFrame")
        ctrl_frame.pack(pady=20)

        self.shuffle_btn = ttk.Button(
            ctrl_frame, text="🔀", width=3, style="Ctrl.TButton",
            command=self.toggle_shuffle
            )
        self.shuffle_btn.grid(row=0, column=0, padx=6)

        self.rewind_btn = ttk.Button(
            ctrl_frame, text="⏮", width=3, style="Ctrl.TButton",
            command=self.previous_track
            )
        self.rewind_btn.grid(row=0, column=1, padx=6)

        self.play_pause_btn = ttk.Button(
            ctrl_frame, text="⏸", width=3, style="Accent.TButton",
            command=self.toggle_play_pause
            )
        self.play_pause_btn.grid(row=0, column=2, padx=6)

        self.next_btn = ttk.Button(
            ctrl_frame, text="⏭", width=3, style="Ctrl.TButton",
            command=self.next_track
            )
        self.next_btn.grid(row=0, column=3, padx=6)

        self.repeat_btn = ttk.Button(
            ctrl_frame, text="🔁", width=3, style="Ctrl.TButton",
            command=self.toggle_repeat
        )
        self.repeat_btn.grid(row=0, column=4, padx=6)

        #Volume
        vol_frame = ttk.Frame(left, style="Panel.TFrame")
        vol_frame.pack(padx=20, pady=(10, 20), fill="x")
        ttk.Label(vol_frame, text="🔊", style="Panel.TLabel").pack(side="left")
        self.volume_scale = ttk.Scale(
            vol_frame, from_=0, to=100, orient="horizontal",
            style="Vol.Horizontal.TScale", command=self._on_volume_change
        )
        self.volume_scale.set(50)
        self.volume_scale.pack(side="left", fill="x", expand=True, padx=10)

        #Status label
        self.status_lbl = ttk.Label(left, text="", style="Sub.TLabel")
        self.status_lbl.pack(side="bottom", pady=(0, 10))

    def _set_placeholder_art(self):
        img = Image.new("RGB", (ALBUM_ART_SIZE, ALBUM_ART_SIZE), "#282828")
        photo = ImageTk.PhotoImage(img)
        self.art_label.configure(image=photo)
        self.art_label.image = photo

    def _build_right_panel(self, parent):
        right = ttk.Frame(parent, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        header = ttk.Frame(right, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        ttk.Label(header, text="Your Playlists", style="Title.TLabel").pack(side="left")
        self.playlist_count_lbl = ttk.Label(header, text="0", style="Sub.TLabel")
        self.playlist_count_lbl.pack(side="left", padx=(10, 0))
        ttk.Button(header, text="⟳ Refresh", style="Ctrl.TButton",
                   command=self._load_playlists).pack(side="right")

        tree_frame = ttk.Frame(right, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        #File tree
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Double-1>", self._on_tree_double_click)


    def _load_playlists(self):
        self.tree.delete(*self.tree.get_children())
        self._loaded_playlist_ids.clear()

        def worker():
            try:
                playlists = []
                results = self.sp.current_user_playlists(limit=50)
                playlists.extend(results["items"])
                self.playlist_count_lbl.config(text=str(len(playlists)))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error loading playlists", str(e)))
                return

            def populate():
                for pl in playlists:
                    node = self.tree.insert(
                        "", "end",
                        text=f"📁 {pl['name']}  ({pl['items']['total']})",
                        values=(pl["id"], pl["type"]),
                        open=False,
                    )
                    self.tree.insert(node, "end", text="Loading...", values=("", "dummy"))

            self.after(0, populate)

        threading.Thread(target=worker, daemon=True).start()

    def _on_tree_open(self, event):
        node = self.tree.focus()
        vals = self.tree.item(node, "values")
        if len(vals) < 2 or vals[1] != "playlist":
            return
        playlist_id = vals[0]
        if playlist_id in self._loaded_playlist_ids:
            return
        self._loaded_playlist_ids.add(playlist_id)

        def worker():
            try:
                tracks = []
                results = self.sp.playlist_items(
                    playlist_id,
                    fields="items(item(id,name,artists(name),duration_ms)),next",
                    additional_types=["track"],
                )
                tracks.extend(results["items"])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error loading tracks", str(e)))
                return

            def populate():
                for child in self.tree.get_children(node):
                    self.tree.delete(child)
                for item in tracks:
                    track = item.get("item")
                    if not track:
                        continue
                    artists = ", ".join(a["name"] for a in track.get("artists", []))
                    duration = self._format_ms(track.get("duration_ms", 0))
                    label = f"🎵 {track['name']} — {artists}  [{duration}]"
                    self.tree.insert(
                        node, "end", text=label,
                        values=(track.get("id", ""), "track"),
                    )

            populate()

        threading.Thread(target=worker, daemon=True).start()

    def _on_tree_double_click(self, event):
        node = self.tree.focus()
        vals = self.tree.item(node, "values")
        if len(vals) < 2 or vals[1] != "track" or not vals[0]:
            return
        track_uri = f"spotify:track:{vals[0]}"
        try:
            self.sp.start_playback(uris=[track_uri])
            self.status_lbl.configure(text="Playing selected track…")
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    @staticmethod
    def _format_ms(ms):
        seconds = int(ms / 1000)
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"

    def _poll_now_playing(self):
        def worker():
            try:
                current = self.sp.current_playback()
            except Exception as e:
                current = None
                self.after(0, lambda: self.status_lbl.configure(text=f"API error: {e}"))
            self.after(0, lambda: self._update_now_playing(current))

        threading.Thread(target=worker, daemon=True).start()
        self.after(POLL_INTERVAL_MS, self._poll_now_playing)

    def _update_now_playing(self, current):
        if not current or not current.get("item"):
            self.track_name_lbl.configure(text="Nothing playing")
            self.artist_lbl.configure(text="")
            self.album_lbl.configure(text="")
            self.progress["value"] = 0
            self.elapsed_lbl.configure(text="0:00")
            self.duration_lbl.configure(text="0:00")
            self.play_pause_btn.configure(text="▶")
            self.status_lbl.configure(text="No active playback")
            self._current_track_id = None
            return

        item = current["item"]
        track_id = item.get("id")
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        album = item.get("album", {}).get("name", "")
        progress_ms = current.get("progress_ms", 0) or 0
        duration_ms = item.get("duration_ms", 1) or 1
        self._is_playing = bool(current.get("is_playing"))

        self.track_name_lbl.configure(text=item.get("name", ""))
        self.artist_lbl.configure(text=artists)
        self.album_lbl.configure(text=album)
        self.progress["maximum"] = duration_ms
        self.progress["value"] = progress_ms
        self.elapsed_lbl.configure(text=self._format_ms(progress_ms))
        self.duration_lbl.configure(text=self._format_ms(duration_ms))
        self.play_pause_btn.configure(text="⏸" if self._is_playing else "▶")
        self.status_lbl.configure(text="")

        #Shuffle/repeat indicator (visual only)
        self.shuffle_btn.state(["pressed"] if current.get("shuffle_state") else ["!pressed"])

        device = current.get("device") or {}
        if "volume_percent" in device and device["volume_percent"] is not None:
            self.volume_scale.set(device["volume_percent"])

        images = item.get("album", {}).get("images", [])
        art_url = images[0]["url"] if images else None
        if track_id != self._current_track_id or art_url != self._current_album_url:
            self._current_track_id = track_id
            self._current_album_url = art_url
            if art_url:
                threading.Thread(target=self._fetch_album_art, args=(art_url,), daemon=True).start()
            else:
                self._set_placeholder_art()

    def _fetch_album_art(self, url):
        try:
            if url in self._album_art_cache:
                photo = self._album_art_cache[url]
            else:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).resize(
                    (ALBUM_ART_SIZE, ALBUM_ART_SIZE), Image.LANCZOS
                )
                photo = ImageTk.PhotoImage(img)
                self._album_art_cache[url] = photo

            def apply():
                self.art_label.configure(image=photo)
                self.art_label.image = photo

            apply()
        except Exception as e:
            print(f"Error fetching album art: {e}")

    def toggle_play_pause(self):
        try:
            if self._is_playing:
                self.sp.pause_playback()
            else:
                self.sp.start_playback()
            self._is_playing = not self._is_playing
            self.play_pause_btn.configure(text="⏸" if self._is_playing else "▶")
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def next_track(self):
        try:
            self.sp.next_track()
            self.after(500, self._poll_now_playing)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def previous_track(self):
        try:
            self.sp.previous_track()
            self.after(500, self._poll_now_playing)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def toggle_shuffle(self):
        try:
            current = self.sp.current_playback()
            new_state = not (current.get("shuffle_state") if current else False)
            self.sp.shuffle(new_state)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def toggle_repeat(self):
        try:
            current = self.sp.current_playback()
            state = (current or {}).get("repeat_state", "off")
            next_state = {"off": "context", "context": "track", "track": "off"}[state]
            self.sp.repeat(next_state)
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def _on_volume_change(self, value):
        try:
            self.sp.volume(int(float(value)))
        except Exception:
            pass


if __name__ == "__main__":
    app = SpotifyApp()
    app.mainloop()
