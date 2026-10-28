# -*- coding: utf-8 -*-
"""
Espelho da Balança Transtino (roda na VPS / Easypanel).

Todo o sistema e o banco ficam no computador da balança. Este programa só:
  - pede usuário e senha para quem acessa pela internet;
  - repassa cada pedido do navegador para o computador da balança, que fica
    perguntando "tem algo para mim?" (/_agente/proximo) — assim não precisa
    abrir porta no roteador;
  - se o computador estiver sem internet, mostra a última cópia das telas.

Variáveis de ambiente: USUARIO, SENHA, AGENTE_TOKEN, PORTA (padrão 8000).
Só biblioteca padrão do Python.
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USUARIO = os.environ.get("USUARIO", "balanca")
SENHA = os.environ.get("SENHA", "")
AGENTE_TOKEN = os.environ.get("AGENTE_TOKEN", "")
PORTA = int(os.environ.get("PORTA", "8000"))
SESSAO_HORAS = 24 * 7    # a sessão dura 7 dias e se renova sozinha com o uso
ESPERA_RESPOSTA = 60       # segundos esperando o computador da balança responder
OFFLINE_APOS = 20          # sem contato do agente por mais que isso = offline

FILA = queue.Queue()
PENDENTES = {}             # id -> {"evento", "resposta"}
SAIDAS = set()             # sessões encerradas com "Sair" (as demais valem até expirar)
FALHAS_LOGIN = {}          # ip -> [quantidade, bloqueado até]
CACHE = {}                 # caminho GET -> resposta (última cópia, para quando estiver offline)
CACHE_MAX_BYTES = 60_000_000
CACHE_MAX_ITEM = 2_000_000
ESTADO = {"ultimo_contato": 0.0, "aguardando": 0}  # aguardando = consultas do agente esperando pedido
LOCK = threading.Lock()

# o que não pode ser feito pela internet (o computador da balança também bloqueia)
def bloqueado(metodo, caminho):
    p = urllib.parse.urlsplit(caminho).path
    return p.startswith("/api/backups") or (p.startswith("/api/config") and metodo != "GET")

# respostas que mudam a cada segundo não vão para a cópia
def guardar_em_cache(caminho):
    p = urllib.parse.urlsplit(caminho).path
    return not any(p.startswith(x) for x in ("/api/peso", "/api/camera", "/api/tag"))


# A sessão fica no próprio cookie, assinada com a senha: reiniciar ou fazer deploy
# do espelho não desconecta ninguém (antes ficava só na memória e caía).
CHAVE_SESSAO = hashlib.sha256(("sessao:" + SENHA + ":" + AGENTE_TOKEN).encode()).digest()


def assinar(texto):
    return hmac.new(CHAVE_SESSAO, texto.encode(), hashlib.sha256).hexdigest()


def nova_sessao():
    texto = str(int(time.time() + SESSAO_HORAS * 3600)) + "." + secrets.token_hex(8)
    return texto + "." + assinar(texto)


def expira_em(token):
    try:
        return int((token or "").split(".")[0])
    except ValueError:
        return 0


def sessao_valida(token):
    """Devolve quando a sessão expira (0 se for inválida)."""
    texto, _, assinatura = (token or "").rpartition(".")
    if not texto or token in SAIDAS or not hmac.compare_digest(assinatura, assinar(texto)):
        return 0
    exp = expira_em(token)
    return exp if exp > time.time() else 0


def agente_online():
    return ESTADO["aguardando"] > 0 or time.time() - ESTADO["ultimo_contato"] < OFFLINE_APOS


ICONE = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMjAgMTIwIiByb2xlPSJpbWciIGFyaWEtbGFiZWw9IkJhbGFuw6dhIFRyYW5zdGlubyI+PGRlZnM+PGxpbmVhckdyYWRpZW50IGlkPSJidC1mdW5kbyIgeDE9IjAiIHkxPSIwIiB4Mj0iMSIgeTI9IjEiPjxzdG9wIG9mZnNldD0iMCIgc3RvcC1jb2xvcj0iIzM0Yzc1OSIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iIzFiN2EzYSIvPjwvbGluZWFyR3JhZGllbnQ+PC9kZWZzPjxyZWN0IHdpZHRoPSIxMjAiIGhlaWdodD0iMTIwIiByeD0iMjYiIGZpbGw9InVybCgjYnQtZnVuZG8pIi8+PHJlY3QgeD0iMzgiIHk9IjE0IiB3aWR0aD0iNDQiIGhlaWdodD0iMjAiIHJ4PSI1IiBmaWxsPSIjMGQxYjJhIi8+PHJlY3QgeD0iNDQiIHk9IjIwIiB3aWR0aD0iNSIgaGVpZ2h0PSI4IiByeD0iMSIgZmlsbD0iIzVkZmY4ZiIvPjxyZWN0IHg9IjUyIiB5PSIyMCIgd2lkdGg9IjUiIGhlaWdodD0iOCIgcng9IjEiIGZpbGw9IiM1ZGZmOGYiLz48cmVjdCB4PSI2MCIgeT0iMjAiIHdpZHRoPSI1IiBoZWlnaHQ9IjgiIHJ4PSIxIiBmaWxsPSIjNWRmZjhmIi8+PHJlY3QgeD0iNjgiIHk9IjI1IiB3aWR0aD0iOCIgaGVpZ2h0PSIzIiByeD0iMSIgZmlsbD0iIzVkZmY4ZiIvPjxyZWN0IHg9IjE0IiB5PSI0NiIgd2lkdGg9IjU2IiBoZWlnaHQ9IjMwIiByeD0iNCIgZmlsbD0iI2ZmZmZmZiIvPjxwYXRoIGQ9Ik03MyA1MmgxN2wxMCAxM3YxMUg3M3oiIGZpbGw9IiNmZmZmZmYiLz48cGF0aCBkPSJNNzggNTZoMTBsNiA4SDc4eiIgZmlsbD0iIzFiN2EzYSIvPjxjaXJjbGUgY3g9IjI4IiBjeT0iODAiIHI9IjgiIGZpbGw9IiMwZDFiMmEiIHN0cm9rZT0iI2ZmZmZmZiIgc3Ryb2tlLXdpZHRoPSIzIi8+PGNpcmNsZSBjeD0iNTQiIGN5PSI4MCIgcj0iOCIgZmlsbD0iIzBkMWIyYSIgc3Ryb2tlPSIjZmZmZmZmIiBzdHJva2Utd2lkdGg9IjMiLz48Y2lyY2xlIGN4PSI4OCIgY3k9IjgwIiByPSI4IiBmaWxsPSIjMGQxYjJhIiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iMyIvPjxyZWN0IHg9IjgiIHk9IjkxIiB3aWR0aD0iMTA0IiBoZWlnaHQ9IjgiIHJ4PSIzIiBmaWxsPSIjMGQxYjJhIi8+PHBhdGggZD0iTTIwIDk5aDEwbC0zIDloLTR6TTkwIDk5aDEwbC0zIDloLTR6IiBmaWxsPSIjMGQxYjJhIi8+PC9zdmc+"
LOGO = """<svg style="width:100%;max-width:280px;height:auto;display:block;margin:0 auto 18px" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 470 120" role="img" aria-label="Balança Transtino — Pesagem rodoviária"><defs><linearGradient id="bt-fundo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#34c759"/><stop offset="1" stop-color="#1b7a3a"/></linearGradient></defs><rect width="120" height="120" rx="26" fill="url(#bt-fundo)"/><rect x="38" y="14" width="44" height="20" rx="5" fill="#0d1b2a"/><rect x="44" y="20" width="5" height="8" rx="1" fill="#5dff8f"/><rect x="52" y="20" width="5" height="8" rx="1" fill="#5dff8f"/><rect x="60" y="20" width="5" height="8" rx="1" fill="#5dff8f"/><rect x="68" y="25" width="8" height="3" rx="1" fill="#5dff8f"/><rect x="14" y="46" width="56" height="30" rx="4" fill="#ffffff"/><path d="M73 52h17l10 13v11H73z" fill="#ffffff"/><path d="M78 56h10l6 8H78z" fill="#1b7a3a"/><circle cx="28" cy="80" r="8" fill="#0d1b2a" stroke="#ffffff" stroke-width="3"/><circle cx="54" cy="80" r="8" fill="#0d1b2a" stroke="#ffffff" stroke-width="3"/><circle cx="88" cy="80" r="8" fill="#0d1b2a" stroke="#ffffff" stroke-width="3"/><rect x="8" y="91" width="104" height="8" rx="3" fill="#0d1b2a"/><path d="M20 99h10l-3 9h-4zM90 99h10l-3 9h-4z" fill="#0d1b2a"/><g font-family="'Segoe UI', Arial, Helvetica, sans-serif" font-weight="800"><text x="140" y="56" font-size="40" fill="#ffffff" letter-spacing="1">BALANÇA</text><text x="140" y="96" font-size="40" fill="#3fb950" letter-spacing="1">TRANSTINO</text></g><rect x="140" y="106" width="250" height="3" rx="1.5" fill="#1f9a46" opacity=".35"/></svg>"""

