"""Registra uma tarefa longa para aparecer no painel "Em segundo plano" da Vega (à direita da página).

  python segundo_plano.py "Render do vídeo" --busca render.py --log C:/.../render.log --etapas "preparar,renderizar,salvar"

--busca: um trecho da linha de comando do processo; quando nenhum processo tiver mais esse trecho, o cartão some.
--etapas e --log: a etapa atual é a última da lista cujo nome já apareceu no log.
Quem usa é o próprio Claude, quando deixa um processo rodando sozinho (está no aviso que a Vega manda para ele).
"""
import argparse
import json
import re
import time
from pathlib import Path

REGISTRO = Path(__file__).resolve().parent / "dados" / "segundo_plano"

a = argparse.ArgumentParser()
a.add_argument("nome")
a.add_argument("--detalhe", default="")
a.add_argument("--busca", default="")
a.add_argument("--log", default="")
a.add_argument("--etapas", default="")
x = a.parse_args()
REGISTRO.mkdir(parents=True, exist_ok=True)
arq = REGISTRO / ((re.sub(r"[^A-Za-z0-9]+", "-", x.nome).strip("-").lower()[:50] or "tarefa") + ".json")
arq.write_text(json.dumps({"nome": x.nome, "detalhe": x.detalhe, "busca": x.busca, "log": x.log, "inicio": int(time.time()),
                           "etapas": [e.strip() for e in x.etapas.split(",") if e.strip()]}, ensure_ascii=False), encoding="utf-8")
print("registrado:", arq.name)
