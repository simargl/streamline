#!/usr/bin/env python3

import threading
import time
import libtorrent as lt
import gi
import sys

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

ses = lt.session()
active_torrent_handle = None
current_download_id = 0


def format_size(num):
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)

    for unit in units:
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024

    return f"{value:.2f} PB"


def format_eta(seconds):
    if seconds <= 0:
        return "--:--"

    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"

class TorrentEngineApp(Gtk.Window):
    def __init__(self):
        super().__init__()

        self.set_title("Streamline")
        self.set_default_size(700, 320)
        self.set_border_width(16)

        try:
            self.set_icon_from_file("/usr/share/pixmaps/streamline.png")
        except Exception as err:
            print("Icon load error:", err)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(root_box)

        input_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root_box.pack_start(input_card, True, True, 0)

        title = Gtk.Label(label="MAGNET LINK")
        title.set_xalign(0.0)
        input_card.pack_start(title, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 140)

        self.magnet_input = Gtk.TextView()
        self.magnet_input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        self.txt_buffer = self.magnet_input.get_buffer()

        self.placeholder_text = "Paste your torrent magnet URI here..."
        self.is_placeholder_active = True
        self.txt_buffer.set_text(self.placeholder_text)

        self.magnet_input.connect("focus-in-event", self.on_focus_in)

        self.magnet_input.connect("focus-out-event", self.on_focus_out)

        scroll.add(self.magnet_input)
        input_card.pack_start(scroll, True, True, 0)

        controls = Gtk.Grid()
        controls.set_column_spacing(12)

        input_card.pack_start(controls, False, False, 0)

        self.btn = Gtk.Button(label="Open Link")
        self.btn.connect("clicked", self.start_download)

        controls.attach(self.btn, 0, 0, 1, 1)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_hexpand(True)

        controls.attach(self.progress_bar, 1, 0, 1, 1)

        self.status_headline = Gtk.Label(label="Status: Idle")
        self.status_headline.set_xalign(0.0)

        root_box.pack_start(self.status_headline, False, False, 0)

        self.info_label = Gtk.Label(
            label="0.00 B / 0.00 B | ETA --:-- | DL 0 KB/s | UL 0 KB/s | 0 Peers"
        )
        self.info_label.set_xalign(0.0)
        self.info_label.set_hexpand(True)

        root_box.pack_start(self.info_label, False, False, 0)

        self.connect("destroy", Gtk.main_quit)
        if len(sys.argv) > 1 and sys.argv[1].startswith("magnet:"):
            self.load_magnet(sys.argv[1])


    def load_magnet(self, magnet):
        self.is_placeholder_active = False
        self.txt_buffer.set_text(magnet)

        GLib.idle_add(
            lambda: self.start_download(None)
        )

    def on_focus_in(self, widget, event):
        if self.is_placeholder_active:
            self.txt_buffer.set_text("")
            self.is_placeholder_active = False
        return False

    def on_focus_out(self, widget, event):
        start, end = self.txt_buffer.get_bounds()

        text = self.txt_buffer.get_text(start, end, True).strip()

        if not text:
            self.txt_buffer.set_text(self.placeholder_text)
            self.is_placeholder_active = True

        return False

    def start_download(self, widget):
        global active_torrent_handle
        global current_download_id

        if self.is_placeholder_active:
            return

        start, end = self.txt_buffer.get_bounds()

        magnet = self.txt_buffer.get_text(start, end, True).strip()

        if not magnet:
            return

        magnet = magnet.replace("\n", "")
        magnet = magnet.replace("\r", "")

        if active_torrent_handle is not None:
            try:
                current_download_id += 1
                ses.remove_torrent(active_torrent_handle)
                active_torrent_handle = None

            except Exception as err:
                print("Stop error:", err)

        current_download_id += 1

        threading.Thread(
            target=self.torrent_thread,
            args=(magnet, current_download_id),
            daemon=True,
        ).start()

    def torrent_thread(self, magnet, download_id):
        global active_torrent_handle
        global current_download_id

        try:
            params = lt.parse_magnet_uri(magnet)
            params.save_path = "/mnt/home/data/torrent"

            handle = ses.add_torrent(params)
            active_torrent_handle = handle

            GLib.idle_add(
                self.status_headline.set_text, "Status: Resolving metadata..."
            )

            while True:
                if download_id != current_download_id:
                    break

                status = handle.status()

                progress = float(status.progress)

                downloaded = int(status.total_done)
                total = int(status.total_wanted)

                uploaded = int(getattr(status, "total_upload", 0))

                dl_speed = float(status.download_rate)
                ul_speed = float(status.upload_rate)

                peers = int(status.num_peers)
                seeders = int(getattr(status, "num_seeds", 0))

                remaining = max(total - downloaded, 0)

                eta = (
                    format_eta(remaining / dl_speed)
                    if dl_speed > 0
                    else "--:--"
                )

                if getattr(status, "is_seeding", False):
                    status_text = f"Status: Seeding ({seeders} seeders)"

                elif progress >= 1.0:
                    status_text = "Status: Complete"

                elif progress > 0:
                    status_text = "Status: Downloading"

                else:
                    status_text = "Status: Fetching metadata..."

                info = (
                    f"{format_size(downloaded)} / "
                    f"{format_size(total)}"
                    f" | ETA {eta}"
                    f" | DL {dl_speed/1024:.1f} KB/s"
                    f" | UL {ul_speed/1024:.1f} KB/s"
                    f" | ↑ {format_size(uploaded)}"
                    f" | {peers} Peers"
                )

                GLib.idle_add(self.status_headline.set_text, status_text)

                GLib.idle_add(self.progress_bar.set_fraction, progress)

                GLib.idle_add(
                    self.progress_bar.set_text, f"{progress * 100:.1f}%"
                )

                GLib.idle_add(self.progress_bar.set_show_text, True)

                GLib.idle_add(self.info_label.set_text, info)

                time.sleep(0.5)

        except Exception as err:
            GLib.idle_add(
                self.status_headline.set_text, f"Status: Error — {err}"
            )


if __name__ == "__main__":
    app = TorrentEngineApp()
    app.show_all()
    Gtk.main()
