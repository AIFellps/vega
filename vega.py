"""Vega: conversar com o Claude Code por uma página própria (web/index.html), com rosto holográfico.

É o MESMO Claude Code do terminal ou do VS Code (mesmas conversas, memória, ferramentas e o seu plano): a página só troca
a janela. As conversas são os arquivos ~/.claude/projects/<pasta>/<id>.jsonl, então dá para começar num e seguir no outro.

  conversas()              lista para a lateral (título, quando, se está aberta em outro lugar agora)
  historico(id)            as mensagens já trocadas (texto; ferramentas viram etiquetas curtas)
  enviar(id, texto, anexos) roda `claude -p --resume id` em segundo plano; devolve um trabalho para acompanhar ao vivo
  eventos(trabalho, desde) o que chegou desde o índice `desde` (texto em pedaços, ferramentas, custo, fim)
  parar(trabalho)          interrompe
  guardar_anexo(nome, b64) salva o arquivo arrastado e devolve o caminho

A voz: a página fala em voz alta as linhas que começam com 🔊 e sincroniza o rosto com elas. O processo leva VEGA=1,
para ganchos de voz que você tenha no Claude Code poderem ficar quietos e não falar em dobro.
"""
import base64
import glob
import json
import os
import re
import subprocess
import threading
import time
import uuid
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DADOS = RAIZ / "dados"
ANEXOS = DADOS / "anexos"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PADRAO = {"nome": "Vega", "artigo": "a", "usuario": "", "saudacao": "Às suas ordens.", "idioma": "pt-BR", "voz": "Thalita",
          "personalidade": "Calma, direta e prestativa, com um humor seco e leve. Respostas curtas, o essencial primeiro.",
          "cores": {"espera": "#2ad8ff", "pensando": "#8a5cff", "falando": "#ff9a3c"},
          "pasta_trabalho": "", "modo_permissao": "auto", "chrome": True, "porta": 8777}


def config():
    """config.json da pasta da Vega por cima do padrão (o que faltar lá vale o padrão)."""
    c = json.loads(json.dumps(PADRAO))
    arq = RAIZ / "config.json"
    if arq.exists():
        dados = json.loads(arq.read_text(encoding="utf-8-sig"))
        c.update({k: v for k, v in dados.items() if not k.startswith("_") and k != "cores"})
        c["cores"].update(dados.get("cores") or {})
    return c


def pasta_trabalho():
    """Onde o Claude trabalha (e de onde vêm as conversas). Vazio = a pasta Documentos."""
    p = config()["pasta_trabalho"]
    pasta = Path(os.path.expandvars(os.path.expanduser(p))) if p else Path.home() / "Documents"
    return pasta if pasta.is_dir() else Path.home()


def projeto():
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(pasta_trabalho()))


def aviso():
    """O que o Claude fica sabendo sobre esta janela (vai junto como prompt de sistema)."""
    c = config()
    quem = f"com {c['usuario']}" if c["usuario"] else "com o seu usuário"
    return (f"Seu nome é {c['nome']}. Você está falando {quem} pela sua página própria, com um rosto holográfico 3D, não pelo terminal. "
            f"Personalidade: {c['personalidade']} "
            "Links de arquivo não são clicáveis aqui: cite o caminho. A página fala em voz alta as linhas que começam com 🔊 e anima "
            "o rosto com elas: comece a resposta com uma linha '🔊 ...' curta dizendo o que vai fazer e termine com outra resumindo o "
            "resultado, em linguagem falada (sem código, caminhos ou markdown nessas linhas). Antes de cada etapa demorada, uma linha 🔊 avisando. "
            "Anexos chegam como caminhos de arquivo: abra com Read.")
_trabalhos = {}
_titulos = {}                                                 # caminho -> (mtime, título)
_nossas = {}                                                  # conversa -> quando a Vega terminou de mexer nela
_ETIQUETAS = re.compile(r"<(system-reminder|ide_opened_file|ide_selection|command-[a-z]+|local-command-[a-z]+)>.*?</\1>", re.S)


