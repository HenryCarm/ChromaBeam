import os
import sys
import json
import time

# If launched on desktop directly without Android environment, launch the PySide6 desktop app
if 'ANDROID_ARGUMENT' not in os.environ and 'ANDROID_PRIVATE' not in os.environ:
    try:
        import desktop_app
        if __name__ == '__main__':
            desktop_app.main()
            sys.exit(0)
    except Exception as e:
        print(f"[QR ChromaBeam] Falling back to Kivy UI: {e}")

import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.progressbar import ProgressBar
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.utils import platform

if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.CAMERA,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE
        ])
    except Exception as e:
        print(f"[Android Permissions] {e}")

try:
    from plyer import filechooser
except ImportError:
    filechooser = None

from PIL import Image as PILImage
import qrcode

from core.protocol import (
    pack_packet, unpack_packet,
    pack_file_metadata, unpack_file_metadata
)
from core.fountain import LTEncoder, LTDecoder

MODE_1BIT_BW = 0
MODE_2BIT_4COLOR = 1
MODE_3BIT_8COLOR = 2


class NativeChromaBeamApp(App):
    def build(self):
        self.title = "QR ChromaBeam"
        self.settings_file = os.path.join(self.user_data_dir, "chromabeam_settings.json")
        self.load_settings()

        self.root_layout = BoxLayout(orientation='vertical', padding=24, spacing=18)
        self._build_main_menu()
        return self.root_layout

    def load_settings(self):
        self.color_mode = MODE_1BIT_BW
        self.grid_size = 64
        self.target_fps = 15
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    self.color_mode = data.get("color_mode", MODE_1BIT_BW)
                    self.grid_size = data.get("grid_size", 64)
                    self.target_fps = data.get("target_fps", 15)
            except Exception:
                pass

    def save_settings(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump({
                    "color_mode": self.color_mode,
                    "grid_size": self.grid_size,
                    "target_fps": self.target_fps
                }, f)
        except Exception:
            pass

    def _build_main_menu(self):
        self.root_layout.clear_widgets()

        header = Label(
            text="[b]QR ChromaBeam[/b]\n[size=14sp]Air-Gapped Optical File Transfer[/size]",
            markup=True,
            font_size='26sp',
            size_hint_y=0.22,
            halign='center'
        )
        self.root_layout.add_widget(header)

        self.send_btn = Button(
            text="📡  SEND FILE",
            font_size='20sp',
            bold=True,
            size_hint_y=0.24,
            background_color=(0.18, 0.55, 0.95, 1.0)
        )
        self.send_btn.bind(on_press=self.on_send_clicked)
        self.root_layout.add_widget(self.send_btn)

        self.recv_btn = Button(
            text="📸  RECEIVE FILE",
            font_size='20sp',
            bold=True,
            size_hint_y=0.24,
            background_color=(0.18, 0.80, 0.44, 1.0)
        )
        self.recv_btn.bind(on_press=self.on_receive_clicked)
        self.root_layout.add_widget(self.recv_btn)

        self.adv_toggle = Button(
            text="⚙️ Advanced Parameters (Pro) ▼",
            font_size='15sp',
            size_hint_y=0.08,
            background_color=(0.12, 0.15, 0.20, 0.7)
        )
        self.adv_toggle.bind(on_press=self.toggle_advanced)
        self.root_layout.add_widget(self.adv_toggle)

        self.adv_container = BoxLayout(orientation='vertical', spacing=8, size_hint_y=None, height=0, opacity=0)

        self.mode_btn = Button(
            text=f"Mode: {self.get_mode_label()}",
            font_size='14sp',
            size_hint_y=None,
            height=44
        )
        self.mode_btn.bind(on_press=self.cycle_mode)
        self.adv_container.add_widget(self.mode_btn)

        self.grid_btn = Button(
            text=f"Density: {self.grid_size}x{self.grid_size}",
            font_size='14sp',
            size_hint_y=None,
            height=44
        )
        self.grid_btn.bind(on_press=self.cycle_grid)
        self.adv_container.add_widget(self.grid_btn)

        self.root_layout.add_widget(self.adv_container)

    def get_mode_label(self):
        if self.color_mode == MODE_1BIT_BW:
            return "1-Bit B&W (Default ~25 KB/s)"
        elif self.color_mode == MODE_2BIT_4COLOR:
            return "2-Bit 4-Color (~60 KB/s ⚡ 2x Faster)"
        else:
            return "3-Bit 8-Color (~120+ KB/s 🚀 3x Turbo)"

    def toggle_advanced(self, instance):
        if self.adv_container.height == 0:
            self.adv_container.height = 100
            self.adv_container.opacity = 1
            self.adv_toggle.text = "⚙️ Advanced Parameters (Pro) ▲"
        else:
            self.adv_container.height = 0
            self.adv_container.opacity = 0
            self.adv_toggle.text = "⚙️ Advanced Parameters (Pro) ▼"

    def cycle_mode(self, instance):
        self.color_mode = (self.color_mode + 1) % 3
        self.mode_btn.text = f"Mode: {self.get_mode_label()}"
        self.save_settings()

    def cycle_grid(self, instance):
        options = [32, 48, 64, 128]
        idx = options.index(self.grid_size) if self.grid_size in options else 2
        self.grid_size = options[(idx + 1) % len(options)]
        self.grid_btn.text = f"Density: {self.grid_size}x{self.grid_size}"
        self.save_settings()

    def on_send_clicked(self, instance):
        if filechooser:
            try:
                filechooser.open_file(on_selection=self._on_file_selected)
                return
            except Exception:
                pass
        self._start_beaming_payload(
            b"ChromaBeam-Mobile-HighSpeed-Airgap-Payload-Data\n" + os.urandom(32 * 1024),
            "chromabeam_sample.bin"
        )

    def _on_file_selected(self, selection):
        if selection and len(selection) > 0:
            filepath = selection[0]
            try:
                with open(filepath, "rb") as f:
                    data = f.read()
                self._start_beaming_payload(data, os.path.basename(filepath))
            except Exception as e:
                print(f"[File Read Error] {e}")

    def _start_beaming_payload(self, data: bytes, filename: str):
        self.root_layout.clear_widgets()

        self.file_data = data
        self.filename = filename
        self.filesize = len(data)
        self.file_id = int(time.time()) & 0xFFFF

        block_size = 200 if self.filesize <= 64 * 1024 else 350
        metadata_bytes = pack_file_metadata(self.filename, self.filesize)
        full_stream = metadata_bytes + self.file_data

        self.encoder = LTEncoder(full_stream, block_size=block_size)
        self.droplet_seed = 0
        self.total_droplets_sent = 0
        self.is_streaming = True

        info = Label(
            text=f"[b]{self.filename}[/b] ({self.filesize / 1024:.1f} KB)\nK={self.encoder.K} blocks",
            markup=True,
            font_size='16sp',
            size_hint_y=0.10
        )
        self.root_layout.add_widget(info)

        self.stream_img = Image(size_hint_y=0.72)
        self.root_layout.add_widget(self.stream_img)

        btn_row = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=0.12)
        self.pause_btn = Button(text="🛑 STOP BEAMING", background_color=(0.9, 0.2, 0.2, 1.0))
        self.pause_btn.bind(on_press=self.toggle_stream_pause)
        btn_row.add_widget(self.pause_btn)

        back_btn = Button(text="⬅️ BACK", background_color=(0.3, 0.3, 0.3, 1.0))
        back_btn.bind(on_press=self.stop_sender_and_exit)
        btn_row.add_widget(back_btn)

        self.root_layout.add_widget(btn_row)

        self.sender_event = Clock.schedule_interval(self._sender_tick, 1.0 / self.target_fps)

    def toggle_stream_pause(self, instance):
        self.is_streaming = not self.is_streaming
        if self.is_streaming:
            self.pause_btn.text = "🛑 STOP BEAMING"
            self.pause_btn.background_color = (0.9, 0.2, 0.2, 1.0)
        else:
            self.pause_btn.text = "🚀 RESUME BEAMING"
            self.pause_btn.background_color = (0.18, 0.8, 0.44, 1.0)

    def _sender_tick(self, dt):
        if not self.is_streaming or not hasattr(self, 'encoder') or self.encoder is None:
            return

        seed = self.droplet_seed
        self.droplet_seed += 1
        self.total_droplets_sent += 1

        _, _, block_payload = self.encoder.generate_droplet(seed)
        packet = pack_packet(
            file_id=self.file_id,
            total_blocks=self.encoder.K,
            block_size=self.encoder.block_size,
            seed=seed,
            payload=block_payload
        )

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2
        )
        qr.add_data(packet)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        w, h = img.size
        texture = Texture.create(size=(w, h), colorfmt='rgb')
        texture.blit_buffer(img.tobytes(), colorfmt='rgb', bufferfmt='ubyte')
        texture.flip_vertical()
        self.stream_img.texture = texture

    def stop_sender_and_exit(self, instance):
        if hasattr(self, 'sender_event') and self.sender_event:
            self.sender_event.cancel()
        self._build_main_menu()

    def on_receive_clicked(self, instance):
        self.root_layout.clear_widgets()

        title = Label(text="[b]Receiving Optical Stream[/b]", markup=True, font_size='18sp', size_hint_y=0.08)
        self.root_layout.add_widget(title)

        try:
            from kivy.uix.camera import Camera
            self.camera = Camera(play=True, resolution=(640, 480), size_hint_y=0.64)
            self.root_layout.add_widget(self.camera)
        except Exception as e:
            err_lbl = Label(text=f"Camera initialization: {e}", size_hint_y=0.64)
            self.root_layout.add_widget(err_lbl)
            self.camera = None

        self.rx_progress = ProgressBar(max=100, value=0, size_hint_y=0.06)
        self.root_layout.add_widget(self.rx_progress)

        self.rx_status = Label(text="Point camera at sender QR matrix...", font_size='14sp', size_hint_y=0.08)
        self.root_layout.add_widget(self.rx_status)

        back_btn = Button(text="⬅️ CANCEL", size_hint_y=0.12, background_color=(0.8, 0.2, 0.2, 1.0))
        back_btn.bind(on_press=self.stop_receiver_and_exit)
        self.root_layout.add_widget(back_btn)

        self.decoder = None
        self.rx_current_file_id = None

    def stop_receiver_and_exit(self, instance):
        if hasattr(self, 'camera') and self.camera:
            self.camera.play = False
        self._build_main_menu()


if __name__ == '__main__':
    NativeChromaBeamApp().run()
