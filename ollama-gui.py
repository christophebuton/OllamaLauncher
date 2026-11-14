#!/usr/bin/env python3
import os
import json
import threading
import subprocess
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import base64

# Dossiers de configuration et de sauvegarde
CONFIG_DIR = os.path.expanduser("~/.config/mini_ollama_gui")
DATA_DIR = os.path.join(CONFIG_DIR, "sessions")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
OLLAMA_URL = "http://127.0.0.1:11434"

AVAILABLE_MODELS_INFO = {
    "mistral:7b": "Modèle généraliste performant de 7 milliards de paramètres, idéal pour le français.",
    "qwen2.5-coder:7b": "Spécialisé dans la génération et l'analyse de code informatique.",
    "llama3.1:8b": "Modèle polyvalent développé par Meta, excellent pour le raisonnement général.",
    "minicpm-v:latest": "Modèle multimodal ultra-léger, capable d'analyser et de décrire des images.",
    "deepseek-r1:8b": "Modèle axé sur le raisonnement logique avancé et la résolution de problèmes complexes.",
    "llava:7b": "Modèle visuel et textuel permettant d'interagir et de poser des questions sur des images.",
    "qwen3:8b": "Modèle polyvalent pour le raisonnement, la compréhension et la génération de contenus structurés."
}

class OllamaGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mini Ollama GUI")
        self.geometry("1024x650")
        self.minsize(1024, 650)

        # --- Ajout d'une icône
        icon_path = os.path.join(os.path.dirname(__file__), "ollama-launcher.png")
        if os.path.exists(icon_path):
            try:
                self.iconphoto(True, tk.PhotoImage(file=icon_path))
            except Exception as e:
                print(f"Impossible de charger l'icône : {e}")
        
        os.makedirs(DATA_DIR, exist_ok=True)
        
        self.current_session_id = None
        self.chat_history = []
        self.current_model = tk.StringVar(value="")
        self.installed_models = []
        self.sessions_files = []
        self.current_assistant_reply = ""
        self.attached_file_path = None

        self._build_ui()
        self._load_config()
        self._load_sessions_list()
        self.fetch_installed_models()

    def _build_ui(self):
        # Séparateur principal (PanedWindow)
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ------------------- PANNEAU GAUCHE : HISTORIQUE -------------------
        left_frame = ttk.Frame(paned, width=220)
        paned.add(left_frame, weight=1)

        # En-tête avec boutons '+' et '-'
        top_left_frame = ttk.Frame(left_frame)
        top_left_frame.pack(fill=tk.X, padx=5, pady=5)
        
        lbl_hist = ttk.Label(top_left_frame, text="Conversations", font=("sans-serif", 10, "bold"))
        lbl_hist.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        btn_del = ttk.Button(top_left_frame, text="-", width=3, command=self.delete_current_chat)
        btn_del.pack(side=tk.RIGHT, padx=2)
        
        btn_new = ttk.Button(top_left_frame, text="+", width=3, command=self.start_new_chat)
        btn_new.pack(side=tk.RIGHT)

        # Liste des conversations
        self.lst_sessions = tk.Listbox(left_frame, bd=0, highlightthickness=1)
        self.lst_sessions.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        self.lst_sessions.bind("<<ListboxSelect>>", self.on_session_select)

        # ------------------- PANNEAU CENTRAL : CHAT -------------------
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=4)

        # Barre supérieure : Sélection du modèle, Gestion et Surveillance GPU
        top_right_frame = ttk.Frame(right_frame)
        top_right_frame.pack(fill=tk.X, padx=10, pady=5)

        lbl_model = ttk.Label(top_right_frame, text="Modèle :", font=("sans-serif", 9, "bold"))
        lbl_model.pack(side=tk.LEFT, padx=(0, 5))

        self.model_combo = ttk.Combobox(top_right_frame, textvariable=self.current_model, state="readonly", width=25)
        self.model_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_change)

        # Bouton Catalogue / Gestion des modèles
        btn_models = ttk.Button(top_right_frame, text="Gestion des modèles", command=self.open_models_dialog)
        btn_models.pack(side=tk.LEFT, padx=(0, 5))

        # Bouton Surveillance GPU (nvtop)
        btn_gpu = ttk.Button(top_right_frame, text="Surveillance du GPU", command=self.open_gpu_monitor)
        btn_gpu.pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_status = ttk.Label(top_right_frame, text="Prêt", font=("sans-serif", 9, "italic"), foreground="green")
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Zone d'affichage des messages
        self.txt_chat = tk.Text(right_frame, wrap=tk.WORD, state=tk.DISABLED, bg="#ffffff", font=("sans-serif", 10))
        self.txt_chat.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Style des tags
        self.txt_chat.tag_config("user", foreground="#0055AA", font=("sans-serif", 10, "bold"))
        self.txt_chat.tag_config("assistant", foreground="#222222")
        self.txt_chat.tag_config("system", foreground="#888888", font=("sans-serif", 9, "italic"))

        # Indicateur de fichier attaché
        self.lbl_attachment = ttk.Label(right_frame, text="", font=("sans-serif", 8, "italic"), foreground="#006600")
        self.lbl_attachment.pack(anchor=tk.W, padx=10)

        # Zone d'envoi de message en bas
        input_frame = ttk.Frame(right_frame)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        # Bouton Trombone à gauche de l'entrée
        self.btn_attach = ttk.Button(input_frame, text="📎", width=3, command=self.attach_file)
        self.btn_attach.pack(side=tk.LEFT, padx=(0, 5))

        self.entry_msg = ttk.Entry(input_frame, font=("sans-serif", 10))
        self.entry_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry_msg.bind("<Return>", lambda event: self.send_message())

        self.btn_send = ttk.Button(input_frame, text="Envoyer", command=self.send_message)
        self.btn_send.pack(side=tk.RIGHT)

    # ------------------- GESTION DES FICHIERS ATTACHÉS -------------------
    def attach_file(self):
        file_path = filedialog.askopenfilename(
            title="Sélectionner un fichier",
            filetypes=[
                ("Tous les fichiers supportés", "*.txt *.md *.py *.json *.png *.jpg *.jpeg *.pdf"),
                ("Fichiers texte", "*.txt *.md *.py *.json"),
                ("Images", "*.png *.jpg *.jpeg"),
                ("Documents PDF", "*.pdf")
            ]
        )
        if file_path:
            self.attached_file_path = file_path
            filename = os.path.basename(file_path)
            self.lbl_attachment.config(text=f"Fichier joint : {filename}")

    # ------------------- ACTIONS BOUTONS SUPPLÉMENTAIRES -------------------
    def open_gpu_monitor(self):
        """Lance nvtop (ou rocm-smi de secours) dans un terminal LXQt ou système."""
        terminals = ["qterminal", "lxterminal", "xfce4-terminal", "gnome-terminal", "xterm"]
        chosen_term = next((t for t in terminals if subprocess.run(f"which {t}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0), None)
        
        cmd = "nvtop" if subprocess.run("which nvtop", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 else "rocm-smi"
        
        try:
            if chosen_term:
                subprocess.Popen([chosen_term, "-e", cmd])
            else:
                subprocess.Popen([cmd])
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lancer la surveillance GPU : {e}")

    def open_models_dialog(self):
        """Ouvre une fenêtre modale listant les modèles et permettant de les installer."""
        dlg = tk.Toplevel(self)
        dlg.title("Gestionnaire de modèles Ollama")
        dlg.geometry("680x380")
        dlg.transient(self)
        dlg.grab_set()

        lbl_info = ttk.Label(dlg, text="Modèles recommandés (Installés ou téléchargeables) :", font=("sans-serif", 10, "bold"))
        lbl_info.pack(anchor=tk.W, padx=10, pady=10)

        # Cadre avec ascenseur pour la liste
        container = ttk.Frame(dlg)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # On récupère la couleur de fond globale pour uniformiser le Canvas avec le reste de la fenêtre
        bg_color = self.cget("bg")
        canvas = tk.Canvas(container, bg=bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def refresh_dialog_list():
            for widget in scrollable_frame.winfo_children():
                widget.destroy()

            for model_name, desc in AVAILABLE_MODELS_INFO.items():
                row_frame = ttk.Frame(scrollable_frame, padding=5)
                row_frame.pack(fill=tk.X, expand=True, pady=2)

                is_installed = model_name in self.installed_models
                status_text = " [ Installé ]" if is_installed else " [ Non installé ]"
                status_color = "green" if is_installed else "gray"

                lbl_name = ttk.Label(row_frame, text=f"{model_name}", font=("sans-serif", 10, "bold"), width=20)
                lbl_name.pack(side=tk.LEFT)

                lbl_stat = ttk.Label(row_frame, text=status_text, foreground=status_color, width=15)
                lbl_stat.pack(side=tk.LEFT)

                lbl_desc = ttk.Label(row_frame, text=desc, wraplength=250)
                lbl_desc.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

                if not is_installed:
                    btn_install = ttk.Button(row_frame, text="Télécharger", command=lambda m=model_name: start_pull(m, btn_install))
                    btn_install.pack(side=tk.RIGHT)

        def start_pull(model_name, btn):
            btn.config(state=tk.DISABLED, text="Téléchargement...")
            self.lbl_status.config(text=f"Téléchargement de {model_name} en cours...", foreground="orange")
            
            def _pull_thread():
                try:
                    payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
                    req = urllib.request.Request(f"{OLLAMA_URL}/api/pull", data=payload, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=600) as resp:
                        resp.read()
                    
                    self.after(0, lambda: [
                        self.fetch_installed_models(),
                        refresh_dialog_list(),
                        self.lbl_status.config(text=f"Modèle {model_name} installé avec succès !", foreground="green")
                    ])
                except Exception as e:
                    self.after(0, lambda: [
                        btn.config(state=tk.NORMAL, text="Télécharger"),
                        # --- MODIFICATION ICI : Remettre le statut à "Prêt" ou afficher l'erreur en rouge ---
                        self.lbl_status.config(text=f"Erreur lors du téléchargement de {model_name}", foreground="red")
                    ])

            threading.Thread(target=_pull_thread, daemon=True).start()

        refresh_dialog_list()

        btn_close = ttk.Button(dlg, text="Fermer", command=dlg.destroy)
        btn_close.pack(pady=10)

    # ------------------- CONFIGURATION & OLLAMA (NETWORK) -------------------
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_model = data.get("last_model", "")
                    if last_model:
                        self.current_model.set(last_model)
            except Exception:
                pass

    def _save_config(self):
        try:
            data = {"last_model": self.current_model.get()}
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def fetch_installed_models(self):
        def _fetch():
            try:
                req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode())
                    models = [m["name"] for m in data.get("models", [])]
                    self.after(0, self._update_models_list, models)
            except Exception:
                self.after(0, lambda: self.lbl_status.config(text="Erreur connexion Ollama", foreground="red"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_models_list(self, models):
        self.installed_models = models
        self.model_combo['values'] = models
        
        current = self.current_model.get()
        if models and (not current or current not in models):
            self.current_model.set(models[0])
            self._save_config()
        elif not models:
            self.lbl_status.config(text="Aucun modèle trouvé dans Ollama", foreground="red")

    def on_model_change(self, event):
        self._save_config()

    def send_message(self):
        prompt = self.entry_msg.get().strip()
        model = self.current_model.get()
        if (not prompt and not self.attached_file_path) or not model:
            return

        # Traitement du fichier joint si présent
        images_list = []
        file_content_to_append = ""
        
        if self.attached_file_path:
            ext = os.path.splitext(self.attached_file_path)[1].lower()
            if ext in [".png", ".jpg", ".jpeg"]:
                try:
                    with open(self.attached_file_path, "rb") as img_file:
                        encoded_img = base64.b64encode(img_file.read()).decode("utf-8")
                        images_list.append(encoded_img)
                except Exception as e:
                    messagebox.showerror("Erreur", f"Impossible de lire l'image : {e}")
            elif ext in [".txt", ".md", ".py", ".json"]:
                try:
                    with open(self.attached_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_text = f.read()
                        file_content_to_append = f"\n\n--- Contenu de {os.path.basename(self.attached_file_path)} ---\n{file_text}"
                except Exception as e:
                    messagebox.showerror("Erreur", f"Impossible de lire le fichier texte : {e}")
            elif ext == ".pdf":
                try:
                    # Extraction basique du texte via pypdf si disponible, sinon message
                    import pypdf
                    reader = pypdf.PdfReader(self.attached_file_path)
                    pdf_text = ""
                    for page in reader.pages:
                        pdf_text += page.extract_text() or ""
                    file_content_to_append = f"\n\n--- Contenu PDF ({os.path.basename(self.attached_file_path)}) ---\n{pdf_text}"
                except ImportError:
                    # Fallback si pypdf n'est pas installé
                    try:
                        import pypdf as pdf_mod # type: ignore
                    except Exception:
                        pass
                    # Si pypdf abs, on tente d'informer ou d'utiliser un fallback minimal
                    file_content_to_append = f"\n\n[Fichier PDF attaché : {os.path.basename(self.attached_file_path)}]"
                except Exception as e:
                    messagebox.showerror("Erreur", f"Impossible de lire le PDF : {e}")

        full_prompt = prompt + file_content_to_append

        if not self.current_session_id:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_session_id = f"chat_{timestamp}.json"
            title = prompt[:30] + "..." if len(prompt) > 30 else (os.path.basename(self.attached_file_path) if self.attached_file_path else "Conversation")
            self._save_session_file(self.current_session_id, title, [])
            self._load_sessions_list()
            
            if self.sessions_files:
                idx = self.sessions_files.index(self.current_session_id)
                self.lst_sessions.selection_clear(0, tk.END)
                self.lst_sessions.selection_set(idx)

        self.entry_msg.delete(0, tk.END)
        display_text = prompt
        if self.attached_file_path:
            display_text += f" [📎 {os.path.basename(self.attached_file_path)}]"

        self._append_text(f"\nVous:\n", "user")
        self._append_text(f"{display_text}\n", "assistant")

        message_payload = {"role": "user", "content": full_prompt}
        if images_list:
            message_payload["images"] = images_list

        self.chat_history.append(message_payload)
        
        # Réinitialisation du fichier attaché après envoi
        self.attached_file_path = None
        self.lbl_attachment.config(text="")

        self.btn_send.config(state=tk.DISABLED)
        self.btn_attach.config(state=tk.DISABLED)

        self._append_text(f"\n{model}:\n", "user")
        self.current_assistant_reply = ""

        threading.Thread(target=self._query_ollama_streaming_thread, args=(model,), daemon=True).start()

    def _query_ollama_streaming_thread(self, model):
        payload = json.dumps({
            "model": model,
            "messages": self.chat_history,
            "stream": True
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req) as response:
                for line in response:
                    if line:
                        chunk_data = json.loads(line.decode("utf-8"))
                        content = chunk_data.get("message", {}).get("content", "")
                        if content:
                            self.current_assistant_reply += content
                            self.after(0, self._append_text_chunk, content)
            
            self.after(0, self._finalize_response)
        except Exception as e:
            self.after(0, self._handle_error, str(e))

    def _append_text_chunk(self, chunk):
        self._append_text(chunk, "assistant")

    def _finalize_response(self):
        self.chat_history.append({"role": "assistant", "content": self.current_assistant_reply})
        self.btn_send.config(state=tk.NORMAL)
        self.btn_attach.config(state=tk.NORMAL)
        self.save_current_session()

    def _handle_error(self, err_msg):
        self._append_text(f"\n[Erreur Ollama: {err_msg}]\n", "system")
        self.btn_send.config(state=tk.NORMAL)
        self.btn_attach.config(state=tk.NORMAL)

    # ------------------- GESTION DES FICHIERS & SESSIONS -------------------
    def start_new_chat(self):
        self.current_session_id = None
        self.chat_history = []
        self.attached_file_path = None
        self.lbl_attachment.config(text="")
        
        self.txt_chat.config(state=tk.NORMAL)
        self.txt_chat.delete("1.0", tk.END)
        self.txt_chat.config(state=tk.DISABLED)
        
        self.lst_sessions.selection_clear(0, tk.END)

    def delete_current_chat(self):
        selection = self.lst_sessions.curselection()
        if not selection:
            return
        
        idx = selection[0]
        if idx >= len(self.sessions_files):
            return

        filename = self.sessions_files[idx]
        filepath = os.path.join(DATA_DIR, filename)

        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            
            if self.current_session_id == filename:
                self.start_new_chat()
            
            self._load_sessions_list()
        except Exception:
            pass

    def save_current_session(self):
        if not self.current_session_id or not self.chat_history:
            return
        filepath = os.path.join(DATA_DIR, self.current_session_id)
        title = "Sans titre"
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    title = data.get("title", "Sans titre")
            except Exception:
                pass
        
        self._save_session_file(self.current_session_id, title, self.chat_history)
        self._load_sessions_list()

    def _save_session_file(self, filename, title, history):
        filepath = os.path.join(DATA_DIR, filename)
        data = {"title": title, "history": history}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_sessions_list(self):
        selected_filename = self.current_session_id
        self.lst_sessions.delete(0, tk.END)
        self.sessions_files = []
        
        if not os.path.exists(DATA_DIR):
            return

        files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".json")], reverse=True)
        for f in files:
            filepath = os.path.join(DATA_DIR, f)
            try:
                with open(filepath, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    self.lst_sessions.insert(tk.END, f"  {data.get('title', 'Sans titre')}")
                    self.sessions_files.append(f)
            except Exception:
                pass
        
        if selected_filename in self.sessions_files:
            idx = self.sessions_files.index(selected_filename)
            self.lst_sessions.selection_set(idx)

    def on_session_select(self, event):
        selection = self.lst_sessions.curselection()
        if not selection:
            return
        
        idx = selection[0]
        if idx >= len(self.sessions_files):
            return

        filename = self.sessions_files[idx]
        self.current_session_id = filename
        
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.chat_history = data.get("history", [])

        self.txt_chat.config(state=tk.NORMAL)
        self.txt_chat.delete("1.0", tk.END)
        for msg in self.chat_history:
            role_label = "Vous" if msg["role"] == "user" else self.current_model.get() or "Assistant"
            self.txt_chat.insert(tk.END, f"\n{role_label}:\n", "user")
            # Ne pas afficher les blocs base64 géants dans l'historique visuel
            content = msg.get('content', '')
            self.txt_chat.insert(tk.END, f"{content}\n", "assistant")
        self.txt_chat.config(state=tk.DISABLED)
        self.txt_chat.see(tk.END)

    def _append_text(self, text, tag):
        self.txt_chat.config(state=tk.NORMAL)
        self.txt_chat.insert(tk.END, text, tag)
        self.txt_chat.config(state=tk.DISABLED)
        self.txt_chat.see(tk.END)

if __name__ == "__main__":
    app = OllamaGUI()
    app.mainloop()
