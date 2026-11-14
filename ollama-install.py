#!/usr/bin/env python3
import getpass
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext


class OllamaInstallerApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Installateur Ollama (Support GPU AMD / RDNA2)")
        self.root.geometry("750x540")
        self.root.resizable(False, False)

        # Ajout de l'icône dans la barre de titre (en haut à gauche)
        try:
            self.icon_img = tk.PhotoImage(file="ollama-launcher.png")
            root.iconphoto(True, self.icon_img)
        except Exception:
            pass  # Ignore si le fichier image est absent

        self.current_user = getpass.getuser()

        # En-tête
        header_frame = tk.Frame(root, bg="#2c3e50", pady=12)
        header_frame.pack(fill=tk.X)

        tk.Label(
            header_frame,
            text="Installation d'Ollama & Configuration AMD GPU",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg="#2c3e50",
        ).pack()

        tk.Label(
            header_frame,
            text=f"Utilisateur détecté : {self.current_user} (Système Debian / Ubuntu)",
            font=("Helvetica", 10),
            fg="#bdc3c7",
            bg="#2c3e50",
        ).pack()

        # Zone des boutons d'action
        btn_frame = tk.Frame(root, pady=15)
        btn_frame.pack(fill=tk.X, padx=10)

        self.btn_install = tk.Button(
            btn_frame,
            text="1. Installer\nOllama",
            command=self.run_install_thread,
            bg="#27ae60",
            fg="white",
            font=("Helvetica", 11, "bold"),
            width=14,
            height=2,
            cursor="hand2",
        )
        self.btn_install.pack(side=tk.LEFT, padx=3, expand=True)

        self.btn_groups = tk.Button(
            btn_frame,
            text="2. Groupes\n(render, video)",
            command=self.run_groups_thread,
            bg="#2980b9",
            fg="white",
            font=("Helvetica", 11, "bold"),
            width=14,
            height=2,
            cursor="hand2",
        )
        self.btn_groups.pack(side=tk.LEFT, padx=3, expand=True)

        self.btn_rdna2 = tk.Button(
            btn_frame,
            text="3. Correctif\nRDNA2 (RX 6000)",
            command=self.run_rdna2_detection_thread,
            bg="#d35400",
            fg="white",
            font=("Helvetica", 11, "bold"),
            width=14,
            height=2,
            cursor="hand2",
        )
        self.btn_rdna2.pack(side=tk.LEFT, padx=3, expand=True)

        self.btn_status = tk.Button(
            btn_frame,
            text="4. Vérifier\nle Service",
            command=self.check_status,
            bg="#8e44ad",
            fg="white",
            font=("Helvetica", 11, "bold"),
            width=14,
            height=2,
            cursor="hand2",
        )
        self.btn_status.pack(side=tk.LEFT, padx=3, expand=True)

        # Zone de logs (Console)
        log_label = tk.Label(
            root,
            text="Journal d'exécution :",
            font=("Helvetica", 10, "bold"),
            anchor="w",
        )
        log_label.pack(fill=tk.X, padx=20)

        self.log_area = scrolledtext.ScrolledText(
            root,
            height=16,
            bg="#1e1e1e",
            fg="#00ff00",
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_area.pack(fill=tk.BOTH, padx=20, pady=(5, 15), expand=True)

        self.log("Prêt. Suivez les étapes de gauche à droite.\n")
        self.log("-" * 65 + "\n")

    def log(self, message):
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert(tk.END, message)
        self.log_area.see(tk.END)
        self.log_area.configure(state="disabled")

    def toggle_buttons(self, state):
        self.root.after(0, lambda: self.btn_install.config(state=state))
        self.root.after(0, lambda: self.btn_groups.config(state=state))
        self.root.after(0, lambda: self.btn_rdna2.config(state=state))
        self.root.after(0, lambda: self.btn_status.config(state=state))

    def run_install_thread(self):
        threading.Thread(target=self.install_ollama, daemon=True).start()

    def install_ollama(self):
      self.toggle_buttons("disabled")
      self.log("\n>>> Démarrage de l'installation d'Ollama...\n")
      try:
        # Utilisation de pkexec pour lancer l'installation avec les droits root graphiques
        cmd = "curl -fsSL https://ollama.com/install.sh | pkexec env bash"
        process = subprocess.Popen(
            ["bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
          self.log(line)
        process.wait()
        if process.returncode == 0:
          self.log("\n[SUCCÈS] Ollama a été installé correctement !\n")
        else:
          self.log(f"\n[ERREUR] Fin avec le code {process.returncode}.\n")
      except Exception as e:
        self.log(f"\n[EXCEPTION] {str(e)}\n")
      finally:
        self.toggle_buttons("normal")

    def run_groups_thread(self):
        threading.Thread(target=self.configure_groups, daemon=True).start()

    def configure_groups(self):
      self.toggle_buttons("disabled")
      self.log(
          f"\n>>> Ajout de '{self.current_user}' aux groupes 'render' et"
          " 'video'...\n"
      )

      # Utilisation du chemin absolu /usr/sbin/usermod
      cmd = [
          "pkexec",
          "/usr/sbin/usermod",
          "-aG",
          "render,video",
          self.current_user,
      ]

      try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
          self.log(
              f"[SUCCÈS] Utilisateur '{self.current_user}' ajouté aux groupes.\n"
          )
          self.root.after(
              0,
              lambda: messagebox.showinfo(
                  "Redémarrage requis",
                  "Fermez votre session pour valider les groupes.",
              ),
          )
        else:
          self.log(f"[ERREUR] Échec de modification : {result.stderr}\n")
      except Exception as e:
        self.log(f"\n[EXCEPTION] {str(e)}\n")
      finally:
        self.toggle_buttons("normal")

    def run_rdna2_detection_thread(self):
        threading.Thread(
            target=self.detect_and_apply_rdna2, daemon=True
        ).start()

    def detect_and_apply_rdna2(self):
        self.toggle_buttons("disabled")
        self.log("\n>>> Analyse du matériel graphique (recherche GPU RDNA2)...\n")
        try:
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, check=True
            )
            lspci_out = result.stdout.lower()

            rdna2_indicators = [
                "navi 2",
                "rx 6",
                "6700",
                "6600",
                "6500",
                "6400",
                "gfx103",
            ]
            is_rdna2 = any(
                indicator in lspci_out for indicator in rdna2_indicators
            )

            if is_rdna2:
                self.log("[INFO] GPU AMD RDNA2 détecté.\n")
                self.log(">>> Application du correctif HSA_OVERRIDE_GFX_VERSION=10.3.0...\n")

                script_content = (
                    "mkdir -p /etc/systemd/system/ollama.service.d && "
                    'echo -e "[Service]\\nEnvironment=\\"HSA_OVERRIDE_GFX_VERSION=10.3.0\\"" > /etc/systemd/system/ollama.service.d/override.conf && '
                    "systemctl daemon-reload && "
                    "systemctl restart ollama"
                )

                cmd = ["pkexec", "bash", "-c", script_content]
                res = subprocess.run(cmd, capture_output=True, text=True)

                if res.returncode == 0:
                    self.log("[SUCCÈS] Correctif appliqué et service redémarré.\n")
                else:
                    self.log(f"[ERREUR] Échec du correctif : {res.stderr}\n")
            else:
                self.log("[INFO] Aucun GPU RDNA2 nécessitant le correctif n'a été détecté.\n")
        except Exception as e:
            self.log(f"\n[EXCEPTION] {str(e)}\n")
        finally:
            self.toggle_buttons("normal")

    def check_status(self):
        self.log("\n>>> Vérification du service système...\n")
        is_active = subprocess.run(
            ["systemctl", "is-active", "ollama"], capture_output=True, text=True
        )
        self.log(f"• État du moteur : {is_active.stdout.strip().upper()}\n")

        full_status = subprocess.run(
            ["systemctl", "status", "ollama", "--no-pager"],
            capture_output=True,
            text=True,
        )
        if full_status.stdout:
            self.log(full_status.stdout + "\n")
        else:
            self.log("Service 'ollama' introuvable.\n")


if __name__ == "__main__":
    root = tk.Tk()
    app = OllamaInstallerApp(root)
    root.mainloop()
