#!/usr/bin/env python3
"""
Ollama Suite : installateur + client de chat dans une seule fenêtre.

Deux onglets (ttk.Notebook) :
  1. « Chat »         : mini interface de discussion avec les modèles Ollama
                        (historique, pièces jointes, gestion des modèles).
  2. « Installation » : installation d'Ollama, groupes utilisateur et
                        correctif GPU AMD RDNA2 (Debian / Ubuntu).
"""

import base64
import getpass
import json
import os
import shutil
import subprocess
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# ============================================================================
# CONSTANTES GLOBALES
# ============================================================================

# Dossiers de configuration et de sauvegarde des conversations
CONFIG_DIR = os.path.expanduser("~/.config/mini_ollama_gui")
DATA_DIR = os.path.join(CONFIG_DIR, "sessions")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

# Adresse du serveur Ollama local
OLLAMA_URL = "http://127.0.0.1:11434"

# Icône optionnelle, cherchée à côté du script
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ollama-suite.png")

# Catalogue des modèles proposés dans la fenêtre de gestion
AVAILABLE_MODELS_INFO = {
    "mistral:7b": "Modèle généraliste performant, idéal pour le français.",
    "qwen2.5-coder:7b": "Spécialisé dans la génération et l'analyse de code informatique.",
    "llama3.1:8b": "Modèle polyvalent développé par Meta, excellent pour le raisonnement général.",
    "minicpm-v:latest": "Modèle multimodal ultra-léger, capable d'analyser et de décrire des images.",
    "deepseek-r1:8b": "Modèle axé sur le raisonnement logique avancé et la résolution de problèmes complexes.",
    "llava:7b": "Modèle visuel et textuel permettant d'interagir et de poser des questions sur des images.",
    "qwen3:8b": "Modèle polyvalent pour le raisonnement, la compréhension et la génération de contenus structurés.",
}

# Extensions gérées par la pièce jointe
TEXT_EXTENSIONS = (".txt", ".md", ".py", ".json")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

# Terminaux testés (dans l'ordre) pour lancer la surveillance GPU,
# avec l'option permettant d'exécuter une commande.
TERMINALS = [
    ("qterminal", "-e"),
    ("lxterminal", "-e"),
    ("xfce4-terminal", "-e"),
    ("gnome-terminal", "--"),
    ("xterm", "-e"),
]


