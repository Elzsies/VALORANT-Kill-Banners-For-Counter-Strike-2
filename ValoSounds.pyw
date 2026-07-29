import ctypes
import sys
import os
import json
import socket
import platform
import keyboard
import tkinter as tk
from tkinter import ttk
import pygame
import threading
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

def run_as_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
    except:
        pass
    try:
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
        sys.exit(0)
    except Exception as e:
        print(f"Admin rights failed: {e}")
    return False

run_as_admin()

SOUNDS_BASE = "sounds"
CONFIG_FILE = "tracker_config.json"

def init_audio():
    if platform.system() == "Windows":
        driver_candidates = ["wasapi", "directsound", None]
    else:
        driver_candidates = [None]
   
    last_err = None
    for driver in driver_candidates:
        try:
            if driver:
                os.environ["SDL_AUDIODRIVER"] = driver
            else:
                os.environ.pop("SDL_AUDIODRIVER", None)
            pygame.mixer.quit()
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=16)
            pygame.mixer.init()
            print(f"Audio driver: {driver or 'default'}, buffer=16")
            return
        except Exception as e:
            last_err = e
            continue
   
    os.environ.pop("SDL_AUDIODRIVER", None)
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=64)
    pygame.mixer.init()
    print(f"Audio driver: default (fallback after error: {last_err})")

init_audio()

NUM_KILL_CHANNELS = 16
pygame.mixer.set_num_channels(NUM_KILL_CHANNELS)
current_volume = 0.5
ACE_VOLUME = 1.3
sound_cache = {}

