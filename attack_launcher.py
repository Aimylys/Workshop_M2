#!/usr/bin/env python3
"""
IDS Attack Launcher — GUI pour piloter des attaques labellisées.

⚠️  Usage strictement réservé à un lab isolé / cibles autorisées.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

# ──────────────────────────── Configuration ────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
LABEL_PATH = PROJECT_ROOT / "collector" / "label.txt"
CONFIG_PATH = SCRIPT_DIR / "config.json"

BG          = "#0d1117"
CARD        = "#161b22"
CARD_HOVER  = "#1f2937"
CYAN        = "#00e5ff"
RED         = "#ff3b3b"
GREEN       = "#22c55e"
YELLOW      = "#facc15"
FG          = "#e6edf3"
MUTED       = "#7d8590"
FIELD_BG    = "#010409"
BORDER      = "#30363d"

ATTACKS = {
    "brute_force": {
        "title": "Brute Force", "icon": "🔨",
        "desc": "POST /login répétés",
        "defaults": {"host": "10.238.100.138", "port": "8000",
                     "endpoint": "/login", "duration": "90",
                     "threads": "30", "username": "admin", "password": "wrong"},
    },
    "port_scan": {
        "title": "Port Scan", "icon": "🔍",
        "desc": "nmap -sS sur plage",
        "defaults": {"host": "localhost", "port": "1-10000"},
    },
    "sql_injection": {
        "title": "SQL Injection", "icon": "💉",
        "desc": "sqlmap en boucle",
        "defaults": {"host": "10.50.75.138", "port": "8000",
                     "endpoint": "/accounts/1", "duration": "90"},
    },
    "ddos": {
        "title": "DDoS", "icon": "🌊",
        "desc": "hey.exe -c threads",
        "defaults": {"host": "10.50.75.138", "port": "8000",
                     "endpoint": "/accounts/1", "duration": "90", "threads": "200"},
    },
}

FIELD_LABELS = {
    "host": "Host / IP", "port": "Port", "endpoint": "Endpoint",
    "duration": "Durée (s)", "threads": "Threads",
    "username": "Username", "password": "Password",
}
FIELD_ORDER = ["host", "port", "endpoint", "duration",
               "threads", "username", "password"]

FIELD_TOOLTIPS = {
    "host": "Adresse IP ou nom d'hôte de la cible",
    "port": "Port unique (1-65535) ou plage ex: 1-10000 (port_scan)",
    "endpoint": "Chemin de l'URL (doit commencer par /)",
    "duration": "Durée de l'attaque en secondes",
    "threads": "Nombre de requêtes / workers parallèles",
    "username": "Nom d'utilisateur (brute force)",
    "password": "Mot de passe à tester (brute force)",
}


# ──────────────────────────── Utilitaires ────────────────────────────
def write_label(value: str) -> None:
    """Écrit label.txt en ASCII sans retour à la ligne (équivalent Set-Content -NoNewline)."""
    LABEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABEL_PATH.write_bytes(value.encode("ascii", errors="replace"))


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, background=CARD, foreground=FG,
                 relief="solid", borderwidth=1, font=("Consolas", 10),
                 padx=8, pady=4).pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ──────────────────────────── Application ────────────────────────────
class AttackLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("IDS Attack Launcher")
        self.geometry("1080x760")
        self.minsize(900, 650)
        self.configure(fg_color=BG)

        self.current_attack: str = "brute_force"
        self.card_widgets: dict[str, ctk.CTkButton] = {}
        self.field_widgets: dict[str, dict] = {}
        self.saved_params: dict = self._load_config()

        self.proc: subprocess.Popen | None = None
        self.attack_in_progress: bool = False
        self.start_time: float | None = None
        self._pulse: bool = False

        self._ensure_label_file()
        self._build_ui()
        self._select_attack("brute_force")
        self._tick_clock()
        self.log("info", f"Répertoire projet : {PROJECT_ROOT}")
        self.log("info", f"Label : {LABEL_PATH}")

    # ── Persistance ──
    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_config(self) -> None:
        try:
            CONFIG_PATH.write_text(json.dumps(self.saved_params, indent=2),
                                   encoding="utf-8")
        except Exception as e:
            self.log("error", f"config.json : {e}")

    def _ensure_label_file(self) -> None:
        try:
            if not LABEL_PATH.exists():
                write_label("normal")
        except Exception as e:
            messagebox.showerror("label.txt", f"Impossible d'initialiser : {e}")

    # ── Construction de l'UI ──
    def _build_ui(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(header, text="🛡️  IDS Attack Launcher",
                     font=("Consolas", 20, "bold"),
                     text_color=CYAN).pack(side="left")
        self.label_indicator = ctk.CTkLabel(header, text="● normal",
                                            font=("Consolas", 13, "bold"),
                                            text_color=GREEN)
        self.label_indicator.pack(side="right", padx=(12, 0))
        self.clock_label = ctk.CTkLabel(header, text="00:00",
                                        font=("Consolas", 14), text_color=FG)
        self.clock_label.pack(side="right")

        # Cartes d'attaque
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", padx=16, pady=6)
        for i, (key, meta) in enumerate(ATTACKS.items()):
            cards.grid_columnconfigure(i, weight=1)
            btn = ctk.CTkButton(
                cards, text=f"{meta['icon']}  {meta['title']}\n{meta['desc']}",
                font=("Consolas", 12), height=68,
                fg_color=CARD, hover_color=CARD_HOVER,
                border_width=2, border_color=CARD, corner_radius=10,
                command=lambda k=key: self._select_attack(k),
            )
            btn.grid(row=0, column=i, padx=4, sticky="ew")
            self.card_widgets[key] = btn

        # Paramètres
        params_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        params_frame.pack(fill="x", padx=16, pady=6)
        params_inner = ctk.CTkFrame(params_frame, fg_color="transparent")
        params_inner.pack(fill="x", padx=12, pady=12)
        for i in range(4):
            params_inner.grid_columnconfigure(i, weight=1)

        for idx, fname in enumerate(FIELD_ORDER):
            row, col = divmod(idx, 4)
            cont = ctk.CTkFrame(params_inner, fg_color="transparent")
            cont.grid(row=row, column=col, padx=6, pady=4, sticky="ew")
            lbl = ctk.CTkLabel(cont, text=FIELD_LABELS[fname],
                               font=("Consolas", 11), text_color=MUTED,
                               anchor="w")
            lbl.pack(fill="x")
            entry = ctk.CTkEntry(cont, font=("Consolas", 12), height=30,
                                 fg_color=FIELD_BG, border_color=BORDER)
            entry.pack(fill="x")
            Tooltip(entry, FIELD_TOOLTIPS[fname])
            self.field_widgets[fname] = {"container": cont, "label": lbl,
                                         "entry": entry}

        # Actions
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=6)
        self.launch_btn = ctk.CTkButton(
            actions, text="▶  LANCER L'ATTAQUE",
            font=("Consolas", 15, "bold"), height=44,
            fg_color=CYAN, hover_color="#00b8d4", text_color="#0d1117",
            command=self._on_launch,
        )
        self.launch_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.stop_btn = ctk.CTkButton(
            actions, text="■  STOP",
            font=("Consolas", 15, "bold"), height=44,
            fg_color=RED, hover_color="#cc2929", text_color="white",
            state="disabled", command=self._on_stop,
        )
        self.stop_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Quitter", width=100, height=44,
                      font=("Consolas", 13), fg_color="#21262d",
                      hover_color="#30363d",
                      command=self._on_quit).pack(side="right")

        # Console
        cons_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        cons_frame.pack(fill="both", expand=True, padx=16, pady=(6, 14))
        top = ctk.CTkFrame(cons_frame, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(top, text="Console", font=("Consolas", 12, "bold"),
                     text_color=CYAN).pack(side="left")
        ctk.CTkButton(top, text="Effacer", width=80, height=24,
                      font=("Consolas", 11), fg_color="#21262d",
                      hover_color="#30363d",
                      command=self._clear_console).pack(side="right")
        self.console = ctk.CTkTextbox(cons_frame, font=("Consolas", 11),
                                      fg_color=FIELD_BG, text_color=FG,
                                      wrap="word")
        self.console.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self.console.configure(state="disabled")
        try:
            txt = self.console._textbox
            txt.tag_config("info", foreground=FG)
            txt.tag_config("attack", foreground=CYAN)
            txt.tag_config("label", foreground=YELLOW)
            txt.tag_config("error", foreground=RED)
            txt.tag_config("done", foreground=GREEN)
        except Exception:
            pass

    # ── Console log ──
    def log(self, tag: str, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{tag.upper():<6}] {msg}\n"

        def _do():
            try:
                txt = self.console._textbox
                txt.configure(state="normal")
                txt.insert("end", line, tag)
                txt.see("end")
                txt.configure(state="disabled")
            except Exception:
                pass

        self.after(0, _do)

    def _clear_console(self) -> None:
        try:
            txt = self.console._textbox
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.configure(state="disabled")
        except Exception:
            pass

    # ── Sélection d'attaque ──
    def _stash_current_params(self) -> None:
        if not self.current_attack:
            return
        params = {}
        for fname in ATTACKS[self.current_attack]["defaults"]:
            val = self.field_widgets[fname]["entry"].get().strip()
            if val:
                params[fname] = val
        if params:
            self.saved_params[self.current_attack] = params

    def _select_attack(self, key: str) -> None:
        if self.attack_in_progress:
            return
        self._stash_current_params()
        self.current_attack = key

        for k, btn in self.card_widgets.items():
            btn.configure(border_color=CYAN if k == key else CARD,
                          fg_color=CARD_HOVER if k == key else CARD)

        defaults = ATTACKS[key]["defaults"]
        saved = self.saved_params.get(key, {})
        for fname, w in self.field_widgets.items():
            if fname in defaults:
                w["container"].grid()
                w["label"].configure(text_color=MUTED)
                w["entry"].configure(state="normal", border_color=BORDER)
                w["entry"].delete(0, "end")
                w["entry"].insert(0, saved.get(fname, defaults[fname]))
            else:
                w["container"].grid_remove()
                w["entry"].delete(0, "end")

    def _collect_params(self) -> dict:
        return {f: self.field_widgets[f]["entry"].get().strip()
                for f in ATTACKS[self.current_attack]["defaults"]}

    # ── Validation ──
    def _validate(self, p: dict) -> str | None:
        key = self.current_attack
        if not p.get("host"):
            return "Host/IP vide."
        port = p.get("port", "")
        if key == "port_scan":
            m = re.fullmatch(r"(\d+)(?:-(\d+))?", port)
            if not m:
                return "Port/plage invalide (ex: 80, 1-10000)."
            if m.group(2):
                a, b = int(m.group(1)), int(m.group(2))
                if not (1 <= a <= b <= 65535):
                    return "Plage de ports invalide."
            elif not (1 <= int(m.group(1)) <= 65535):
                return "Port invalide (1-65535)."
        else:
            if not port.isdigit() or not (1 <= int(port) <= 65535):
                return "Port invalide (1-65535)."
        if "duration" in p:
            if not p["duration"].isdigit() or int(p["duration"]) <= 0:
                return "Durée invalide."
        if "threads" in p:
            if not p["threads"].isdigit() or int(p["threads"]) <= 0:
                return "Threads invalide."
        if "endpoint" in p and not p["endpoint"].startswith("/"):
            return "L'endpoint doit commencer par /."
        return None

    # ── Vérification des outils ──
    def _resolve_hey(self) -> str | None:
        if (PROJECT_ROOT / "hey.exe").exists():
            return ".\\hey.exe"
        if shutil.which("hey.exe"):
            return "hey.exe"
        return None

    # ── Construction de la commande PowerShell ──
    def _build_command(self, key: str, p: dict) -> tuple[str, int]:
        if key == "brute_force":
            dur = int(p["duration"])
            body = json.dumps({"username": p["username"],
                               "password": p["password"]}).replace("'", "''")
            script = (
                f"$fin = (Get-Date).AddSeconds({dur}); "
                f"while ((Get-Date) -lt $fin) {{ "
                f"1..{int(p['threads'])} | ForEach-Object {{ "
                f"try {{ Invoke-RestMethod -Uri \"http://{p['host']}:{p['port']}"
                f"{p['endpoint']}\" -Method Post -ContentType \"application/json\" "
                f"-Body '{body}' -TimeoutSec 2 }} catch {{}} }} }}"
            )
            return script, dur + 20
        if key == "port_scan":
            return f"nmap -sS -p {p['port']} {p['host']}", 300
        if key == "sql_injection":
            dur = int(p["duration"])
            script = (
                f"$fin = (Get-Date).AddSeconds({dur}); "
                f"while ((Get-Date) -lt $fin) {{ "
                f"sqlmap -u \"http://{p['host']}:{p['port']}{p['endpoint']}\" "
                f"--batch --level=1 --flush-session 2>$null }}"
            )
            return script, dur + 20
        if key == "ddos":
            dur = int(p["duration"])
            hey = self._resolve_hey() or ".\\hey.exe"
            script = (f"{hey} -z {dur}s -c {int(p['threads'])} "
                      f"http://{p['host']}:{p['port']}{p['endpoint']}")
            return script, dur + 20
        raise ValueError(key)

    # ── Lancement ──
    def _on_launch(self) -> None:
        if self.attack_in_progress:
            return
        params = self._collect_params()
        err = self._validate(params)
        if err:
            messagebox.showerror("Validation", err)
            return

        key = self.current_attack
        if key == "port_scan" and not shutil.which("nmap"):
            messagebox.showerror("Outil manquant", "nmap introuvable dans le PATH.")
            return
        if key == "sql_injection" and not shutil.which("sqlmap"):
            messagebox.showerror("Outil manquant", "sqlmap introuvable dans le PATH.")
            return
        if key == "ddos" and not self._resolve_hey():
            messagebox.showerror("Outil manquant",
                                 f"hey.exe introuvable dans {PROJECT_ROOT} ni dans le PATH.")
            return

        target = f"{params['host']}:{params.get('port','')}"
        extra = f" pendant {params['duration']}s" if "duration" in params else ""
        if not messagebox.askyesno(
                "Confirmation",
                f"Lancer {ATTACKS[key]['title']} sur {target}{extra} ?"):
            return

        self.saved_params[key] = params
        self.save_config()

        script, timeout = self._build_command(key, params)
        self.log("info", f"Commande : {script}")

        self.attack_in_progress = True
        self.start_time = time.time()
        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        threading.Thread(target=self._run_attack,
                         args=(key, script, timeout),
                         daemon=True).start()

    def _run_attack(self, key: str, script: str, timeout: int) -> None:
        try:
            write_label(key)
            self.log("label", f"label.txt = {key}")
            self.log("attack", f"Démarrage : {ATTACKS[key]['title']}")

            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-Command", script]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creationflags,
            )
            deadline = time.time() + timeout
            if self.proc.stdout:
                for line in self.proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log("info", line)
                    if time.time() > deadline:
                        self.log("error", "Timeout atteint, kill du process…")
                        self._kill_proc()
                        break
            try:
                rc = self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._kill_proc()
                rc = -1

            if rc == 0:
                self.log("done", "Attaque terminée (rc=0).")
            else:
                self.log("error", f"Process terminé avec code {rc}.")
        except Exception as e:
            self.log("error", f"Exception : {e}")
        finally:
            try:
                write_label("normal")
                self.log("label", "label.txt = normal")
            except Exception as e:
                self.log("error", f"Reset label impossible : {e}")
            self.after(0, self._attack_finished)

    def _kill_proc(self) -> None:
        if not self.proc:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    capture_output=True, timeout=5,
                )
            else:
                self.proc.kill()
        except Exception as e:
            self.log("error", f"Kill : {e}")

    def _attack_finished(self) -> None:
        self.attack_in_progress = False
        self.proc = None
        self.start_time = None
        self.launch_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.label_indicator.configure(text="● normal", text_color=GREEN)
        self.clock_label.configure(text="00:00")

    def _on_stop(self) -> None:
        if not self.attack_in_progress:
            return
        self.log("error", "STOP demandé — kill du process.")
        self._kill_proc()

    def _on_quit(self) -> None:
        if self.attack_in_progress:
            if not messagebox.askyesno("Quitter",
                                       "Une attaque est en cours. Stopper et quitter ?"):
                return
            self._kill_proc()
            try:
                write_label("normal")
            except Exception:
                pass
        self.save_config()
        self.destroy()

    # ── Horloge / pulse ──
    def _tick_clock(self) -> None:
        if self.attack_in_progress and self.start_time:
            elapsed = int(time.time() - self.start_time)
            m, s = divmod(elapsed, 60)
            self.clock_label.configure(text=f"{m:02d}:{s:02d}")
            self._pulse = not self._pulse
            self.label_indicator.configure(
                text=f"● {self.current_attack}",
                text_color=RED if self._pulse else "#7a1f1f",
            )
        self.after(500, self._tick_clock)


# ──────────────────────────── Main ────────────────────────────
def main() -> None:
    LABEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LABEL_PATH.exists():
        LABEL_PATH.write_bytes(b"normal")
    app = AttackLauncher()
    app.protocol("WM_DELETE_WINDOW", app._on_quit)
    app.mainloop()


if __name__ == "__main__":
    main()