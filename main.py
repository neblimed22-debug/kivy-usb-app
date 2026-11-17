import queue
import threading
import time
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkBox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

import serial
from serial.tools import list_ports

BAUD = 115200


class LEDWidget(BoxLayout):
    """Widget personnalisé pour afficher l'indicateur LED sous forme de cercle coloré."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (50, 50)
        with self.canvas:
            self.color_instruction = Color(0.5, 0.5, 0.5, 1)  gris par défaut
            self.circle = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.circle.pos = self.pos
        self.circle.size = self.size

    def set_color(self, allumee):
        if allumee:
            self.color_instruction.rgba = (0.94, 0.77, 0.12, 1)  # Jaune (#f1c40f)
        else:
            self.color_instruction.rgba = (0.5, 0.55, 0.55, 1)  # Gris (#7f8c8d)


class TempHumiditeApp(App):

    def build(self):
        self.title = "Température / Humidité - Commande LED"
        self.ser = None
        self.thread = None
        self.stop_event = threading.Event()
        self.rx_queue = queue.Queue()

        root = BoxLayout(orientation="vertical", padding=15, spacing=12)

        # --- Section Connexion ---
        conn_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=50, spacing=8
        )
        self.spinner_ports = Spinner(
            text="Sélectionner un port",
            values=[],
            size_hint_x=0.5,
            background_color=(0.2, 0.6, 0.8, 1),
        )
        btn_refresh = Button(
            text="Actualiser",
            size_hint_x=0.25,
            on_press=self.refresh_ports,
        )
        self.btn_connect = Button(
            text="Se connecter",
            size_hint_x=0.25,
            background_color=(0.1, 0.7, 0.3, 1),
            on_press=self.toggle_connection,
        )
        conn_layout.add_widget(self.spinner_ports)
        conn_layout.add_widget(btn_refresh)
        conn_layout.add_widget(btn_connect)
        root.add_widget(conn_layout)

        # --- Section Mesures (Température & Humidité) ---
        mes_layout = GridLayout(cols=2, spacing=10, size_hint_y=None, height=130)

        # Boîte Température
        temp_box = BoxLayout(orientation="vertical", padding=5)
        temp_box.add_widget(
            Label(text="Température", font_size=16, color=(0.8, 0.8, 0.8, 1))
        )
        self.lbl_temp = Label(
            text="-- °C", font_size=32, bold=True, color=(0.75, 0.22, 0.17, 1)
        )
        temp_box.add_widget(self.lbl_temp)
        mes_layout.add_widget(temp_box)

        # Boîte Humidité
        hum_box = BoxLayout(orientation="vertical", padding=5)
        hum_box.add_widget(
            Label(text="Humidité", font_size=16, color=(0.8, 0.8, 0.8, 1))
        )
        self.lbl_hum = Label(
            text="-- %", font_size=32, bold=True, color=(0.14, 0.44, 0.64, 1)
        )
        hum_box.add_widget(self.lbl_hum)
        mes_layout.add_widget(mes_layout)
        root.add_widget(mes_layout)

        # --- Section Contrôle LED ---
        led_layout = GridLayout(
            cols=2, spacing=10, size_hint_y=None, height=110
        )

        left_led_box = BoxLayout(
            orientation="vertical",
            size_hint_x=None,
            width=80,
            padding=(15, 10, 0, 0),
        )
        self.led_widget = LEDWidget()
        left_led_box.add_widget(self.led_widget)
        led_layout.add_widget(left_led_box)

        right_led_box = BoxLayout(
            orientation="vertical", spacing=8, padding=(0, 5, 0, 0)
        )
        btn_ctrl_layout = BoxLayout(
            orientation="horizontal", spacing=10, size_hint_y=None, height=45
        )
        self.btn_on = Button(
            text="LED ON",
            disabled=True,
            background_color=(0.9, 0.5, 0.1, 1),
            on_press=lambda x: self.send("LED_ON"),
        )
        self.btn_off = Button(
            text="LED OFF",
            disabled=True,
            background_color=(0.3, 0.3, 0.3, 1),
            on_press=lambda x: self.send("LED_OFF"),
        )
        btn_ctrl_layout.add_widget(self.btn_on)
        btn_ctrl_layout.add_widget(self.btn_off)
        right_led_box.add_widget(btn_ctrl_layout)

        auto_box = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=35, spacing=5
        )
        self.chk_auto = CheckBox(
            active=True, disabled=True, size_hint_x=None, width=40
        )
        self.chk_auto.bind(active=self.on_auto_toggle)
        auto_box.add_widget(self.chk_auto)
        auto_box.add_widget(
            Label(
                text="Mode auto (T ≥ 25°C et H ≥ 55%)",
                font_size=13,
                halign="left",
            )
        )
        right_led_box.add_widget(auto_box)
        led_layout.add_widget(right_led_box)
        root.add_widget(led_layout)

        # --- Section Journal / Logs ---
        log_layout = BoxLayout(orientation="vertical", size_hint_y=1)
        log_layout.add_widget(
            Label(
                text="Journal",
                size_hint_y=None,
                height=25,
                halign="left",
                color=(0.7, 0.7, 0.7, 1),
            )
        )
        self.txt_log = TextInput(
            readonly=True,
            font_name="Consolas",
            font_size=12,
            background_color=(0.1, 0.1, 0.1, 1),
            foreground_color=(1, 1, 1, 1),
        )
        log_layout.add_widget(self.txt_log)
        root.add_widget(log_layout)

        # --- Barre d'état ---
        self.lbl_status = Label(
            text="Déconnecté",
            size_hint_y=None,
            height=25,
            halign="left",
            color=(0.8, 0.8, 0.8, 1),
        )
        root.add_widget(self.lbl_status)

        # Initialisation
        self.refresh_ports()
        Clock.schedule_interval(self.process_queue, 0.1)

        return root

    # --- Gestion des ports et connexions ---
    def refresh_ports(self, *args):
        ports = [p.device for p in list_ports.comports()]
        self.spinner_ports.values = ports
        if ports:
            self.spinner_ports.text = ports[0]
        else:
            self.spinner_ports.text = "Aucun port détecté"

    def toggle_connection(self, *args):
        if self.ser:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.spinner_ports.text
        if not port or port.startswith("Aucun") or port.startswith("Sélectionner"):
            self.log("Erreur : Aucun port valide sélectionné.")
            return

        try:
            self.ser = serial.Serial(port, BAUD, timeout=1)
        except Exception as exc:
            self.ser = None
            self.log(f"Erreur d'ouverture de {port} : {exc}")
            return

        time.sleep(2)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        self.stop_event.clear()
        self.thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.thread.start()

        self.btn_connect.text = "Se déconnecter"
        self.btn_connect.background_color = (0.8, 0.2, 0.2, 1)
        self.spinner_ports.disabled = True
        for w in (self.btn_on, self.btn_off, self.chk_auto):
            w.disabled = False

        self.lbl_status.text = f"Connecté à {port} ({BAUD} bauds)"
        self.log(f"Connecté à {port}")

    def disconnect(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.thread = None

        self.btn_connect.text = "Se connecter"
        self.btn_connect.background_color = (0.1, 0.7, 0.3, 1)
        self.spinner_ports.disabled = False
        for w in (self.btn_on, self.btn_off, self.chk_auto):
            w.disabled = True

        self.lbl_temp.text = "-- °C"
        self.lbl_hum.text = "-- %"
        self.led_widget.set_color(False)
        self.lbl_status.text = "Déconnecté"
        self.log("Déconnecté")

    # --- Boucle de lecture série (Thread séparé) ---
    def reader_loop(self):
        while not self.stop_event.is_set():
            try:
                raw = self.ser.readline()
            except Exception:
                self.rx_queue.put("__LOST__")
                return
            if raw:
                try:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if line:
                        self.rx_queue.put(line)
                except Exception:
                    pass

    def send(self, commande):
        if not self.ser:
            return
        try:
            self.ser.write((commande + "\n").encode("ascii"))
            self.log(f"> {commande}")
        except Exception as exc:
            self.log(f"Erreur d'envoi : {exc}")

    # --- Traitement des messages dans le fil principal (Kivy Clock) ---
    def process_queue(self, dt):
        try:
            while True:
                line = self.rx_queue.get_nowait()
                self.handle_line(line)
        except queue.Empty:
            pass

    def handle_line(self, line):
        if line == "__LOST__":
            self.log("Connexion série perdue.")
            self.disconnect()
            return

        if line.startswith("DATA,"):
            parts = line.split(",")
            try:
                temp = float(parts[1])
                hum = float(parts[2])
            except (IndexError, ValueError):
                self.log(f"Trame invalide : {line}")
                return
            self.lbl_temp.text = f"{temp:.1f} °C"
            self.lbl_hum.text = f"{hum:.1f} %"
            if len(parts) >= 5:
                self.led_widget.set_color(parts[3] == "1")
                # On désactive temporairement l'écouteur du CheckBox pour éviter les boucles
                self.chk_auto.unbind(active=self.on_auto_toggle)
                self.chk_auto.active = parts[4] == "A"
                self.chk_auto.bind(active=self.on_auto_toggle)
        elif line == "ERROR":
            self.lbl_temp.text = "Erreur"
            self.lbl_hum.text = "Erreur"
            self.log("Erreur de lecture du capteur (vérifier le câblage)")
        elif line == "LED_ON_OK":
            self.led_widget.set_color(True)
            self.log("LED allumée (mode manuel)")
        elif line == "LED_OFF_OK":
            self.led_widget.set_color(False)
            self.log("LED éteinte (mode manuel)")
        elif line == "MODE_AUTO_OK":
            self.log("Mode automatique activé")
        elif line == "MODE_MANUAL_OK":
            self.log("Mode manuel activé")
        else:
            self.log(line)

    def on_auto_toggle(self, checkbox, value):
        self.send("MODE_AUTO" if value else "MODE_MANUAL")

    def log(self, message):
        horodatage = datetime.now().strftime("%H:%M:%S")
        self.txt_log.text += f"{horodatage}  {message}\n"

    def on_stop(self):
        self.disconnect()


if __name__ == "__main__":
    TempHumiditeApp().run()