weapon_to_preset = {
    "weapon_ak47": "ak",
    "weapon_deagle": "deagle",
    "weapon_m4a1_silencer": "m4",
    "weapon_m4a4": "m4",
    "weapon_knife": "default",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Config load error: {e}")
    return {"volume": 100, "skins": {}}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except:
        pass

def load_skin_sounds(skin_name):
    if not skin_name or skin_name == "None":
        return []
    path = os.path.join(SOUNDS_BASE, skin_name)
    if not os.path.isdir(path):
        return []
    files = [f for f in os.listdir(path) if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac'))]
    files.sort(key=lambda f: int(os.path.splitext(f)[0]) if os.path.splitext(f)[0].isdigit() else 9999)
    sound_list = []
    for f in files:
        full_path = os.path.abspath(os.path.join(path, f))
        if full_path not in sound_cache:
            try:
                sound_cache[full_path] = pygame.mixer.Sound(full_path)
            except Exception as e:
                print(f"Failed to load {f}: {e}")
                continue
        sound_list.append(full_path)
    return sound_list

def play_kill_sound(path, is_ace=False):
    sound = sound_cache.get(path)
    if not sound:
        return
    vol = ACE_VOLUME if is_ace else current_volume
    sound.set_volume(vol)
    channel = pygame.mixer.find_channel(True)
    channel.play(sound)

def play_random_ace():
    ace_sounds = tracker.preset_sounds.get("ace", [])
    if ace_sounds:
        path = random.choice(ace_sounds)
        play_kill_sound(path, is_ace=True)

class KillTracker:
    def __init__(self):
        self.last_kills = 0
        self.user = "lea"
        self.preset_sounds = {}
        self.ui_callback = None
        self.server = None
        self.ace_triggered = False

    def reset(self, *args):
        self.last_kills = 0
        self.ace_triggered = False
        if self.ui_callback:
            self.ui_callback()

tracker = KillTracker()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
           
            self.send_response(0)
            self.send_header('Content-Length', '0')
            self.end_headers()
            if not body:
                return
            data = json.loads(body)
            player = data.get('player', {})
            if player.get('name', '').lower() != tracker.user.lower():
                return
            round_kills = player.get('state', {}).get('round_kills', 0)

            round_phase = ""
            try:
                round_info = data.get("round", {}) or data.get("info", {}).get("round", {})
                round_phase = round_info.get("phase", "").lower()
            except:
                pass

            if round_kills > tracker.last_kills:
                kill_weapon = None
                try:
                    info = data.get("info", {}).get("match_info", {})
                    kf_str = info.get("kill_feed")
                    if kf_str:
                        kf = json.loads(kf_str)
                        if kf.get("attacker", "").lower() == tracker.user.lower():
                            kill_weapon = kf.get("weapon") or kf.get("ult")
                except:
                    pass
                if not kill_weapon:
                    for w in player.get("weapons", {}).values():
                        if w.get("state") == "active":
                            kill_weapon = w.get("name")
                            break
                preset = "default" if kill_weapon and any(x in str(kill_weapon).lower() for x in ["knife", "grenade", "flash", "smoke"]) else weapon_to_preset.get(kill_weapon, "others")
                sounds = tracker.preset_sounds.get(preset, [])
                if sounds:
                    idx = min(round_kills - 1, len(sounds) - 1)
                    play_kill_sound(sounds[idx])
                tracker.last_kills = round_kills

            if round_phase in ["over", "intermission", "gameover"] and not tracker.ace_triggered:
                if tracker.last_kills >= 5:
                    match_info = data.get("info", {}).get("match_info", {}) or data.get("match", {})
                    queue = str(match_info.get("queue") or match_info.get("mode") or "").lower()
                    is_deathmatch = any(x in queue for x in ["deathmatch", "dm"])
                    if not is_deathmatch:
                        play_random_ace()
                        tracker.ace_triggered = True
            if tracker.ui_callback:
                tracker.ui_callback()
        except Exception:
            pass

class KillTrackerUI(tk.Tk):
    def __init__(self, available_skins):
        super().__init__()
        self.title("Valo Sounds")
        self.geometry("560x780")
        self.resizable(False, False)
        self.available_skins = available_skins
        self.config = load_config()
        self.combos = {}
        self.started = False
        self.build_ui()
        self.after(0, self.start_server)

    def build_ui(self):
        skin_frame = ttk.LabelFrame(self, text="Skin Selection", padding=12)
        skin_frame.pack(fill="both", padx=12, pady=8)
        row = 0
        tk.Label(skin_frame, text="Default (Knife + Grenades):", font=("Arial", 9)).grid(row=row, column=0, padx=8, pady=8, sticky="w")
        tk.Label(skin_frame, text="Base", font=("Arial", 9, "bold"), fg="#00aa00").grid(row=row, column=1, padx=8, pady=8, sticky="w")
        row += 1
        presets = ["ak", "deagle", "m4", "others"]
        displays = ["AK-47", "Deagle", "M4", "Others"]
        for disp, key in zip(displays, presets):
            tk.Label(skin_frame, text=f"{disp}:", font=("Arial", 9)).grid(row=row, column=0, padx=8, pady=6, sticky="w")
            combo = ttk.Combobox(skin_frame, values=["None"] + self.available_skins, state="readonly", width=38)
            saved = self.config.get("skins", {}).get(key, "None")
            combo.set(saved if saved in ["None"] + self.available_skins else "None")
            combo.grid(row=row, column=1, padx=8, pady=6)
            self.combos[key] = combo
            row += 1
        vol_frame = ttk.LabelFrame(self, text="Volume", padding=12)
        vol_frame.pack(fill="both", padx=12, pady=8)
        ttk.Label(vol_frame, text="Mute").pack(side="left", padx=5)
        self.volume_slider = ttk.Scale(vol_frame, from_=0, to=100, orient="horizontal", command=self.set_volume)
        self.volume_slider.set(self.config.get("volume", 100))
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(vol_frame, text="Max").pack(side="left", padx=5)
        ctrl_frame = ttk.LabelFrame(self, text="Controls", padding=12)
        ctrl_frame.pack(fill="both", padx=12, pady=8)
        btn_frame = tk.Frame(ctrl_frame)
        btn_frame.pack(fill="x", pady=8)
        self.start_btn = tk.Button(btn_frame, text="START SERVER", command=self.start_server,
                                   bg="#00aa00", fg="white", font=("Arial", 10, "bold"), height=2)
        self.start_btn.pack(side="left", padx=5, fill="x", expand=True)
        self.stop_btn = tk.Button(btn_frame, text="STOP SERVER", command=self.stop_server,
                                  bg="#aa0000", fg="white", font=("Arial", 10, "bold"), height=2, state="disabled")
        self.stop_btn.pack(side="left", padx=5, fill="x", expand=True)
        tk.Button(ctrl_frame, text="Test Sound Now", command=self.test_sound, bg="#4444ff", fg="white", font=("Arial", 10)).pack(pady=8)
        tk.Button(ctrl_frame, text="Reset Kills", command=tracker.reset).pack(pady=4)
        self.status_label = tk.Label(self, text="Server: Stopped", font=("Arial", 11), fg="red")
        self.status_label.pack(pady=6)
        self.kills_label = tk.Label(self, text="0", font=("Arial", 80, "bold"), fg="#00ff00")
        self.kills_label.pack(pady=20)

    def set_volume(self, val):
        global current_volume
        current_volume = float(val) / 100.0
        self.config["volume"] = int(float(val))
        save_config(self.config)

    def test_sound(self):
        sounds = tracker.preset_sounds.get("default", [])
        if sounds:
            try:
                play_kill_sound(sounds[0])
            except:
                pass

    def start_server(self):
        if self.started:
            return
        try:
            tracker.preset_sounds["default"] = load_skin_sounds("Base")
            for key, combo in self.combos.items():
                skin = combo.get()
                tracker.preset_sounds[key] = load_skin_sounds(skin)
                self.config.setdefault("skins", {})[key] = skin
            tracker.preset_sounds["ace"] = load_skin_sounds("Ace")
            tracker.ui_callback = self.update_kills
            for combo in self.combos.values():
                combo.config(state="disabled")
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self.status_label.config(text="Server: RUNNING (Max Speed)", fg="green")
            threading.Thread(target=self._run_server, daemon=True).start()
            self.started = True
        except Exception as e:
            print(f"Start server error: {e}")

    def _run_server(self):
        try:
            server = ThreadedHTTPServer(('127.0.0.1', 3000), Handler)
            tracker.server = server
            print("Server started on port 3000")
            server.serve_forever()
        except Exception as e:
            print(f"Server run error: {e}")

    def stop_server(self):
        if hasattr(tracker, 'server') and tracker.server:
            try:
                tracker.server.shutdown()
            except:
                pass
        self.started = False
        for combo in self.combos.values():
            combo.config(state="readonly")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text="Server: Stopped", fg="red")

    def update_kills(self):
        self.kills_label.config(text=str(tracker.last_kills))

    def on_closing(self):
        save_config(self.config)
        self.stop_server()
        self.destroy()

if __name__ == "__main__":
    try:
        os.makedirs(os.path.join(SOUNDS_BASE, "Base"), exist_ok=True)
        available_skins = [d for d in os.listdir(SOUNDS_BASE)
                          if os.path.isdir(os.path.join(SOUNDS_BASE, d)) and not d.startswith('.')]
       
        app = KillTrackerUI(available_skins)
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        try:
            keyboard.on_press_key("z", tracker.reset)
        except:
            pass
        print("Starting UI...")
        app.mainloop()
    except Exception as e:
        print(f"Critical error: {e}")
        input("Press Enter to exit...")