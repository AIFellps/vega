"""Servidor da Vega: entrega a página (web/) e as rotas /api/vega/* (vega.py). Só a biblioteca padrão do Python.

Ouve só neste computador (127.0.0.1). Como do outro lado está um Claude Code com permissão para agir, ele recusa
pedidos que não venham da própria página: o Host tem que ser o local e todo POST precisa do cabeçalho X-Vega
(um site qualquer aberto no navegador não consegue mandar esse cabeçalho sem a permissão do servidor).
"""
import json
import re
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import esteira
import uso
import vega

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
PORTA = int(vega.config().get("porta") or 8777)
HOSTS = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}


class Pedido(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".glb": "model/gltf-binary",
                      ".webmanifest": "application/manifest+json"}

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _mandar_arquivo(self, arq):
        tipo = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(arq.suffix.lower(), "application/octet-stream")
        corpo = arq.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _local(self):
        return self.headers.get("Host", "") in HOSTS

    def do_GET(self):
        if not self._local():
            return self._json({"erro": "só neste computador"}, 403)
        url = urllib.parse.urlparse(self.path)
        if not url.path.startswith("/api/vega/"):
            return super().do_GET()
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            acao = url.path[10:]
            if acao == "config":
                c = vega.config()
                return self._json({k: c[k] for k in ("nome", "artigo", "saudacao", "idioma", "voz", "cores", "mostrar_limites")})
            if acao == "vivo":
                return self._json({"ok": True})
            if acao == "conversas":
                return self._json(vega.conversas())
            if acao == "historico":
                return self._json(vega.historico(qs["id"]))
            if acao == "eventos":
                return self._json(vega.eventos(qs["t"], int(qs.get("desde", 0))))
            if acao == "anexo":
                return self._mandar_arquivo(vega.arquivo_anexo(qs["n"]))
            if acao == "tela":
                return self._mandar_arquivo(vega.arquivo_tela(qs["n"]))
            if acao == "contexto":
                return self._json(vega.contexto(qs["id"]))
            if acao == "uso":                                   # limite do plano (5 h e semana); uso.py
                return self._json(uso.limites() if vega.config()["mostrar_limites"] else {"limites": None})
            if acao == "segundo-plano":
                return self._json(vega.segundo_plano())
            if acao == "esteira":
                return self._json(esteira.listar())
            if acao == "esteira/log":
                return self._json(esteira.ver_log(qs["id"]))
        except (KeyError, ValueError, RuntimeError) as e:
            return self._json({"erro": str(e)}, 400)
        return self._json({"erro": "não conheço"}, 404)

    def do_POST(self):
        if not self._local() or self.headers.get("X-Vega") != "1":
            return self._json({"erro": "só a página da Vega pode mandar"}, 403)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            acao = self.path[10:] if self.path.startswith("/api/vega/") else ""
            if acao == "enviar":
                return self._json(vega.enviar(d.get("sessao") or None, d.get("texto", ""), d.get("anexos", []), d.get("modelo")))
            if acao == "esteira":
                return self._json(esteira.acao(d))
            if acao == "parar":
                return self._json(vega.parar(d["trabalho"]))
            if acao == "anexo":
                return self._json(vega.guardar_anexo(d["nome"], d["dados"]))
        except (KeyError, ValueError, RuntimeError) as e:
            return self._json({"erro": str(e)}, 400)
        return self._json({"erro": "não conheço"}, 404)


if __name__ == "__main__":
    esteira.vigiar_horario()                                  # no horário marcado na esteira, libera a fila sozinha
    print(f"Vega em http://127.0.0.1:{PORTA}  (Ctrl+C para desligar)")
    ThreadingHTTPServer(("127.0.0.1", PORTA), Pedido).serve_forever()
