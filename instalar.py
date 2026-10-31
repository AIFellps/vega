"""Instalador da Vega: confere o que precisa, cria o config.json e o atalho "Vega" na área de trabalho.

Não baixa nada e não mexe em nada fora desta pasta (além do atalho). Pode rodar de novo quando quiser.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
OK, FALTA = "  [ok]", "  [!!]"
problemas = 0


def linha(ok, texto, dica=""):
    global problemas
    print(f"{OK if ok else FALTA} {texto}")
    if not ok:
        problemas += 1
        if dica:
            print(f"       {dica}")


print("\n  Instalando a Vega\n  -----------------")

linha(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Precisa do Python 3.10 ou mais novo: https://www.python.org/downloads/")

sys.path.insert(0, str(RAIZ))
import vega  # noqa: E402

try:
    exe = vega.claude_exe()
    versao = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    linha(True, f"Claude Code {versao}")
except Exception as e:
    linha(False, "Claude Code", str(e))

edge = any((Path(b) / "Microsoft" / "Edge" / "Application" / "msedge.exe").exists()
           for b in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")) if b)
linha(edge, "Microsoft Edge", "Sem o Edge a Vega abre no navegador padrão, mas a voz natural e o ditado podem não funcionar.")

(RAIZ / "dados").mkdir(exist_ok=True)
config = RAIZ / "config.json"
if not config.exists():
    shutil.copy(RAIZ / "config.exemplo.json", config)
    linha(True, "config.json criado (nome, voz, cores: edite à vontade)")
else:
    linha(True, "config.json já existe (mantido)")

pythonw = Path(sys.executable).with_name("pythonw.exe")
alvo = pythonw if pythonw.exists() else Path(sys.executable)
ps = (
    "$d=[Environment]::GetFolderPath('Desktop');"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Vega.lnk'));"
    f"$s.TargetPath='{alvo}';$s.Arguments='\"{RAIZ / 'Vega.pyw'}\"';$s.WorkingDirectory='{RAIZ}';"
    f"$s.IconLocation='{RAIZ / 'web' / 'icones' / 'vega.ico'}';$s.Description='Vega';$s.Save()"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
linha(r.returncode == 0, "Atalho \"Vega\" na área de trabalho", r.stderr.strip()[:300])

print()
if problemas:
    print("  Faltou alguma coisa acima. Resolva e rode o instalar.bat de novo.")
else:
    print("  Pronto! Abra pelo atalho \"Vega\" na área de trabalho.")
    print("  Primeira vez com o Claude Code? Abra um terminal, digite  claude  e entre na sua conta antes.")
print()