def claude_exe():
    """O Claude Code instalado: no PATH, no instalador nativo (~/.local/bin) ou dentro da extensão do VS Code."""
    achado = shutil.which("claude")
    if achado:
        return achado
    nativo = Path.home() / ".local" / "bin" / "claude.exe"
    if nativo.exists():
        return str(nativo)
    achados = glob.glob(os.path.expanduser(r"~\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe"))
    if achados:
        return max(achados, key=os.path.getmtime)
    raise RuntimeError("não achei o Claude Code. Instale em https://claude.com/claude-code e rode `claude` uma vez para entrar na conta")


# ---------------------------------------------------------------- leitura das conversas
def _limpar(texto):
    return _ETIQUETAS.sub("", texto).strip()


def _texto_do_usuario(conteudo):
    """Só o que ele digitou (e imagens). Devolve None se a entrada é resultado de ferramenta."""
    if isinstance(conteudo, str):
        return _limpar(conteudo), 0
    partes, imagens = [], 0
    for c in conteudo or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_result":
            return None, 0
        if c.get("type") == "text":
            partes.append(c.get("text", ""))
        elif c.get("type") == "image":
            imagens += 1
    return _limpar("\n".join(partes)), imagens


def _linhas(arq, ultimos_bytes=None):
    with open(arq, "rb") as f:
        if ultimos_bytes:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - ultimos_bytes))
            f.readline()                                      # descarta a linha cortada no meio
        for linha in f:
            try:
                yield json.loads(linha)
            except ValueError:
                continue


def _titulo(arq):
    mt = arq.stat().st_mtime
    if _titulos.get(arq, (0,))[0] == mt:
        return _titulos[arq][1]
    titulo = ""
    with open(arq, "rb") as f:
        for n, linha in enumerate(f):
            if n > 400:
                break
            try:
                e = json.loads(linha)
            except ValueError:
                continue
            if e.get("type") in ("summary", "custom-title", "ai-title") and (e.get("summary") or e.get("title") or e.get("customTitle") or e.get("aiTitle")):
                titulo = e.get("customTitle") or e.get("title") or e.get("aiTitle") or e.get("summary")
                break
            if e.get("type") == "user" and not e.get("isMeta") and not titulo:
                txt, _ = _texto_do_usuario((e.get("message") or {}).get("content"))
                if txt and not txt.startswith(("This session is being continued", "Caveat:", "<")):
                    titulo = txt.splitlines()[0][:80]
    _titulos[arq] = (mt, titulo or "Conversa sem título")
    return _titulos[arq][1]


def conversas(limite=60):
    pasta = projeto()
    if not pasta.exists():
        return []
    arqs = sorted(pasta.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limite]
    agora = time.time()
    em_curso = {t["sessao"] for t in _trabalhos.values() if not t["fim"]}
    fomos_nos = lambda sid, mt: sid in em_curso or mt <= _nossas.get(sid, 0) + 10      # quem mexeu por último foi a própria Vega
    saida = []
    for a in arqs:
        if a.stat().st_size < 200:
            continue
        mt = a.stat().st_mtime
        saida.append({"id": a.stem, "titulo": _titulo(a), "quando": time.strftime("%d/%m %H:%M", time.localtime(mt)),
                      "aberta_fora": (agora - mt) < 90 and not fomos_nos(a.stem, mt)})
    return saida


def _resumo_ferramenta(c):
    nome, ent = c.get("name", ""), c.get("input") or {}
    detalhe = ent.get("description") or ent.get("file_path") or ent.get("pattern") or ent.get("url") or ent.get("query") or ent.get("command") or ""
    return {"nome": nome.replace("mcp__claude-in-chrome__", "chrome·").replace("mcp__", ""), "detalhe": str(detalhe)[:90]}


