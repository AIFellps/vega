"""Vega: conversar com o Claude Code por uma página própria (web/index.html), com rosto holográfico.

É o MESMO Claude Code do terminal ou do VS Code (mesmas conversas, memória, ferramentas e o seu plano): a página só troca
a janela. As conversas são os arquivos ~/.claude/projects/<pasta>/<id>.jsonl, então dá para começar num e seguir no outro.

  conversas()              lista para a lateral (título, quando, se está aberta em outro lugar agora)
  historico(id)            as mensagens já trocadas (texto; ferramentas viram etiquetas curtas)
  enviar(id, texto, anexos) roda `claude -p --resume id` em segundo plano; devolve um trabalho para acompanhar ao vivo
  eventos(trabalho, desde) o que chegou desde o índice `desde` (texto em pedaços, ferramentas, agentes, custo, fim)
  parar(trabalho)          interrompe
  guardar_anexo(nome, b64) salva o arquivo arrastado e devolve o caminho
  contexto(id)             tamanho atual da conversa (quantos tokens cada mensagem nova carrega)
  segundo_plano()          tarefas longas registradas com segundo_plano.py (painel da direita)

Várias conversas podem responder ao mesmo tempo (uma resposta por conversa). O modelo escolhido ao criar a conversa
fica guardado em dados/modelos.json, porque o --resume não guarda.

A voz: a página fala em voz alta as linhas que começam com 🔊 e sincroniza o rosto com elas. O processo leva VEGA=1,
para ganchos de voz que você tenha no Claude Code poderem ficar quietos e não falar em dobro.
"""
import base64
import glob
import sys
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
MODELOS = DADOS / "modelos.json"
MODELOS_VALIDOS = ("opus", "sonnet", "haiku")
REGISTRO = DADOS / "segundo_plano"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PADRAO = {"nome": "Vega", "artigo": "a", "usuario": "", "saudacao": "Às suas ordens.", "idioma": "pt-BR", "voz": "Thalita",
          "personalidade": "Calma, direta e prestativa, com um humor seco e leve. Respostas curtas, o essencial primeiro.",
          "cores": {"espera": "#2ad8ff", "pensando": "#8a5cff", "falando": "#ff9a3c"},
          "pasta_trabalho": "", "modo_permissao": "auto", "chrome": True, "mostrar_limites": True, "porta": 8777}


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
    py = Path(sys.executable).with_name("python.exe")
    py = f'"{py if py.exists() else sys.executable}"'
    return (f"Seu nome é {c['nome']}. Você está falando {quem} pela sua página própria, com um rosto holográfico 3D, não pelo terminal. "
            f"Personalidade: {c['personalidade']} "
            "Links de arquivo não são clicáveis aqui: cite o caminho. A página fala em voz alta as linhas que começam com 🔊 e anima "
            "o rosto com elas: comece a resposta com uma linha '🔊 ...' curta dizendo o que vai fazer e termine com outra resumindo o "
            "resultado, em linguagem falada (sem código, caminhos ou markdown nessas linhas). Antes de cada etapa demorada, uma linha 🔊 avisando. "
            "Anexos chegam como caminhos de arquivo: abra com Read. "
            "Em tarefa longa (vários passos ou agentes), escreva logo no começo uma linha '📊 etapa · etapa · etapa' (3 a 6 etapas curtas) "
            "e, ao começar cada etapa seguinte, uma linha só '📊 N' (o número dela). A página vira isso numa barra de progresso e esconde essas linhas do chat. "
            f"Processo longo que você deixar rodando sozinho em segundo plano: registre com {py} \"{RAIZ / 'segundo_plano.py'}\" \"nome\" "
            "--busca <trecho da linha de comando> [--log arquivo --etapas a,b,c], e ele aparece no painel 'Em segundo plano' até o processo acabar. "
            "Quando pedirem para 'colocar na fila' (ou para não ocupar o computador agora), NÃO rode: ponha na esteira, que aparece no botão Esteira "
            f"e roda quando liberarem: {py} \"{RAIZ / 'esteira.py'}\" vega \"título curto\" \"@arquivo-com-o-pedido.txt\" [--detalhe \"...\"] [--modelo sonnet|opus|haiku]. "
            "O pedido roda depois numa conversa nova, sem ninguém olhando: escreva no arquivo tudo o que ela precisa saber "
            f"(guarde em \"{DADOS / 'esteira' / 'pedidos'}\"). Para um comando simples: esteira.py comando \"título\" \"linha de comando\" [--pasta <pasta>].")
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


def _modelos():
    try:
        return json.loads(MODELOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_modelo(sessao, modelo):
    m = _modelos()
    if sessao and m.get(sessao) != modelo:
        m[sessao] = modelo
        MODELOS.parent.mkdir(parents=True, exist_ok=True)
        MODELOS.write_text(json.dumps(m, indent=1), encoding="utf-8")


def conversas(limite=60):
    pasta = projeto()
    if not pasta.exists():
        return []
    arqs = sorted(pasta.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limite]
    mods = _modelos()
    agora = time.time()
    em_curso = {t["sessao"] for t in _trabalhos.values() if not t["fim"]}
    fomos_nos = lambda sid, mt: sid in em_curso or mt <= _nossas.get(sid, 0) + 10      # quem mexeu por último foi a própria Vega
    saida = []
    for a in arqs:
        if a.stat().st_size < 200:
            continue
        mt = a.stat().st_mtime
        saida.append({"id": a.stem, "titulo": _titulo(a), "quando": time.strftime("%d/%m %H:%M", time.localtime(mt)),
                      "aberta_fora": (agora - mt) < 90 and not fomos_nos(a.stem, mt), "modelo": mods.get(a.stem, "")})
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


def contexto(sessao):
    """Tamanho atual da conversa: quantos tokens cada nova mensagem carrega (lido do arquivo, então sobrevive a reinício e F5)."""
    arq = projeto() / f"{re.sub(r'[^A-Za-z0-9-]', '', sessao)}.jsonl"
    if not arq.exists():
        return {"tokens": 0}
    for janela in (3_000_000, 30_000_000):                   # imagens deixam linhas enormes: se o fim só tiver isso, lê mais
        ultimo = None
        for e in _linhas(arq, ultimos_bytes=janela):
            u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" and not e.get("isSidechain") else None
            if u:
                ultimo = u
        if ultimo:
            return {"tokens": sum(ultimo.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))}
    return {"tokens": 0}


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