# ============================================================================
# ONGLET 1 : CHAT AVEC OLLAMA
# ============================================================================
class ChatTab(ttk.Frame):
    """Onglet de discussion : historique à gauche, conversation à droite."""

    def __init__(self, parent, root):
        super().__init__(parent)
        self.root = root  # fenêtre principale (pour after() et les dialogues)

        # --- État de l'application ---
        self.current_session_id = None          # nom du fichier JSON de la session
        self.chat_history = []                  # messages envoyés/reçus (format API Ollama)
        self.current_model = tk.StringVar(value="")
        self.installed_models = []              # modèles présents dans Ollama
        self.sessions_files = []                # fichiers de sessions affichés dans la liste
        self.current_assistant_reply = ""       # réponse en cours de streaming
        self.attached_file_path = None          # pièce jointe en attente d'envoi

        os.makedirs(DATA_DIR, exist_ok=True)

        self._build_ui()
        self._load_config()
        self._load_sessions_list()
        self.fetch_installed_models()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _build_ui(self):
        """Crée le panneau d'historique (gauche) et la zone de chat (droite)."""
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        self._build_history_panel(paned)
        self._build_chat_panel(paned)

    def _build_history_panel(self, paned):
        """Panneau gauche : liste des conversations + boutons « + » et « - »."""
        left = ttk.Frame(paned, width=220)
        paned.add(left, weight=1)

        header = ttk.Frame(left)
        header.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(header, text="Conversations", style="Title.TLabel").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(header, text="-", width=3, command=self.delete_current_chat).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(header, text="+", width=3, command=self.start_new_chat).pack(side=tk.RIGHT)

        # Liste (tk.Listbox : pas d'équivalent ttk) avec ascenseur ttk
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.lst_sessions = tk.Listbox(
            list_frame, bd=0, highlightthickness=1, exportselection=False,
            yscrollcommand=scroll.set,
        )
        scroll.config(command=self.lst_sessions.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst_sessions.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lst_sessions.bind("<<ListboxSelect>>", self.on_session_select)

    def _build_chat_panel(self, paned):
        """Panneau droit : barre d'outils, zone de messages, saisie."""
        right = ttk.Frame(paned)
        paned.add(right, weight=4)

        # --- Barre supérieure : modèle, gestion, GPU, statut ---
        toolbar = ttk.Frame(right)
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(toolbar, text="Modèle :", style="Bold.TLabel").pack(side=tk.LEFT, padx=(0, 5))

        self.model_combo = ttk.Combobox(
            toolbar, textvariable=self.current_model, state="readonly", width=25
        )
        self.model_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.model_combo.bind("<<ComboboxSelected>>", lambda e: self._save_config())

        ttk.Button(toolbar, text="Gestion des modèles", command=self.open_models_dialog).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(toolbar, text="Surveillance du GPU", command=self.open_gpu_monitor).pack(
            side=tk.LEFT, padx=(0, 10)
        )

        self.lbl_status = ttk.Label(toolbar, text="Prêt", style="Status.TLabel", foreground="green")
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- Zone d'affichage des messages (tk.Text + ascenseur ttk) ---
        chat_frame = ttk.Frame(right)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        chat_scroll = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL)
        self.txt_chat = tk.Text(
            chat_frame, wrap=tk.WORD, state=tk.DISABLED, bg="#ffffff",
            font=("sans-serif", 10), yscrollcommand=chat_scroll.set,
        )
        chat_scroll.config(command=self.txt_chat.yview)
        chat_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Styles de texte selon l'émetteur
        self.txt_chat.tag_config("user", foreground="#0055AA", font=("sans-serif", 10, "bold"))
        self.txt_chat.tag_config("assistant", foreground="#222222")
        self.txt_chat.tag_config("system", foreground="#888888", font=("sans-serif", 9, "italic"))

        # --- Indicateur de fichier joint ---
        self.lbl_attachment = ttk.Label(right, text="", style="Attach.TLabel", foreground="#006600")
        self.lbl_attachment.pack(anchor=tk.W, padx=10)

        # --- Zone de saisie : trombone, champ de texte, bouton d'envoi ---
        input_frame = ttk.Frame(right)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        self.btn_attach = ttk.Button(input_frame, text="📎", width=3, command=self.attach_file)
        self.btn_attach.pack(side=tk.LEFT, padx=(0, 5))

        self.entry_msg = ttk.Entry(input_frame, font=("sans-serif", 10))
        self.entry_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry_msg.bind("<Return>", lambda e: self.send_message())

        self.btn_send = ttk.Button(input_frame, text="Envoyer", command=self.send_message)
        self.btn_send.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Utilitaires d'interface
    # ------------------------------------------------------------------
    def set_status(self, text, color="green"):
        """Met à jour le message de statut (couleur : green / orange / red)."""
        self.lbl_status.config(text=text, foreground=color)

    def set_busy(self, busy):
        """Active/désactive les boutons d'envoi pendant une génération."""
        state = tk.DISABLED if busy else tk.NORMAL
        self.btn_send.config(state=state)
        self.btn_attach.config(state=state)

    def _append_text(self, text, tag):
        """Ajoute du texte à la fin du chat (la zone est en lecture seule sinon)."""
        self.txt_chat.config(state=tk.NORMAL)
        self.txt_chat.insert(tk.END, text, tag)
        self.txt_chat.config(state=tk.DISABLED)
        self.txt_chat.see(tk.END)

    def _clear_chat(self):
        """Efface complètement la zone d'affichage."""
        self.txt_chat.config(state=tk.NORMAL)
        self.txt_chat.delete("1.0", tk.END)
        self.txt_chat.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Pièces jointes
    # ------------------------------------------------------------------
    def attach_file(self):
        """Ouvre un sélecteur de fichier et mémorise la pièce jointe."""
        file_path = filedialog.askopenfilename(
            title="Sélectionner un fichier",
            filetypes=[
                ("Tous les fichiers supportés", "*.txt *.md *.py *.json *.png *.jpg *.jpeg *.pdf"),
                ("Fichiers texte", "*.txt *.md *.py *.json"),
                ("Images", "*.png *.jpg *.jpeg"),
                ("Documents PDF", "*.pdf"),
            ],
        )
        if file_path:
            self.attached_file_path = file_path
            self.lbl_attachment.config(text=f"Fichier joint : {os.path.basename(file_path)}")

    def _clear_attachment(self):
        """Oublie la pièce jointe courante."""
        self.attached_file_path = None
        self.lbl_attachment.config(text="")

    def _read_attachment(self):
        """
        Lit la pièce jointe et renvoie (texte_a_ajouter, liste_images_base64).
        - Images  : encodées en base64 (champ « images » de l'API).
        - Texte   : contenu ajouté au prompt.
        - PDF     : texte extrait via pypdf si disponible.
        """
        text_to_append = ""
        images = []
        path = self.attached_file_path
        if not path:
            return text_to_append, images

        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()

        try:
            if ext in IMAGE_EXTENSIONS:
                with open(path, "rb") as f:
                    images.append(base64.b64encode(f.read()).decode("utf-8"))

            elif ext in TEXT_EXTENSIONS:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text_to_append = f"\n\n--- Contenu de {name} ---\n{f.read()}"

            elif ext == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(path)
                    pdf_text = "".join(page.extract_text() or "" for page in reader.pages)
                    text_to_append = f"\n\n--- Contenu PDF ({name}) ---\n{pdf_text}"
                except ImportError:
                    # pypdf absent : on signale seulement la présence du fichier
                    text_to_append = f"\n\n[Fichier PDF attaché : {name} (pypdf non installé)]"
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lire « {name} » : {e}")

        return text_to_append, images

    # ------------------------------------------------------------------
    # Boutons supplémentaires : GPU et gestion des modèles
    # ------------------------------------------------------------------
    def open_gpu_monitor(self):
        """Lance nvtop (ou rocm-smi à défaut) dans le premier terminal trouvé."""
        cmd = "nvtop" if shutil.which("nvtop") else "rocm-smi"
        if not shutil.which(cmd):
            messagebox.showerror("Erreur", "Ni nvtop ni rocm-smi n'est installé.")
            return

        # Premier terminal disponible, avec son option d'exécution
        term = next(((t, opt) for t, opt in TERMINALS if shutil.which(t)), None)
        try:
            if term:
                # rocm-smi s'arrête aussitôt : on garde la fenêtre ouverte
                if cmd == "rocm-smi":
                    subprocess.Popen([term[0], term[1], "bash", "-c", "rocm-smi; read -p 'Entrée pour fermer'"])
                else:
                    subprocess.Popen([term[0], term[1], cmd])
            else:
                subprocess.Popen([cmd])
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lancer la surveillance GPU : {e}")

    def open_models_dialog(self):
        """Fenêtre modale listant les modèles recommandés et permettant de les télécharger."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Gestionnaire de modèles Ollama")
        dlg.geometry("680x380")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(
            dlg, text="Modèles recommandés (installés ou téléchargeables) :", style="Bold.TLabel"
        ).pack(anchor=tk.W, padx=10, pady=10)

        # Zone défilante : Canvas + Frame interne + ascenseur
        container = ttk.Frame(dlg)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        canvas = tk.Canvas(container, highlightthickness=0, bg=self.root.cget("bg"))
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        rows_frame = ttk.Frame(canvas)

        rows_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def refresh_list():
            """Reconstruit les lignes (une par modèle) selon l'état d'installation."""
            for widget in rows_frame.winfo_children():
                widget.destroy()

            for name, desc in AVAILABLE_MODELS_INFO.items():
                row = ttk.Frame(rows_frame, padding=5)
                row.pack(fill=tk.X, expand=True, pady=2)

                installed = name in self.installed_models
                ttk.Label(row, text=name, style="Bold.TLabel", width=20).pack(side=tk.LEFT)
                ttk.Label(
                    row,
                    text="[ Installé ]" if installed else "[ Non installé ]",
                    foreground="green" if installed else "gray",
                    width=15,
                ).pack(side=tk.LEFT)
                ttk.Label(row, text=desc, wraplength=250).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

                if not installed:
                    btn = ttk.Button(row, text="Télécharger")
                    # Liaison après création pour que le bouton puisse se passer lui-même
                    btn.config(command=lambda m=name, b=btn: start_pull(m, b))
                    btn.pack(side=tk.RIGHT)

        def start_pull(model_name, btn):
            """Télécharge un modèle dans un thread pour ne pas figer l'interface."""
            btn.config(state=tk.DISABLED, text="Téléchargement...")
            self.set_status(f"Téléchargement de {model_name} en cours...", "orange")

            def worker():
                try:
                    payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{OLLAMA_URL}/api/pull", data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=600) as resp:
                        resp.read()
                    self.root.after(0, on_success)
                except Exception:
                    self.root.after(0, on_failure)

            def on_success():
                self.fetch_installed_models()
                self.set_status(f"Modèle {model_name} installé avec succès !", "green")
                # La liste des modèles installés est mise à jour de façon asynchrone :
                # on rafraîchit la fenêtre un peu après.
                if dlg.winfo_exists():
                    dlg.after(800, refresh_list)

            def on_failure():
                if btn.winfo_exists():
                    btn.config(state=tk.NORMAL, text="Télécharger")
                self.set_status(f"Erreur lors du téléchargement de {model_name}", "red")

            threading.Thread(target=worker, daemon=True).start()

        refresh_list()
        ttk.Button(dlg, text="Fermer", command=dlg.destroy).pack(pady=10)

    # ------------------------------------------------------------------
    # Configuration et modèles installés
    # ------------------------------------------------------------------
    def _load_config(self):
        """Recharge le dernier modèle utilisé."""
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                last_model = json.load(f).get("last_model", "")
            if last_model:
                self.current_model.set(last_model)
        except Exception:
            pass  # fichier corrompu : on repart avec les valeurs par défaut

    def _save_config(self):
        """Mémorise le modèle sélectionné."""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_model": self.current_model.get()}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def fetch_installed_models(self):
        """Interroge Ollama (/api/tags) dans un thread et met à jour la liste déroulante."""
        def worker():
            try:
                with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                self.root.after(0, self._update_models_list, models)
            except Exception:
                self.root.after(0, lambda: self.set_status("Erreur connexion Ollama", "red"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_models_list(self, models):
        """Met à jour la liste déroulante et choisit un modèle valide."""
        self.installed_models = models
        self.model_combo["values"] = models

        current = self.current_model.get()
        if models and current not in models:
            self.current_model.set(models[0])
            self._save_config()
        elif not models:
            self.set_status("Aucun modèle trouvé dans Ollama", "red")

    # ------------------------------------------------------------------
    # Envoi d'un message et streaming de la réponse
    # ------------------------------------------------------------------
    def send_message(self):
        """Prépare le message (texte + pièce jointe), l'affiche et lance la requête."""
        prompt = self.entry_msg.get().strip()
        model = self.current_model.get()
        if (not prompt and not self.attached_file_path) or not model:
            return

        attachment_name = os.path.basename(self.attached_file_path) if self.attached_file_path else None
        extra_text, images = self._read_attachment()
        full_prompt = prompt + extra_text

        # Première question : on crée la session avec un titre court
        if not self.current_session_id:
            self._create_session(prompt, attachment_name)

        # Affichage du message utilisateur
        self.entry_msg.delete(0, tk.END)
        display_text = prompt + (f" [📎 {attachment_name}]" if attachment_name else "")
        self._append_text("\nVous:\n", "user")
        self._append_text(f"{display_text}\n", "assistant")

        # Ajout à l'historique envoyé à l'API
        message = {"role": "user", "content": full_prompt}
        if images:
            message["images"] = images
        self.chat_history.append(message)

        self._clear_attachment()
        self.set_busy(True)

        # En-tête de la réponse du modèle, puis requête dans un thread
        self._append_text(f"\n{model}:\n", "user")
        self.current_assistant_reply = ""
        threading.Thread(target=self._stream_worker, args=(model,), daemon=True).start()

    def _create_session(self, prompt, attachment_name):
        """Crée le fichier de la nouvelle conversation et le sélectionne dans la liste."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session_id = f"chat_{timestamp}.json"

        if prompt:
            title = prompt[:30] + "..." if len(prompt) > 30 else prompt
        else:
            title = attachment_name or "Conversation"

        self._save_session_file(self.current_session_id, title, [])
        self._load_sessions_list()

    def _stream_worker(self, model):
        """Thread : lit la réponse d'Ollama ligne par ligne (JSON) et l'affiche au fil de l'eau."""
        payload = json.dumps(
            {"model": model, "messages": self.chat_history, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req) as response:
                for line in response:
                    if not line.strip():
                        continue
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        self.current_assistant_reply += content
                        self.root.after(0, self._append_text, content, "assistant")
            self.root.after(0, self._finalize_response)
        except Exception as e:
            self.root.after(0, self._handle_error, str(e))

    def _finalize_response(self):
        """Fin de génération : on enregistre la réponse dans l'historique et sur disque."""
        self.chat_history.append({"role": "assistant", "content": self.current_assistant_reply})
        self.set_busy(False)
        self.save_current_session()

    def _handle_error(self, err_msg):
        """Erreur réseau : on affiche le problème et on retire la question sans réponse."""
        self._append_text(f"\n[Erreur Ollama: {err_msg}]\n", "system")
        if self.chat_history and self.chat_history[-1]["role"] == "user":
            self.chat_history.pop()  # garde l'historique cohérent (alternance user/assistant)
        self.set_busy(False)

    # ------------------------------------------------------------------
    # Sessions (sauvegarde / chargement / suppression)
    # ------------------------------------------------------------------
    def start_new_chat(self):
        """Réinitialise l'interface pour une nouvelle conversation."""
        self.current_session_id = None
        self.chat_history = []
        self._clear_attachment()
        self._clear_chat()
        self.lst_sessions.selection_clear(0, tk.END)

    def delete_current_chat(self):
        """Supprime la conversation sélectionnée dans la liste."""
        selection = self.lst_sessions.curselection()
        if not selection or selection[0] >= len(self.sessions_files):
            return

        filename = self.sessions_files[selection[0]]
        try:
            filepath = os.path.join(DATA_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
            if self.current_session_id == filename:
                self.start_new_chat()
            self._load_sessions_list()
        except Exception:
            pass

    def save_current_session(self):
        """Écrit l'historique courant en conservant le titre existant."""
        if not self.current_session_id or not self.chat_history:
            return

        filepath = os.path.join(DATA_DIR, self.current_session_id)
        title = "Sans titre"
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    title = json.load(f).get("title", title)
            except Exception:
                pass

        self._save_session_file(self.current_session_id, title, self.chat_history)
        self._load_sessions_list()

    def _save_session_file(self, filename, title, history):
        """Écrit un fichier de session JSON {titre, historique}."""
        with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as f:
            json.dump({"title": title, "history": history}, f, ensure_ascii=False, indent=2)

    def _load_sessions_list(self):
        """Remplit la liste des conversations (les plus récentes en haut)."""
        selected = self.current_session_id
        self.lst_sessions.delete(0, tk.END)
        self.sessions_files = []

        if not os.path.exists(DATA_DIR):
            return

        for filename in sorted((f for f in os.listdir(DATA_DIR) if f.endswith(".json")), reverse=True):
            try:
                with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
                    title = json.load(f).get("title", "Sans titre")
            except Exception:
                continue  # fichier illisible : on l'ignore
            self.lst_sessions.insert(tk.END, f"  {title}")
            self.sessions_files.append(filename)

        # Conserve la sélection de la session active
        if selected in self.sessions_files:
            self.lst_sessions.selection_set(self.sessions_files.index(selected))

    def on_session_select(self, event):
        """Charge et affiche la conversation choisie dans la liste."""
        selection = self.lst_sessions.curselection()
        if not selection or selection[0] >= len(self.sessions_files):
            return

        filename = self.sessions_files[selection[0]]
        self.current_session_id = filename

        try:
            with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
                self.chat_history = json.load(f).get("history", [])
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de charger la conversation : {e}")
            return

        # Réaffichage complet (les images base64 ne sont pas montrées)
        assistant_label = self.current_model.get() or "Assistant"
        self._clear_chat()
        for msg in self.chat_history:
            label = "Vous" if msg["role"] == "user" else assistant_label
            self._append_text(f"\n{label}:\n", "user")
            self._append_text(f"{msg.get('content', '')}\n", "assistant")


# ============================================================================
# ONGLET 2 : INSTALLATION D'OLLAMA ET CONFIGURATION GPU AMD
# ============================================================================
class InstallerTab(ttk.Frame):
    """Onglet d'installation : quatre actions et une console de journal."""

    def __init__(self, parent, root, on_install_done=None):
        super().__init__(parent)
        self.root = root
        self.on_install_done = on_install_done   # callback appelé après une installation réussie
        self.current_user = getpass.getuser()
        self.buttons = []                        # boutons à désactiver pendant une action

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- En-tête ---
        header = ttk.Frame(self, style="Header.TFrame", padding=12)
        header.pack(fill=tk.X)
        ttk.Label(
            header, text="Installation d'Ollama & Configuration AMD GPU", style="HeaderTitle.TLabel"
        ).pack()
        ttk.Label(
            header,
            text=f"Utilisateur détecté : {self.current_user} (Système Debian / Ubuntu)",
            style="HeaderSub.TLabel",
        ).pack()

        # --- Boutons d'action : (texte, commande, style) ---
        actions = [
            ("1. Installer\nOllama", self.run_install_thread, "Install.TButton"),
            ("2. Groupes\n(render, video)", self.run_groups_thread, "Groups.TButton"),
            ("3. Correctif\nRDNA2 (RX 6000)", self.run_rdna2_thread, "Rdna2.TButton"),
            ("4. Vérifier\nle Service", self.run_status_thread, "Status.TButton"),
        ]
        btn_frame = ttk.Frame(self, padding=(10, 15))
        btn_frame.pack(fill=tk.X)
        for text, command, style in actions:
            btn = ttk.Button(btn_frame, text=text, command=command, style=style, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)
            self.buttons.append(btn)

        # --- Console de journal ---
        ttk.Label(self, text="Journal d'exécution :", style="Bold.TLabel").pack(anchor=tk.W, padx=20)

        log_frame = ttk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 15))

        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL)
        self.log_area = tk.Text(
            log_frame, height=16, bg="#1e1e1e", fg="#00ff00", font=("Monospace", 10),
            state=tk.DISABLED, yscrollcommand=log_scroll.set,
        )
        log_scroll.config(command=self.log_area.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log("Prêt. Suivez les étapes de gauche à droite.\n")
        self.log("-" * 65 + "\n")

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------
    def log(self, message):
        """Ajoute une ligne au journal (utilisable depuis n'importe quel thread)."""
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, message)
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)

    def _set_buttons(self, enabled):
        """Active ou désactive tous les boutons d'action (thread-safe)."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.root.after(0, lambda: [b.config(state=state) for b in self.buttons])

    def _run_in_thread(self, func):
        """
        Exécute une action dans un thread, en bloquant les boutons pendant sa durée
        et en les réactivant quoi qu'il arrive.
        """
        def wrapper():
            self._set_buttons(False)
            try:
                func()
            except Exception as e:
                self.log(f"\n[EXCEPTION] {e}\n")
            finally:
                self._set_buttons(True)

        threading.Thread(target=wrapper, daemon=True).start()

    # Points d'entrée des boutons
    def run_install_thread(self):
        self._run_in_thread(self.install_ollama)

    def run_groups_thread(self):
        self._run_in_thread(self.configure_groups)

    def run_rdna2_thread(self):
        self._run_in_thread(self.detect_and_apply_rdna2)

    def run_status_thread(self):
        self._run_in_thread(self.check_status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def install_ollama(self):
        """Télécharge et exécute le script officiel d'installation avec les droits root (pkexec)."""
        self.log("\n>>> Démarrage de l'installation d'Ollama...\n")

        cmd = "curl -fsSL https://ollama.com/install.sh | pkexec env bash"
        process = subprocess.Popen(
            ["bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # Affichage de la sortie en direct
        for line in process.stdout:
            self.log(line)
        process.wait()

        if process.returncode == 0:
            self.log("\n[SUCCÈS] Ollama a été installé correctement !\n")
            if self.on_install_done:
                # Laisse un instant au service pour démarrer avant d'interroger l'API
                self.root.after(3000, self.on_install_done)
        else:
            self.log(f"\n[ERREUR] Fin avec le code {process.returncode}.\n")

    def configure_groups(self):
        """Ajoute l'utilisateur aux groupes « render » et « video » (accès au GPU)."""
        self.log(f"\n>>> Ajout de '{self.current_user}' aux groupes 'render' et 'video'...\n")

        cmd = ["pkexec", "/usr/sbin/usermod", "-aG", "render,video", self.current_user]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            self.log(f"[SUCCÈS] Utilisateur '{self.current_user}' ajouté aux groupes.\n")
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Redémarrage requis", "Fermez votre session pour valider les groupes."
                ),
            )
        else:
            self.log(f"[ERREUR] Échec de modification : {result.stderr}\n")

    def detect_and_apply_rdna2(self):
        """Détecte un GPU AMD RDNA2 via lspci et applique le correctif HSA_OVERRIDE_GFX_VERSION."""
        self.log("\n>>> Analyse du matériel graphique (recherche GPU RDNA2)...\n")

        lspci_out = subprocess.run(["lspci"], capture_output=True, text=True, check=True).stdout.lower()

        # Mots-clés révélant une carte RDNA2 (RX 6000)
        indicators = ["navi 2", "rx 6", "6700", "6600", "6500", "6400", "gfx103"]
        if not any(word in lspci_out for word in indicators):
            self.log("[INFO] Aucun GPU RDNA2 nécessitant le correctif n'a été détecté.\n")
            return

        self.log("[INFO] GPU AMD RDNA2 détecté.\n")
        self.log(">>> Application du correctif HSA_OVERRIDE_GFX_VERSION=10.3.0...\n")

        # Crée un « drop-in » systemd pour le service, recharge puis redémarre Ollama
        script = (
            "mkdir -p /etc/systemd/system/ollama.service.d && "
            "printf '[Service]\\nEnvironment=\"HSA_OVERRIDE_GFX_VERSION=10.3.0\"\\n' "
            "> /etc/systemd/system/ollama.service.d/override.conf && "
            "systemctl daemon-reload && systemctl restart ollama"
        )
        res = subprocess.run(["pkexec", "bash", "-c", script], capture_output=True, text=True)

        if res.returncode == 0:
            self.log("[SUCCÈS] Correctif appliqué et service redémarré.\n")
        else:
            self.log(f"[ERREUR] Échec du correctif : {res.stderr}\n")

    def check_status(self):
        """Affiche l'état du service systemd « ollama »."""
        self.log("\n>>> Vérification du service système...\n")

        active = subprocess.run(["systemctl", "is-active", "ollama"], capture_output=True, text=True)
        self.log(f"• État du moteur : {active.stdout.strip().upper()}\n")

        full = subprocess.run(
            ["systemctl", "status", "ollama", "--no-pager"], capture_output=True, text=True
        )
        self.log((full.stdout + "\n") if full.stdout else "Service 'ollama' introuvable.\n")


