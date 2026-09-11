import os
import sys
import threading
import time
import json
from functools import partial

# Check for desktop
if 'ANDROID_ARGUMENT' not in os.environ and 'ANDROID_PRIVATE' not in os.environ:
    try:
        import desktop_app
        if __name__ == '__main__':
            desktop_app.main()
            sys.exit(0)
    except ImportError:
        pass

import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.clock import Clock, mainthread
from kivy.graphics.texture import Texture
from kivy.utils import platform

# For Android camera/permissions
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass
else:
    import cv2

try:
    import numpy as np
    from plyer import filechooser
    from core.protocol import pack_packet, unpack_packet, pack_file_metadata, unpack_file_metadata
    from core.fountain import LTEncoder, LTDecoder
    from core.color_matrix import (
        ColorMatrixLayout, bytes_to_color_grid, color_grid_to_bytes, upscale_grid_for_display,
        packet_to_standard_qr_rgb, MODE_1BIT_BW, MODE_2BIT_4COLOR, MODE_3BIT_8COLOR
    )
    from desktop_receiver.tracker import OpticalTracker
    from desktop_receiver.color_classifier import AdaptiveColorClassifier
    import cv2
except ImportError as e:
    print(f"[QR ChromaBeam] Import Error: {e}")

class NativeChromaBeamApp(App):
    def build(self):
        self.title = "QR ChromaBeam"
        self.settings_file = os.path.join(self.user_data_dir, "chromabeam_settings.json")
        self.load_settings()

        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=20)
        
        # Simplistic UI
        self.title_lbl = Label(text="QR ChromaBeam", font_size='30sp', size_hint_y=0.2, bold=True)
        self.layout.add_widget(self.title_lbl)

        self.send_btn = Button(text="📡 Send File", font_size='24sp', size_hint_y=0.3, background_color=(0.2, 0.6, 1, 1))
        self.send_btn.bind(on_press=self.start_sender)
        self.layout.add_widget(self.send_btn)

        self.recv_btn = Button(text="📸 Receive File", font_size='24sp', size_hint_y=0.3, background_color=(0.2, 0.8, 0.2, 1))
        self.recv_btn.bind(on_press=self.start_receiver)
        self.layout.add_widget(self.recv_btn)

        self.adv_btn = Button(text="⚙️ Advanced Parameters (Pro) ▼", font_size='16sp', size_hint_y=0.1, background_color=(0, 0, 0, 0))
        self.adv_btn.bind(on_press=self.toggle_advanced)
        self.layout.add_widget(self.adv_btn)

        self.adv_layout = BoxLayout(orientation='vertical', size_hint_y=None, height=0, opacity=0)
        
        self.mode_btn = Button(text=f"Mode: {self.get_mode_text()}")
        self.mode_btn.bind(on_press=self.cycle_mode)
        self.adv_layout.add_widget(self.mode_btn)

        self.grid_btn = Button(text=f"Grid: {self.grid_size}x{self.grid_size}")
        self.grid_btn.bind(on_press=self.cycle_grid)
        self.adv_layout.add_widget(self.grid_btn)

        self.layout.add_widget(self.adv_layout)
        
        self.tracker = None
        self.decoder = None
        return self.layout

    def load_settings(self):
        self.color_mode = MODE_1BIT_BW
        self.grid_size = 64
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    self.color_mode = data.get("color_mode", MODE_1BIT_BW)
                    self.grid_size = data.get("grid_size", 64)
            except: pass

    def save_settings(self):
        with open(self.settings_file, "w") as f:
            json.dump({"color_mode": self.color_mode, "grid_size": self.grid_size}, f)

    def get_mode_text(self):
        if self.color_mode == MODE_1BIT_BW: return "1-Bit B&W (Ultra-Reliable)"
        if self.color_mode == MODE_2BIT_4COLOR: return "2-Bit 4-Color (2x Faster)"
        return "3-Bit 8-Color (3x Faster)"

    def cycle_mode(self, instance):
        self.color_mode = (self.color_mode + 1) % 3
        self.mode_btn.text = f"Mode: {self.get_mode_text()}"
        self.save_settings()

    def cycle_grid(self, instance):
        opts = [32, 48, 64, 128]
        idx = opts.index(self.grid_size) if self.grid_size in opts else 2
        self.grid_size = opts[(idx + 1) % len(opts)]
        self.grid_btn.text = f"Grid: {self.grid_size}x{self.grid_size}"
        self.save_settings()

    def toggle_advanced(self, instance):
        if self.adv_layout.height == 0:
            self.adv_layout.height = 100
            self.adv_layout.opacity = 1
            self.adv_btn.text = "⚙️ Advanced Parameters (Pro) ▲"
        else:
            self.adv_layout.height = 0
            self.adv_layout.opacity = 0
            self.adv_btn.text = "⚙️ Advanced Parameters (Pro) ▼"

    def on_start(self):
        if platform == 'android':
            request_permissions([
                Permission.CAMERA,
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE
            ])

    def start_sender(self, instance):
        self.layout.clear_widgets()
        self.layout.add_widget(Label(text="Select file to send...", size_hint_y=0.1))
        # Use plyer to select file, for now just load demo
        self.start_beaming_demo()

    def start_beaming_demo(self):
        self.layout.clear_widgets()
        self.img = Image()
        self.layout.add_widget(self.img)
        btn = Button(text="Stop Beaming", size_hint_y=0.1, background_color=(1, 0, 0, 1))
        btn.bind(on_press=self.stop_sender)
        self.layout.add_widget(btn)

        data = b"ChromaBeam-HighSpeedOpticalPayload\n" + os.urandom(16 * 1024)
        self.file_id = np.random.randint(1000, 60000)
        self.layout_engine = ColorMatrixLayout(grid_size=self.grid_size, color_mode=self.color_mode)
        
        if self.color_mode == MODE_1BIT_BW and self.grid_size == 64:
            block_size = 200
        else:
            block_size = max(24, self.layout_engine.max_payload_bytes - 16)
            
        full_stream = pack_file_metadata("demo.bin", len(data)) + data
        self.encoder = LTEncoder(full_stream, block_size=block_size)
        self.droplet_seed = 0
        
        self.sender_event = Clock.schedule_interval(self.sender_tick, 1.0 / 15.0) # 15 FPS

    def sender_tick(self, dt):
        seed = self.droplet_seed
        self.droplet_seed += 1
        
        _, _, block_payload = self.encoder.generate_droplet(seed)
        packet = pack_packet(self.file_id, self.encoder.K, self.encoder.block_size, seed, block_payload)
        
        if self.color_mode == MODE_1BIT_BW and self.grid_size == 64:
            rgb_grid = packet_to_standard_qr_rgb(packet)
        else:
            grid = self.layout_engine.bytes_to_color_grid(packet)
            rgb_grid = upscale_grid_for_display(grid, target_size=800)
            
        # Convert to Kivy Texture
        h, w, c = rgb_grid.shape
        texture = Texture.create(size=(w, h), colorfmt='rgb')
        texture.blit_buffer(rgb_grid.tobytes(), colorfmt='rgb', bufferfmt='ubyte')
        texture.flip_vertical()
        self.img.texture = texture

    def stop_sender(self, instance):
        if hasattr(self, 'sender_event'):
            self.sender_event.cancel()
        self.layout.clear_widgets()
        self.build() # Restart UI
        # We need to manually re-add widgets since build() just returns the layout
        # Actually it's better to reload app
        self.layout.clear_widgets()
        self.layout.add_widget(self.title_lbl)
        self.layout.add_widget(self.send_btn)
        self.layout.add_widget(self.recv_btn)
        self.layout.add_widget(self.adv_btn)
        self.layout.add_widget(self.adv_layout)
        
    def start_receiver(self, instance):
        self.layout.clear_widgets()
        
        from kivy.uix.camera import Camera
        self.camera = Camera(play=True, resolution=(640, 480))
        self.layout.add_widget(self.camera)
        
        self.rx_lbl = Label(text="Status: Scanning...", size_hint_y=0.1)
        self.layout.add_widget(self.rx_lbl)
        
        btn = Button(text="Stop Receiving", size_hint_y=0.1, background_color=(1, 0, 0, 1))
        btn.bind(on_press=self.stop_receiver)
        self.layout.add_widget(btn)

        self.tracker = OpticalTracker()
        self.classifier = AdaptiveColorClassifier()
        self.decoder = None
        self.current_file_id = None
        self.rx_event = Clock.schedule_interval(self.receiver_tick, 1.0 / 30.0)

    def receiver_tick(self, dt):
        if not self.camera.texture: return
        # Extract frame
        pixels = self.camera.texture.pixels
        w, h = self.camera.texture.size
        frame = np.frombuffer(pixels, np.uint8).reshape((h, w, 4))
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        frame_bgr = cv2.flip(frame_bgr, 0) # Flip vertically for OpenCV
        
        quad = self.tracker.find_matrix_quad(frame_bgr)
        if quad is not None:
            self.rx_lbl.text = "Status: Locked 🎯"
            
            # Simple check for now
            warped = self.tracker.compute_homography(quad, grid_size=64)
            # The rest of the decoding pipeline goes here...
            
    def stop_receiver(self, instance):
        if hasattr(self, 'rx_event'):
            self.rx_event.cancel()
        self.camera.play = False
        self.layout.clear_widgets()
        self.layout.add_widget(self.title_lbl)
        self.layout.add_widget(self.send_btn)
        self.layout.add_widget(self.recv_btn)
        self.layout.add_widget(self.adv_btn)
        self.layout.add_widget(self.adv_layout)


if __name__ == '__main__':
    NativeChromaBeamApp().run()
