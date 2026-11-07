"""Quanto do limite do plano do Claude já foi usado (janela de 5 h e da semana) e quando zera, para o topo da página.

Duas fontes, as duas sem mexer no login:
  - ao vivo: a mesma consulta que o /usage do Claude Code faz (api.anthropic.com/api/oauth/usage), com o token que o próprio
    Claude Code já guarda em ~/.claude/.credentials.json. Só lê: nunca renova nem grava. Guardada por 60 s;
  - a cópia que o Claude Code guarda em ~/.claude.json ("cachedUsageUtilization"), atualizada quando o /usage é aberto.
Vale a mais nova. Sem nenhuma das duas (login por chave de API, por exemplo), a página só não mostra os limites.
Desligue com "mostrar_limites": false no config.json.
"""
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CASA = Path.home()
_ao_vivo = {"dados": None, "tentou": 0}


def _quando(v):
    """resets_at pode vir em segundos, milissegundos ou como data ISO. Devolve segundos ou None."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e12 else 1)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _janela(d):
    return {"usado": d.get("utilization"), "zera": d.get("resets_at")} if isinstance(d, dict) else None


def _consultar_ao_vivo():
    agora = time.time()
    if agora - _ao_vivo["tentou"] < 60:
        return _ao_vivo["dados"]
    _ao_vivo["tentou"] = agora
    try:
        token = json.loads((CASA / ".claude" / ".credentials.json").read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20", "User-Agent": "vega"})
        u = json.loads(urllib.request.urlopen(req, timeout=8).read())
        _ao_vivo["dados"] = {"quando": agora, "cinco_horas": _janela(u.get("five_hour")), "semana": _janela(u.get("seven_day"))}
    except Exception:                                          # token vencido, outro tipo de login ou sem internet: fica a última leitura boa
        pass
    return _ao_vivo["dados"]


def limites():
    opcoes = []
    vivo = _consultar_ao_vivo()
    if vivo:
        opcoes.append(dict(vivo))
    try:
        c = json.loads((CASA / ".claude.json").read_text(encoding="utf-8")).get("cachedUsageUtilization") or {}
        u = c.get("utilization") or {}
        if u:
            opcoes.append({"quando": (c.get("fetchedAtMs") or 0) / 1000, "cinco_horas": _janela(u.get("five_hour")), "semana": _janela(u.get("seven_day"))})
    except Exception:
        pass
    if not opcoes:
        return {"limites": None}
    m = max(opcoes, key=lambda o: o["quando"])
    agora = time.time()
    for k in ("cinco_horas", "semana"):
        j = m.get(k)
        if j:
            z = _quando(j.get("zera"))
            m[k] = {"usado": 0, "zera": None} if z and z < agora else {"usado": j.get("usado"), "zera": z}   # já zerou depois dessa leitura
    m["idade_min"] = round((agora - m["quando"]) / 60) if m["quando"] else None
    return {"limites": m}


if __name__ == "__main__":
    print(json.dumps(limites(), ensure_ascii=False, indent=1))
