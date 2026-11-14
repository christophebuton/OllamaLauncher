#!/usr/bin/env python3
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox


def run_script(script_name):
  try:
    subprocess.Popen([sys.executable, script_name])
  except Exception as e:
    messagebox.showerror('Erreur', f'Impossible de lancer {script_name} :\n{e}')


root = tk.Tk()
root.title('Ollama Launcher')
root.geometry('320x420')
root.resizable(False, False)

# Chargement de l'icône si le fichier existe
if os.path.exists('ollama-launcher.png'):
  try:
    icon_img = tk.PhotoImage(file='ollama-launcher.png')
    root.iconphoto(True, icon_img)
    # Affichage de l'icône dans l'interface
    tk.Label(root, image=icon_img).pack(pady=10)
  except Exception:
    pass

tk.Button(
    root,
    text='Installation',
    command=lambda: run_script('ollama-install.py'),
    width=24,
    height=2,
    font=('Helvetica', 12, 'bold'),
).pack(pady=5)

tk.Button(
    root,
    text='Interface graphique',
    command=lambda: run_script('ollama-gui.py'),
    width=24,
    height=2,
    font=('Helvetica', 12, 'bold'),
).pack(pady=5)

root.mainloop()
