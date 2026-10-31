"""Abre a Vega: liga o servidor (se estiver desligado) e abre a página numa janela própria do Edge.

O Edge usa um perfil só dele (dados/edge-perfil) para valer a opção desta janela de falar sem precisar de um clique
antes (autoplay). É no Edge que as vozes naturais (Online) e o ditado em português funcionam.
O atalho "Vega" da área de trabalho (criado pelo instalar.bat) aponta para este arquivo.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SEM_JANELA = 0x08000000


def porta():
    try:
        return int(json.loads((RAIZ / "config.json").read_text(encoding="utf-8-sig")).get("porta") or 8777)
    except Exception:
        return 8777


URL = f"http://127.0.0.1:{porta()}"


def ligado():
    try:
        urllib.request.urlopen(URL + "/api/vega/vivo", timeout=2).read()
        return True
    except Exception:
        return False


def edge():
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if base and exe.exists():
            return str(exe)
    return None


if not ligado():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    log = open(RAIZ / "dados" / "servidor.log", "a", encoding="utf-8") if (RAIZ / "dados").is_dir() else subprocess.DEVNULL
    subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), "servidor.py"], cwd=RAIZ, creationflags=SEM_JANELA,
                     stdout=log, stderr=log)
    for _ in range(60):
        time.sleep(0.5)
        if ligado():
            break

exe = edge()
if exe:
    perfil = RAIZ / "dados" / "edge-perfil"
    perfil.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--app={URL}/", f"--user-data-dir={perfil}", "--autoplay-policy=no-user-gesture-required",
                      "--window-size=1500,950", "--no-first-run", "--no-default-browser-check"])
else:
    webbrowser.open(URL + "/")
