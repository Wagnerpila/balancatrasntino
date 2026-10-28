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
SESSAO_HORAS = 12
ESPERA_RESPOSTA = 60       # segundos esperando o computador da balança responder
OFFLINE_APOS = 20          # sem contato do agente por mais que isso = offline

FILA = queue.Queue()
PENDENTES = {}             # id -> {"evento", "resposta"}
SESSOES = {}               # token -> expira em
FALHAS_LOGIN = {}          # ip -> [quantidade, bloqueado até]
CACHE = {}                 # caminho GET -> resposta (última cópia, para quando estiver offline)
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


def agente_online():
    return ESTADO["aguardando"] > 0 or time.time() - ESTADO["ultimo_contato"] < OFFLINE_APOS


PAGINA_LOGIN = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Balança Transtino</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0d1117;
font-family:Segoe UI,Arial,sans-serif;color:#e6edf3}form{background:#161b22;border:1px solid #30363d;border-radius:14px;
padding:28px;width:min(340px,90vw)}h1{font-size:20px;margin:0 0 18px;color:#3fb950}label{display:block;font-size:13px;
color:#8b949e;margin:12px 0 4px}input{width:100%;box-sizing:border-box;padding:11px;border-radius:9px;border:1px solid #30363d;
background:#0d1117;color:#e6edf3;font-size:15px}button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:9px;
background:#238636;color:#fff;font-weight:700;font-size:15px;cursor:pointer}.e{color:#ff7b72;font-size:13px;margin-top:10px}</style>
</head><body><form method="post" action="/_login"><h1>⚖ Balança Transtino</h1>
<label>Usuário</label><input name="usuario" autocomplete="username" autofocus>
<label>Senha</label><input name="senha" type="password" autocomplete="current-password">
<button>Entrar</button>%ERRO%</form></body></html>"""

PAGINA_OFFLINE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Balança Transtino</title></head>
<body style="font-family:Segoe UI,Arial;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;min-height:100vh">
<div style="text-align:center"><h1>⚠️ Computador da balança sem conexão</h1>
<p>O sistema roda no computador da balança e ele não está conectado à internet agora.<br>
A pesagem continua funcionando lá. Tente de novo em alguns minutos.</p><a style="color:#58a6ff" href="/">Tentar de novo</a></div></body></html>"""


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
    def sessao_ok(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "espelho":
                with LOCK:
                    exp = SESSOES.get(v)
                return bool(exp and exp > time.time())
        return False

    def login(self):
        ip = self.ip()
        n, ate = FALHAS_LOGIN.get(ip, [0, 0])
        if ate > time.time():
            return self.enviar(429, PAGINA_LOGIN.replace("%ERRO%", '<div class="e">Muitas tentativas. Aguarde 10 minutos.</div>'))
        dados = urllib.parse.parse_qs(self.corpo().decode("utf-8", "ignore"))
        u, s = (dados.get("usuario") or [""])[0].strip(), (dados.get("senha") or [""])[0]
        if SENHA and hmac.compare_digest(u.lower(), USUARIO.lower()) and hmac.compare_digest(s, SENHA):
            FALHAS_LOGIN.pop(ip, None)
            token = secrets.token_urlsafe(32)
            with LOCK:
                SESSOES[token] = time.time() + SESSAO_HORAS * 3600
            seguro = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"espelho={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSAO_HORAS * 3600}{seguro}")
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
        try:
            pedido = FILA.get(timeout=25)
        except queue.Empty:
            pedido = None
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
        if metodo == "GET" and status == 200 and guardar_em_cache(caminho):
            if len(CACHE) > 500 and caminho not in CACHE:
                CACHE.pop(next(iter(CACHE)))  # descarta a mais antiga
            CACHE[caminho] = (tipo, corpo, cab)
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
                    return self.json(401, {"erro": "Faça login de novo."})
                self.send_response(303)
                self.send_header("Location", "/_login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if caminho == "/_sair":
                for parte in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = parte.strip().partition("=")
                    if k == "espelho":
                        SESSOES.pop(v, None)
                self.send_response(303)
                self.send_header("Location", "/_login")
                self.send_header("Set-Cookie", "espelho=; Path=/; Max-Age=0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if caminho == "/_status":
                return self.json(200, {"online": agente_online(), "ultimo_contato": ESTADO["ultimo_contato"]})
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

    def do_POST(self):
        self.tratar("POST")

    def do_PUT(self):
        self.tratar("PUT")

    def do_DELETE(self):
        self.tratar("DELETE")


def limpar_sessoes():
    while True:
        time.sleep(600)
        agora = time.time()
        with LOCK:
            for t in [t for t, e in SESSOES.items() if e < agora]:
                SESSOES.pop(t, None)


if __name__ == "__main__":
    if not SENHA or not AGENTE_TOKEN:
        print("ATENÇÃO: defina SENHA e AGENTE_TOKEN nas variáveis de ambiente.", flush=True)
    threading.Thread(target=limpar_sessoes, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    print(f"Espelho da balança na porta {PORTA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