def enviar(sessao, texto, anexos=None, modelo=None):
    texto = (texto or "").strip()
    modelo = modelo if modelo in MODELOS_VALIDOS else (_modelos().get(sessao) if sessao else None)   # sem escolha: o padrão do Claude
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
    if modelo:
        cmd += ["--model", modelo]
    amb = dict(os.environ, VEGA="1")
    proc = subprocess.Popen(cmd, cwd=pasta_trabalho(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=amb, creationflags=SEM_JANELA)
    tid = uuid.uuid4().hex[:12]
    t = {"proc": proc, "eventos": [], "fim": False, "sessao": sessao or "", "cond": threading.Condition(), "inicio": time.time(),
         "agentes": {}, "modelo": modelo}
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
                if t.get("modelo"):
                    _guardar_modelo(t["sessao"], t["modelo"])
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
                _fim_de_agentes(t, e)
            elif tipo == "assistant":
                pai = e.get("parent_tool_use_id")                     # preenchido = é um agente (subagente) trabalhando
                for c in (e.get("message") or {}).get("content") or []:
                    if c.get("type") != "tool_use":
                        continue
                    if pai:
                        _por(t, dict(_resumo_ferramenta(c), t="passo", pai=pai))
                        continue
                    _por(t, dict(_resumo_ferramenta(c), t="ferramenta"))
                    if c.get("name") in ("Agent", "Task"):
                        ent = c.get("input") or {}
                        t["agentes"][c.get("id")] = "rodando"
                        _por(t, {"t": "agente", "id": c.get("id"), "tipo": ent.get("subagent_type") or "general-purpose",
                                 "desc": str(ent.get("description") or "")[:90]})
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


def _fim_de_agentes(t, e):
    """Fecha o cartão do agente na barra de progresso quando o resultado dele volta. Agente em segundo plano devolve
    na hora só um "começou"; esse fica aberto até chegar o aviso de tarefa concluída (ou até a resposta acabar)."""
    abertos = t["agentes"]
    conteudo = (e.get("message") or {}).get("content")
    partes = conteudo if isinstance(conteudo, list) else []
    for c in partes:
        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in abertos:
            aid = c["tool_use_id"]
            if not c.get("is_error") and re.search(r"launched|running in (the )?background|async agent", json.dumps(c.get("content")), re.I):
                abertos[aid] = "fundo"
                continue
            del abertos[aid]
            _por(t, {"t": "agente_fim", "id": aid, "erro": bool(c.get("is_error"))})
    texto = conteudo if isinstance(conteudo, str) else " ".join(c.get("text", "") for c in partes if isinstance(c, dict) and c.get("type") == "text")
    if "task-notification" in texto:
        fundo = [a for a, v in abertos.items() if v == "fundo"]
        for aid in [a for a in fundo if a in texto] or fundo[:1]:
            del abertos[aid]
            _por(t, {"t": "agente_fim", "id": aid, "erro": False})


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


# ---------------------------------------------------------------- em segundo plano
# O que o Claude deixou rodando sozinho e registrou com segundo_plano.py. O cartão some quando nenhum processo tem mais
# o trecho de --busca na linha de comando (ou depois de um dia). A página pergunta a cada poucos segundos; não gasta token.
_procs = {"quando": 0.0, "linhas": []}


def _linhas_de_comando():
    if time.time() - _procs["quando"] > 4:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=SEM_JANELA)
        _procs.update(quando=time.time(), linhas=[l for l in r.stdout.splitlines() if l.strip()])
    return _procs["linhas"]


def segundo_plano():
    if not REGISTRO.is_dir():
        return []
    saida, linhas = [], None
    for arq in REGISTRO.glob("*.json"):
        try:
            r = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        busca = r.get("busca")
        if busca and linhas is None:
            linhas = _linhas_de_comando()
        if (busca and not any(busca in l for l in linhas)) or time.time() - r.get("inicio", 0) > 86400:
            arq.unlink(missing_ok=True)                       # o processo acabou (ou o registro tem mais de um dia)
            continue
        etapas, atual = r.get("etapas") or [], None
        if etapas and r.get("log") and Path(r["log"]).is_file():
            with open(r["log"], "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 20000))
                texto = f.read().decode("utf-8", "replace").lower()
            achadas = [i for i, e in enumerate(etapas) if e.lower() in texto]
            atual = max(achadas) if achadas else 0
        saida.append({"id": "r-" + arq.stem, "nome": r.get("nome", "Tarefa"), "detalhe": r.get("detalhe", ""),
                      "inicio": r.get("inicio"), "etapas": etapas, "atual": atual})
    return saida
