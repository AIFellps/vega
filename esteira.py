"""Esteira: a fila de tarefas que a Vega roda sozinha quando você libera o computador (botão ▶ ou horário marcado 🌙).
Aparece no botão "Esteira" da página. Os dados ficam em dados/esteira/esteira.json; o registro de cada tarefa, em dados/esteira/logs/.

Dois tipos de tarefa:
  vega     um pedido para o Claude, rodado como conversa nova (`claude -p`), sem ninguém olhando
  comando  uma linha de comando qualquer

Pelo terminal (é assim que o Claude põe coisa na esteira quando você diz "coloca na fila"):
  python esteira.py vega "Resumo dos relatórios" "pedido completo..." [--detalhe "..."] [--modelo sonnet|opus|haiku]
    (o pedido pode vir de um arquivo: "@C:/caminho/pedido.txt")
  python esteira.py comando "Backup" "robocopy ..." [--pasta C:/...]
  python esteira.py listar
  python esteira.py rodar        (o trabalhador; a página e o horário marcado é que chamam)

Uma tarefa por vez, na ordem da lista. Quando a lista acaba (ou você pausa), o trabalhador sai; a que estava rodando termina antes.
Se o limite do plano do Claude acabar no meio de uma tarefa "vega", ela volta para a fila marcada com a hora do reset;
na hora, o trabalhador retoma a MESMA conversa (--resume), de onde parou. O servidor religa o trabalhador se ele cair.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import vega  # noqa: E402

PASTA = RAIZ / "dados" / "esteira"
ARQ = PASTA / "esteira.json"
LOGS = PASTA / "logs"
TRAVA = PASTA / ".trava"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOLTO = SEM_JANELA | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
RETOMAR = ("O limite de uso do Claude acabou no meio desta tarefa e já zerou. Continue exatamente de onde parou: confira o que já ficou pronto "
           "(arquivos, logs, processos ainda rodando) antes de refazer qualquer coisa, e siga até o fim do pedido original.")
LIMITE = re.compile(r"usage limit|limit reached|hit your limit|rate.?limit|out of (extra )?usage", re.I)


def aviso():
    c = vega.config()
    quem = c["usuario"] or "a pessoa"
    return (f"Seu nome é {c['nome']}. Esta tarefa veio da ESTEIRA: {quem} deixou na fila e provavelmente está longe do computador. "
            "Ninguém vai responder pergunta: decida pelo mais seguro. "
            "Não publique nada, não gaste dinheiro e não apague nada que não tenha sido você a criar. Se travar de verdade, pare e explique o motivo. "
            "Ao terminar, escreva um resumo curto (o que ficou pronto, onde está, o que precisa ser conferido), sem linhas 🔊.")


# ---------------------------------------------------------------- dados
def _travar():
    for _ in range(100):
        try:
            os.close(os.open(TRAVA, os.O_CREAT | os.O_EXCL))
            return
        except FileExistsError:
            if time.time() - TRAVA.stat().st_mtime > 10:     # trava esquecida por um processo que caiu
                TRAVA.unlink(missing_ok=True)
            time.sleep(0.05)


def _ler():
    try:
        return json.loads(ARQ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"liberada": False, "horario": "", "trabalhador": 0, "itens": []}


def mexer(funcao):
    """Lê, aplica a mudança e grava, com trava (página e trabalhador mexem no mesmo arquivo)."""
    PASTA.mkdir(parents=True, exist_ok=True)
    _travar()
    try:
        d = _ler()
        r = funcao(d)
        tmp = ARQ.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ARQ)
        return r
    finally:
        TRAVA.unlink(missing_ok=True)


def _vivo(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=SEM_JANELA)
    return str(pid) in r.stdout


def adicionar(tipo, titulo, conteudo, detalhe="", pasta="", modelo="sonnet"):
    item = {"id": uuid.uuid4().hex[:8], "tipo": tipo, "titulo": titulo, "detalhe": detalhe,
            "conteudo": conteudo, "pasta": pasta or str(vega.pasta_trabalho()), "estado": "fila", "criada": int(time.time())}
    if tipo == "vega":
        item["modelo"] = modelo
    mexer(lambda d: d["itens"].append(item))
    return item


# ---------------------------------------------------------------- para a página
def listar():
    d = _ler()
    if d.get("trabalhador") and not _vivo(d["trabalhador"]):  # o trabalhador caiu (computador desligou, por exemplo)
        def consertar(d):
            d["trabalhador"] = 0
            for i in d["itens"]:
                if i["estado"] == "rodando":
                    i.update(estado="erro", fim=int(time.time()), resumo="interrompida: o trabalhador da esteira parou no meio")
        mexer(consertar)
        d = _ler()
    for i in d["itens"]:
        i["conteudo"] = (i.get("conteudo") or "")[:700]      # o pedido inteiro pode ser longo; a página só mostra o começo
        log = LOGS / f"{i['id']}.txt"
        if i["estado"] == "rodando" and log.is_file():
            i["ultima"] = _ultima_linha(log)
    return d


def _ultima_linha(log):
    with open(log, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4000))
        linhas = [l.strip() for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
    return linhas[-1][-160:] if linhas else ""


def ver_log(iid):
    log = LOGS / f"{re.sub(r'[^a-f0-9]', '', iid)}.txt"
    return {"texto": log.read_text(encoding="utf-8", errors="replace")[-6000:] if log.is_file() else ""}


def acao(d):
    """O que a página manda: rodar, pausar, horario, subir, descer, tirar, refazer, limpar."""
    a, iid = d.get("acao"), d.get("id")

    def aplicar(e):
        itens = e["itens"]
        idx = next((k for k, i in enumerate(itens) if i["id"] == iid), None)
        if a == "rodar":
            e["liberada"] = True
        elif a == "pausar":
            e["liberada"] = False
        elif a == "horario":
            e["horario"] = (d.get("horario") or "").strip()[:5]
        elif idx is not None and a in ("subir", "descer"):
            alvo = idx - 1 if a == "subir" else idx + 1
            if 0 <= alvo < len(itens):
                itens[idx], itens[alvo] = itens[alvo], itens[idx]
        elif idx is not None and a == "tirar" and itens[idx]["estado"] != "rodando":
            itens.pop(idx)
        elif idx is not None and a == "refazer" and itens[idx]["estado"] in ("erro", "feita"):
            for k in ("inicio", "fim", "resumo", "sessao", "espera_ate", "retomar"):
                itens[idx].pop(k, None)
            itens[idx]["estado"] = "fila"
        elif a == "limpar":
            e["itens"] = [i for i in itens if i["estado"] != "feita"]
    mexer(aplicar)
    if a == "rodar":
        garantir_trabalhador()
    return listar()


def garantir_trabalhador():
    d = _ler()
    if d.get("trabalhador") and _vivo(d["trabalhador"]):
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pyw if pyw.is_file() else sys.executable), str(Path(__file__).resolve()), "rodar"],
                     cwd=str(RAIZ), creationflags=SOLTO, close_fds=True)


def vigiar_horario():
    """Roda dentro do servidor: no horário marcado, libera a esteira sozinha (uma vez por dia)."""
    def laco():
        disparado = ""
        while True:
            try:
                d = _ler()
                h, hoje = d.get("horario"), datetime.now().strftime("%Y-%m-%d")
                if h and datetime.now().strftime("%H:%M") >= h and disparado != hoje + h and d.get("disparado") != hoje + h:
                    disparado = hoje + h
                    if any(i["estado"] == "fila" for i in d["itens"]):
                        mexer(lambda e: e.update(liberada=True, disparado=hoje + h))
                        garantir_trabalhador()
                    else:
                        mexer(lambda e: e.update(disparado=hoje + h))
                if d.get("liberada") and any(i["estado"] == "fila" for i in d["itens"]) and not _vivo(d.get("trabalhador")):
                    garantir_trabalhador()                    # o trabalhador caiu (ou o servidor reiniciou) com a fila liberada: religa
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=laco, daemon=True).start()


# ---------------------------------------------------------------- o trabalhador
class LimiteAcabou(Exception):
    """O limite de uso do Claude acabou no meio da tarefa. .reset = hora do reset (segundos) ou 0 se não veio."""
    def __init__(self, reset):
        super().__init__("limite")
        self.reset = reset


def _rodar_vega(item, log):
    c = vega.config()
    cmd = [vega.claude_exe(), "-p", "--model", item.get("modelo") or "sonnet", "--output-format", "stream-json", "--verbose",
           "--permission-mode", c["modo_permissao"], "--append-system-prompt", aviso()]
    retomando = item.get("retomar") and item.get("sessao")
    if retomando:                                             # o limite acabou no meio: continua a mesma conversa
        cmd += ["--resume", item["sessao"]]
    p = subprocess.Popen(cmd, cwd=item["pasta"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VEGA="1"), creationflags=SEM_JANELA)
    p.stdin.write(RETOMAR if retomando else item["conteudo"])
    p.stdin.close()
    resumo, ok, limite = "", False, None
    with open(log, "a", encoding="utf-8") as f:
        for linha in p.stdout:
            try:
                ev = json.loads(linha)
            except ValueError:
                f.write(linha)
                continue
            if "rate_limit" in str(ev.get("type")) and (ev.get("rate_limit_info") or {}).get("status") == "rejected":
                limite = ev["rate_limit_info"].get("resetsAt") or limite or 0
            if ev.get("type") == "system" and ev.get("session_id"):
                mexer(lambda d: [i.update(sessao=ev["session_id"]) for i in d["itens"] if i["id"] == item["id"]])
            elif ev.get("type") == "assistant":
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "text":
                        f.write(b["text"].strip() + "\n")
                    elif b.get("type") == "tool_use":
                        entrada = b.get("input", {})
                        f.write(f"→ {b.get('name')}: {str(entrada.get('description') or entrada.get('command') or entrada.get('file_path') or '')[:140]}\n")
            elif ev.get("type") == "result":
                resumo, ok = (ev.get("result") or "").strip(), not ev.get("is_error")
                if not ok and limite is None and LIMITE.search(resumo):
                    m = re.search(r"\|(\d{10,13})", resumo)      # formato antigo: "...limit reached|<hora do reset>"
                    limite = int(m.group(1)) / (1000 if len(m.group(1)) > 10 else 1) if m else 0
            f.flush()
    p.wait()
    if limite is not None and not ok:
        raise LimiteAcabou(limite)
    return ok and p.returncode == 0, resumo


def _hora_do_reset(dica):
    """Quando dá para voltar: a hora que veio na mensagem ou a da janela que está cheia (5 h ou semana). Sem nenhuma: daqui a 30 min."""
    agora, horas = time.time(), []
    if dica and dica > agora:
        horas.append(dica)
    try:
        import uso
        lim = uso.limites()["limites"] or {}
        for k in ("cinco_horas", "semana"):
            j = lim.get(k) or {}
            if j.get("zera") and (j.get("usado") or 0) >= 95:
                horas.append(j["zera"])
    except Exception:
        pass
    return (max(horas) if horas else agora + 1800) + 120         # 2 min de folga depois do reset


def _rodar_comando(item, log):
    p = subprocess.Popen(item["conteudo"], shell=True, cwd=item["pasta"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=SEM_JANELA)
    with open(log, "a", encoding="utf-8") as f:
        for linha in p.stdout:                                # o cmd do Windows escreve em cp850; o Python, em utf-8
            try:
                f.write(linha.decode("utf-8"))
            except UnicodeDecodeError:
                f.write(linha.decode("cp850", "replace"))
            f.flush()
    p.wait()
    return p.returncode == 0, _ultima_linha(log)


def trabalhar():
    if not mexer(lambda d: (not d.get("trabalhador") or not _vivo(d["trabalhador"])) and (d.update(trabalhador=os.getpid()) or True)):
        return                                                # já tem outro trabalhador rodando
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            def pegar(d):
                if not d.get("liberada"):
                    return None
                prox = next((i for i in d["itens"] if i["estado"] == "fila"), None)
                if prox and prox.get("espera_ate", 0) > time.time():
                    return {"esperar": prox["espera_ate"] - time.time()}
                if prox:
                    prox.pop("espera_ate", None)
                    prox.update(estado="rodando", inicio=prox.get("inicio") or int(time.time()))
                return dict(prox) if prox else None
            item = mexer(pegar)
            if not item:
                break
            if "esperar" in item:                             # esperando o limite do Claude zerar
                time.sleep(min(item["esperar"], 300))
                continue
            log = LOGS / f"{item['id']}.txt"
            if item.get("retomar"):
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now():%d/%m %H:%M}] o limite zerou: retomando de onde parou\n")
            else:
                log.write_text(f"[{datetime.now():%d/%m %H:%M}] começou: {item['titulo']}\n", encoding="utf-8")
            try:
                ok, resumo = (_rodar_vega if item["tipo"] == "vega" else _rodar_comando)(item, log)
            except LimiteAcabou as e:
                volta = _hora_do_reset(e.reset)
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now():%d/%m %H:%M}] o limite do Claude acabou; a esteira volta sozinha às {datetime.fromtimestamp(volta):%H:%M} e continua de onde parou\n")
                mexer(lambda d: [i.update(estado="fila", espera_ate=volta, retomar=True) for i in d["itens"] if i["id"] == item["id"]])
                continue
            except Exception as e:
                ok, resumo = False, f"erro ao rodar: {e}"
            mexer(lambda d: [i.update(estado="feita" if ok else "erro", fim=int(time.time()), resumo=resumo[:4000])
                             for i in d["itens"] if i["id"] == item["id"]])
    finally:
        def soltar(d):
            d["trabalhador"] = 0
            if not any(i["estado"] == "fila" for i in d["itens"]):
                d["liberada"] = False                         # acabou a lista: volta a esperar o próximo "liberar"
        mexer(soltar)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("o_que", choices=["vega", "comando", "listar", "rodar"])
    a.add_argument("titulo", nargs="?")
    a.add_argument("conteudo", nargs="?")
    a.add_argument("--detalhe", default="")
    a.add_argument("--pasta", default="")
    a.add_argument("--modelo", default="sonnet", choices=["sonnet", "opus", "haiku"])
    x = a.parse_args()
    if x.o_que == "rodar":
        trabalhar()
    elif x.o_que == "listar":
        for i in _ler()["itens"]:
            print(f"{i['estado']:8} {i['id']}  {i['titulo']}")
    else:
        if not x.titulo or not x.conteudo:
            a.error("faltou o título ou o conteúdo")
        conteudo = x.conteudo
        if conteudo.startswith("@") and Path(conteudo[1:]).is_file():   # @arquivo: pedido longo guardado num arquivo
            conteudo = Path(conteudo[1:]).read_text(encoding="utf-8")
        print("na esteira:", adicionar(x.o_que, x.titulo, conteudo, x.detalhe, x.pasta, x.modelo)["id"])