def historico(sessao, limite=120):
    arq = projeto() / f"{re.sub(r'[^A-Za-z0-9-]', '', sessao)}.jsonl"
    if not arq.exists():
        raise RuntimeError("conversa não encontrada")
    msgs = []
    for e in _linhas(arq, ultimos_bytes=6_000_000):
        tipo, msg = e.get("type"), e.get("message") or {}
        if tipo == "user" and not e.get("isMeta") and not e.get("isCompactSummary"):
            txt, imagens = _texto_do_usuario(msg.get("content"))
            if txt is None or (not txt and not imagens):
                continue
            msgs.append({"de": "voce", "texto": txt, "imagens": imagens})
        elif tipo == "assistant":
            if not msgs or msgs[-1]["de"] != "vega":
                msgs.append({"de": "vega", "texto": "", "ferramentas": []})
            for c in msg.get("content") or []:
                if c.get("type") == "text" and c.get("text", "").strip():
                    msgs[-1]["texto"] += ("\n\n" if msgs[-1]["texto"] else "") + c["text"].strip()
                elif c.get("type") == "tool_use":
                    msgs[-1]["ferramentas"].append(_resumo_ferramenta(c))
    return [m for m in msgs if m["de"] == "voce" or m["texto"] or m["ferramentas"]][-limite:]


# ---------------------------------------------------------------- envio
def guardar_anexo(nome, b64):
    ANEXOS.mkdir(parents=True, exist_ok=True)
    seguro = re.sub(r"[^A-Za-z0-9._-]", "-", Path(nome).name)[-80:] or "anexo"
    arq = ANEXOS / f"{time.strftime('%Y%m%d-%H%M%S')}-{seguro}"
    arq.write_bytes(base64.b64decode(b64.split(",", 1)[-1]))
    return {"caminho": str(arq), "nome": Path(nome).name}


TELAS = DADOS / "tela"