PAGINA_LOGIN = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Balança Transtino</title>
<link rel="icon" href="%ICONE%">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d1117;
font-family:Segoe UI,Arial,sans-serif;color:#e6edf3}form{background:#161b22;border:1px solid #30363d;border-radius:14px;
padding:28px;width:min(340px,90vw)}h1{font-size:20px;margin:0 0 18px;color:#3fb950}label{display:block;font-size:13px;
color:#8b949e;margin:12px 0 4px}input{width:100%;box-sizing:border-box;padding:11px;border-radius:9px;border:1px solid #30363d;
background:#0d1117;color:#e6edf3;font-size:15px}button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:9px;
background:#238636;color:#fff;font-weight:700;font-size:15px;cursor:pointer}.e{color:#ff7b72;font-size:13px;margin-top:10px}</style>
</head><body><form method="post" action="/_login">%LOGO%
<label>Usuário</label><input name="usuario" autocomplete="username" autofocus>
<label>Senha</label><input name="senha" type="password" autocomplete="current-password">
<button>Entrar</button>%ERRO%</form></body></html>""".replace("%ICONE%", ICONE).replace("%LOGO%", LOGO)

PAGINA_OFFLINE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Balança Transtino</title>
<link rel="icon" href="%ICONE%"></head>
<body style="font-family:Segoe UI,Arial;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;min-height:100vh">
<div style="text-align:center">%LOGO%<h1>⚠️ Computador da balança sem conexão</h1>
<p>O sistema roda no computador da balança e ele não está conectado à internet agora.<br>
A pesagem continua funcionando lá. Tente de novo em alguns minutos.</p><a style="color:#58a6ff" href="/">Tentar de novo</a></div></body></html>""".replace("%ICONE%", ICONE).replace("%LOGO%", LOGO)


class Handler(BaseHTTPRequestHandler):
    server_version = "EspelhoBalanca/1.0"

    def log_message(self, fmt, *args):
        if "/_agente/" in str(args[0] if args else "") or "/api/peso" in str(args[0] if args else ""):
            return
        print("[%s] %s %s" % (time.strftime("%H:%M:%S"), self.ip(), fmt % args), flush=True)

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def enviar(self, status, corpo, tipo="text/html; charset=utf-8", extras=None):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def json(self, status, obj):
        self.enviar(status, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            raise ValueError("corpo grande demais")
        return self.rfile.read(n) if n else b""

    # ---------------- sessão ----------------
    def cookie_sessao(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "espelho":
                return v
        return ""

    def sessao_ok(self):
        return sessao_valida(self.cookie_sessao()) > 0

    def set_cookie(self, token):
        seguro = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"espelho={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSAO_HORAS * 3600}{seguro}"

    def login(self):
        ip = self.ip()
        n, ate = FALHAS_LOGIN.get(ip, [0, 0])
        if ate > time.time():
            return self.enviar(429, PAGINA_LOGIN.replace("%ERRO%", '<div class="e">Muitas tentativas. Aguarde 10 minutos.</div>'))
        dados = urllib.parse.parse_qs(self.corpo().decode("utf-8", "ignore"))
        u, s = (dados.get("usuario") or [""])[0].strip(), (dados.get("senha") or [""])[0]
        if SENHA and hmac.compare_digest(u.lower(), USUARIO.lower()) and hmac.compare_digest(s, SENHA):
            FALHAS_LOGIN.pop(ip, None)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", self.set_cookie(nova_sessao()))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n += 1
        FALHAS_LOGIN[ip] = [n, time.time() + 600 if n >= 8 else 0]
        print(f"Login recusado de {ip} ({n}x)", flush=True)
        time.sleep(1.5)
        self.enviar(401, PAGINA_LOGIN.replace("%ERRO%", '<div class="e">Usuário ou senha incorretos.</div>'))

    # ---------------- agente (computador da balança) ----------------
    def agente_ok(self):
        return bool(AGENTE_TOKEN) and hmac.compare_digest(self.headers.get("X-Agente-Token") or "", AGENTE_TOKEN)

    def agente_proximo(self):
        ESTADO["ultimo_contato"] = time.time()
        with LOCK:
            ESTADO["aguardando"] += 1
        pedido, limite = None, time.time() + 25
        try:
            while time.time() < limite:
                p = FILA.get(timeout=max(0.1, limite - time.time()))
                if p["id"] in PENDENTES:  # pula pedidos que o navegador já desistiu de esperar
                    pedido = p
                    break
        except queue.Empty:
            pass
        finally:
            with LOCK:
                ESTADO["aguardando"] -= 1
            ESTADO["ultimo_contato"] = time.time()
        if pedido is None:
            return self.enviar(204, b"")
        try:
            self.json(200, pedido)
        except OSError:
            FILA.put(pedido)  # a conexão do agente caiu: devolve o pedido para outra consulta
            raise

    def agente_resposta(self):
        ESTADO["ultimo_contato"] = time.time()
        r = json.loads(self.corpo() or b"{}")
        p = PENDENTES.get(r.get("id"))
        if p:
            p["resposta"] = r
            p["evento"].set()
        self.json(200, {"ok": True})

    # ---------------- repasse ----------------
    def repassar(self, metodo):
        caminho = self.path
        if bloqueado(metodo, caminho):
            return self.json(403, {"erro": "Isso só pode ser feito no computador da balança."})
        if not agente_online():
            return self.copia_ou_offline(metodo, caminho)
        pid = secrets.token_hex(8)
        evento = threading.Event()
        PENDENTES[pid] = {"evento": evento, "resposta": None}
        FILA.put({"id": pid, "metodo": metodo, "caminho": caminho,
                  "tipo": self.headers.get("Content-Type") or "",
                  "corpo": base64.b64encode(self.corpo()).decode()})
        try:
            if not evento.wait(ESPERA_RESPOSTA):
                return self.copia_ou_offline(metodo, caminho)
            r = PENDENTES[pid]["resposta"]
        finally:
            PENDENTES.pop(pid, None)
        corpo = base64.b64decode(r.get("corpo") or "")
        cab = {k: v for k, v in (r.get("cabecalhos") or {}).items() if k.lower() in ("content-disposition",)}
        tipo = (r.get("cabecalhos") or {}).get("Content-Type") or "application/octet-stream"
        status = int(r.get("status") or 502)
        if metodo == "GET" and status == 200 and guardar_em_cache(caminho) and len(corpo) <= CACHE_MAX_ITEM:
            with LOCK:  # limite de memória: a VPS reiniciava o espelho quando a cópia crescia demais
                CACHE.pop(caminho, None)
                CACHE[caminho] = (tipo, corpo, cab)
                while len(CACHE) > 500 or sum(len(c[1]) for c in CACHE.values()) > CACHE_MAX_BYTES:
                    CACHE.pop(next(iter(CACHE)))  # descarta a mais antiga
        self.enviar(status, corpo, tipo, cab)

    def copia_ou_offline(self, metodo, caminho):
        if metodo == "GET" and caminho in CACHE:
            tipo, corpo, cab = CACHE[caminho]
            return self.enviar(200, corpo, tipo, dict(cab, **{"X-Espelho": "copia"}))
        if caminho.startswith("/api/"):
            return self.json(503, {"erro": "Computador da balança sem conexão — mostrando a última cópia quando houver."})
        self.enviar(503, PAGINA_OFFLINE)

    # ---------------- rotas ----------------
    def tratar(self, metodo):
        try:
            caminho = urllib.parse.urlsplit(self.path).path
            if caminho.startswith("/_agente/"):
                if not self.agente_ok():
                    return self.json(401, {"erro": "token inválido"})
                if caminho == "/_agente/proximo":
                    return self.agente_proximo()
                if caminho == "/_agente/resposta" and metodo == "POST":
                    return self.agente_resposta()
                return self.json(404, {"erro": "rota"})
            if caminho == "/_saude":
                return self.json(200, {"ok": True})
            if caminho == "/_login":
                if metodo == "POST":
                    return self.login()
                return self.enviar(200, PAGINA_LOGIN.replace("%ERRO%", ""))
            if not self.sessao_ok():
                if caminho.startswith("/api/") or caminho.startswith("/_"):
                    return self.json(401, {"erro": "Sessão expirada — faça login de novo.", "login": True})
                self.send_response(303)
                self.send_header("Location", "/_login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if caminho == "/_sair":
                SAIDAS.add(self.cookie_sessao())
                self.send_response(303)
                self.send_header("Location", "/_login")
                self.send_header("Set-Cookie", "espelho=; Path=/; Max-Age=0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if caminho == "/_status":
                extras = {}
                if sessao_valida(self.cookie_sessao()) - time.time() < SESSAO_HORAS * 3600 / 2:
                    extras["Set-Cookie"] = self.set_cookie(nova_sessao())  # renova a sessão de quem está usando
                corpo = {"online": agente_online(), "ultimo_contato": ESTADO["ultimo_contato"]}
                return self.enviar(200, json.dumps(corpo), "application/json; charset=utf-8", extras)
            self.repassar(metodo)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            try:
                self.json(500, {"erro": f"{type(e).__name__}: {e}"})
            except OSError:
                pass

    def do_GET(self):
        self.tratar("GET")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self.tratar("POST")

    def do_PUT(self):
        self.tratar("PUT")

    def do_DELETE(self):
        self.tratar("DELETE")


def limpar_sessoes():
    while True:
        time.sleep(600)
        for t in [t for t in SAIDAS if expira_em(t) < time.time()]:
            SAIDAS.discard(t)


if __name__ == "__main__":
    if not SENHA or not AGENTE_TOKEN:
        print("ATENÇÃO: defina SENHA e AGENTE_TOKEN nas variáveis de ambiente.", flush=True)
    threading.Thread(target=limpar_sessoes, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    print(f"Espelho da balança na porta {PORTA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