# ============================================================================
# FENÊTRE PRINCIPALE
# ============================================================================
class OllamaSuite(tk.Tk):
    """Fenêtre principale : un ttk.Notebook contenant les deux onglets."""

    def __init__(self):
        super().__init__()
        self.title("Ollama Suite")
        self.geometry("1024x650")
        self.minsize(1024, 650)

        self._load_icon()
        self._configure_styles()

        # Notebook avec ses deux onglets
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.chat_tab = ChatTab(notebook, self)
        # Après une installation réussie, on rafraîchit la liste des modèles du chat
        self.installer_tab = InstallerTab(
            notebook, self, on_install_done=self.chat_tab.fetch_installed_models
        )

        notebook.add(self.chat_tab, text="  💬 Chat  ")
        notebook.add(self.installer_tab, text="  🛠 Installation  ")

    def _load_icon(self):
        """Charge l'icône de la fenêtre si le fichier est présent."""
        if not os.path.exists(ICON_PATH):
            return
        try:
            self._icon = tk.PhotoImage(file=ICON_PATH)  # référence conservée (sinon ramassée)
            self.iconphoto(True, self._icon)
        except Exception as e:
            print(f"Impossible de charger l'icône : {e}")

    def _configure_styles(self):
        """Définit tous les styles ttk utilisés par les deux onglets."""
        style = ttk.Style(self)
        # Le thème « clam » respecte les couleurs de fond des boutons ttk
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # --- Étiquettes ---
        style.configure("Title.TLabel", font=("sans-serif", 10, "bold"))
        style.configure("Bold.TLabel", font=("sans-serif", 9, "bold"))
        style.configure("Status.TLabel", font=("sans-serif", 9, "italic"))
        style.configure("Attach.TLabel", font=("sans-serif", 8, "italic"))

        # --- En-tête de l'onglet d'installation ---
        style.configure("Header.TFrame", background="#2c3e50")
        style.configure("HeaderTitle.TLabel", background="#2c3e50", foreground="white",
                        font=("Helvetica", 14, "bold"))
        style.configure("HeaderSub.TLabel", background="#2c3e50", foreground="#bdc3c7",
                        font=("Helvetica", 10))

        # --- Boutons colorés de l'onglet d'installation ---
        colors = {
            "Install.TButton": ("#27ae60", "#2ecc71"),   # vert
            "Groups.TButton": ("#2980b9", "#3498db"),    # bleu
            "Rdna2.TButton": ("#d35400", "#e67e22"),     # orange
            "Status.TButton": ("#8e44ad", "#9b59b6"),    # violet
        }
        for name, (normal, hover) in colors.items():
            style.configure(name, background=normal, foreground="white",
                            font=("Helvetica", 11, "bold"), padding=8, anchor="center")
            style.map(name,
                      background=[("disabled", "#95a5a6"), ("active", hover)],
                      foreground=[("disabled", "#ecf0f1")])


if __name__ == "__main__":
    OllamaSuite().mainloop()