def _imagens_de_ferramenta(e):
    """As imagens que voltaram de ferramentas (ex.: print do Chrome) numa entrada "user" do stream-json."""
    achadas = []
    for c in (e.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_result":
            for p in c.get("content") if isinstance(c.get("content"), list) else []:
                if not isinstance(p, dict):
                    continue
                fonte = p.get("source") or {}
                if p.get("type") == "image" and fonte.get("data"):
                    achadas.append(fonte)
    return achadas


def _guardar_tela(tid, fonte):
    TELAS.mkdir(parents=True, exist_ok=True)
    ext = {"image/png": "png", "image/webp": "webp"}.get(fonte.get("media_type"), "jpg")
    arq = TELAS / f"{time.strftime('%Y%m%d-%H%M%S')}-{tid}-{uuid.uuid4().hex[:6]}.{ext}"
    arq.write_bytes(base64.b64decode(fonte["data"]))
    for velho in sorted(TELAS.glob("*.*"))[:-60]:                     # guarda só as 60 mais recentes
        velho.unlink(missing_ok=True)
    return arq.name


def arquivo_tela(nome):
    arq = (TELAS / Path(nome).name).resolve()
    if arq.parent != TELAS.resolve() or not arq.is_file():
        raise RuntimeError("tela não encontrada")
    return arq


def arquivo_anexo(nome):
    arq = (ANEXOS / Path(nome).name).resolve()
    if arq.parent != ANEXOS.resolve() or not arq.is_file():
        raise RuntimeError("anexo não encontrado")
    return arq


def enviar(sessao, texto, anexos=None):
    texto = (texto or "").strip()
    anexos = [a for a in (anexos or []) if Path(a).is_file()]
    if not texto and not anexos:
        raise RuntimeError("mensagem vazia")
    if sessao and any(t["sessao"] == sessao and not t["fim"] for t in _trabalhos.values()):
        raise RuntimeError("ainda estou respondendo a mensagem anterior nesta conversa")
    if anexos:
        texto += "\n\n[Anexos, abra com Read:]\n" + "\n".join(anexos)
    c = config()
    cmd = [claude_exe(), "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--permission-mode", c["modo_permissao"], "--append-system-prompt", aviso()]
    if c["chrome"]:
        cmd.append("--chrome")                                        # a Vega controla o Chrome pela extensão Claude in Chrome
    if sessao:
        cmd += ["--resume", sessao]
    amb = dict(os.environ, VEGA="1")
    proc = subprocess.Popen(cmd, cwd=pasta_trabalho(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=amb, creationflags=SEM_JANELA)
    tid = uuid.uuid4().hex[:12]
    t = {"proc": proc, "eventos": [], "fim": False, "sessao": sessao or "", "cond": threading.Condition(), "inicio": time.time()}
    _trabalhos[tid] = t
    proc.stdin.write(texto)
    proc.stdin.close()
    threading.Thread(target=_ler, args=(tid,), daemon=True).start()
    return {"trabalho": tid}


def _por(t, ev):
    with t["cond"]:
        t["eventos"].append(ev)
        t["cond"].notify_all()


def _ler(tid):
    t = _trabalhos[tid]
    proc = t["proc"]
    try:
        for linha in proc.stdout:
            try:
                e = json.loads(linha)
            except ValueError:
                continue
            tipo = e.get("type")
            if tipo == "system" and e.get("subtype") == "init":
                t["sessao"] = e.get("session_id", t["sessao"])
                _por(t, {"t": "sessao", "id": t["sessao"]})
            elif tipo == "stream_event":
                ev = e.get("event") or {}
                if ev.get("type") == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta" and not e.get("parent_tool_use_id"):
                    _por(t, {"t": "texto", "d": ev["delta"]["text"]})
                elif ev.get("type") == "message_start" and not e.get("parent_tool_use_id"):
                    _por(t, {"t": "bloco"})
            elif tipo == "user" and not e.get("parent_tool_use_id"):
                for img in _imagens_de_ferramenta(e):                 # print que eu tirei do navegador: vira a janelinha "o que a Vega vê"
                    _por(t, {"t": "tela", "arq": _guardar_tela(tid, img)})
            elif tipo == "assistant" and not e.get("parent_tool_use_id"):
                for c in (e.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        _por(t, dict(_resumo_ferramenta(c), t="ferramenta"))
            elif tipo == "result":
                u = e.get("usage") or {}
                _por(t, {"t": "resultado", "custo": e.get("total_cost_usd"), "erro": bool(e.get("is_error")),
                         "tokens": sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "output_tokens")),
                         "duracao": round(time.time() - t["inicio"])})
                if e.get("is_error"):
                    _por(t, {"t": "erro", "msg": str(e.get("result", "erro"))[:400]})
        proc.wait()
        if proc.returncode not in (0, None) and not any(ev["t"] == "resultado" for ev in t["eventos"]):
            _por(t, {"t": "erro", "msg": (proc.stderr.read() or "o Claude parou sem resposta").strip()[-400:]})
    except Exception as erro:
        _por(t, {"t": "erro", "msg": str(erro)[:300]})
    finally:
        _nossas[t["sessao"]] = time.time()
        t["fim"] = True
        _por(t, {"t": "fim", "sessao": t["sessao"]})


def eventos(tid, desde=0, espera=25):
    """Long polling: devolve o que chegou depois de `desde`; sem nada novo, espera até `espera` segundos."""
    t = _trabalhos.get(tid)
    if not t:
        raise RuntimeError("trabalho não encontrado")
    with t["cond"]:
        if len(t["eventos"]) <= desde and not t["fim"]:
            t["cond"].wait(espera)
        return {"eventos": t["eventos"][desde:], "fim": t["fim"], "proximo": len(t["eventos"])}


def parar(tid):
    t = _trabalhos.get(tid)
    if t and not t["fim"]:
        subprocess.run(["taskkill", "/PID", str(t["proc"].pid), "/T", "/F"], capture_output=True, creationflags=SEM_JANELA)
        _por(t, {"t": "erro", "msg": "interrompido"})
    return {"ok": True}
