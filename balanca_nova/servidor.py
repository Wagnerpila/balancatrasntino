# -*- coding: utf-8 -*-
"""
Sistema de Pesagem - Balança Transtino (versão nova)

Servidor local que usa SOMENTE a biblioteca padrão do Python (não precisa de
Django, venv ou pip). Lê e grava no MESMO banco SQLite do sistema antigo
(balanca/db.sqlite3), então os cadastros (pesagem_cliente) e o histórico
(pesagem_pesagem) continuam compartilhados com o sistema Django.

Como abrir: dê dois cliques em INICIAR.bat (ou rode: python servidor.py).
"""
import base64
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
STATIC_DIR = os.path.join(BASE, "static")
FOTOS_DIR = os.path.join(BASE, "fotos")  # foto da câmera de cada ticket encerrado (fotos/ticket_<id>.jpg)
LOGS_DIR = os.path.join(BASE, "logs")
FALHAS_LOG = os.path.join(LOGS_DIR, "falhas.log")

DEFAULT_CONFIG = {
    "porta": 8080,
    "banco_dados": "../balanca/db.sqlite3",
    "empresa": "BALANÇA TRANSTINO",
    "balanca_url": "http://127.0.0.1:80/peso/?fmt=1",
    "numero_balanca": 1,
    "vias_impressao": 2,
    "impressora": "",
    "pesagem_unica": True,
    "registrar_no_historico_antigo": True,
    "abrir_navegador": True,
    "chrome_impressao_direta": False,
    "incontrol": {
        "ativo": False,
        "url": "https://localhost:4441",
        "usuario": "admin",
        "senha": "",
    },
    "backup": {
        "ativo": True,
        "pasta": "backups",
        "intervalo_horas": 6,
        "manter": 60,
    },
    "espelho": {
        "ativo": False,
        "url": "",
        "token": "",
        "conexoes": 6,
    },
    "camera": {
        "ativo": False,
        "url": "rtsp://192.168.100.29:554/",
        "usuario": "admin",
        "senha": "",
        "peso_minimo": 100,
        "ler_placa": True,
        "pesagem_automatica": True,
        "imprimir_automatico": False,
        "segundos_estavel": 3,
        "porta_auxiliar": 8092,
    },
    "whatsapp": {
        "ativo": False,
        "numeros": "",
        "link": "https://balancatranstino.wcmdigital.com.br",
        "espera_placa": 25,
    },
}


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
def carregar_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            salvo = json.load(f)
        for k, v in salvo.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    else:
        salvar_config(cfg)
    return cfg


def salvar_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = carregar_config()


def caminho_banco():
    p = CONFIG["banco_dados"]
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(BASE, p))


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
def conectar():
    con = sqlite3.connect(caminho_banco(), timeout=15)
    con.row_factory = sqlite3.Row
    return con


def preparar_banco():
    """Cria as tabelas do sistema novo (não mexe na estrutura das tabelas do Django)."""
    with conectar() as con:
        ja_instalado = con.execute("SELECT 1 FROM sqlite_master WHERE name='nova_ticket'").fetchone()
        sem_empresas = not con.execute("SELECT 1 FROM sqlite_master WHERE name='nova_empresa'").fetchone()
    if ja_instalado and sem_empresas:
        # primeira vez com cadastro de empresas/cobrança: guarda uma cópia antes de mexer na estrutura
        fazer_backup("antes_atualizacao")
    with conectar() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS nova_ticket (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL DEFAULT 'ABERTO',
                emissor TEXT NOT NULL DEFAULT 'Manual',
                cliente_id INTEGER,
                tag TEXT,
                placa TEXT,
                transportadora TEXT,
                motorista TEXT,
                item TEXT,
                peso_inicial REAL,
                data_inicial TEXT,
                operador_inicial TEXT,
                balanca_inicial INTEGER,
                origem_inicial TEXT,
                peso_final REAL,
                data_final TEXT,
                operador_final TEXT,
                balanca_final INTEGER,
                origem_final TEXT,
                peso_liquido REAL,
                peso_origem REAL,
                local_descarga TEXT,
                observacao TEXT,
                pesagem_legado_id INTEGER,
                criado_em TEXT,
                atualizado_em TEXT
            )
            """
        )
        # Empresa definida manualmente para um cadastro (quando o agrupamento automático não serve)
        con.execute(
            "CREATE TABLE IF NOT EXISTS nova_cliente_empresa (cliente_id INTEGER PRIMARY KEY, empresa TEXT NOT NULL)"
        )
        # Cadastro de empresas (quem contrata o serviço / recebe a cobrança)
        con.execute(
            """CREATE TABLE IF NOT EXISTS nova_empresa (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, documento TEXT, telefone TEXT,
                email TEXT, contato TEXT, endereco TEXT, observacao TEXT, plano_id INTEGER,
                ativa INTEGER NOT NULL DEFAULT 1, criado_em TEXT, atualizado_em TEXT)"""
        )
        # Dados do motorista/caminhão que não cabem na tabela do Django:
        # empresa vinculada, quem paga, tabela de valor própria, cadastro oculto (unificado)
        con.execute(
            """CREATE TABLE IF NOT EXISTS nova_motorista (
                cliente_id INTEGER PRIMARY KEY, motorista_nome TEXT, empresa_id INTEGER, pagador TEXT,
                plano_id INTEGER, inativo INTEGER NOT NULL DEFAULT 0, unificado_em INTEGER,
                nome_original TEXT, atualizado_em TEXT)"""
        )
        # Tabela de valores: por pesagem, por tonelada ou pacote mensal
        con.execute(
            """CREATE TABLE IF NOT EXISTS nova_plano (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, tipo TEXT NOT NULL,
                valor REAL NOT NULL DEFAULT 0, franquia INTEGER NOT NULL DEFAULT 0,
                valor_excedente REAL NOT NULL DEFAULT 0, padrao INTEGER NOT NULL DEFAULT 0,
                ativo INTEGER NOT NULL DEFAULT 1, observacao TEXT, criado_em TEXT, atualizado_em TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS nova_fatura (
                id INTEGER PRIMARY KEY AUTOINCREMENT, pagador TEXT NOT NULL, pagador_chave TEXT NOT NULL,
                pagador_tipo TEXT, empresa_id INTEGER, inicio TEXT, fim TEXT, pesagens INTEGER, liquido REAL,
                valor REAL, status TEXT NOT NULL DEFAULT 'ABERTA', detalhes TEXT, observacao TEXT,
                criado_em TEXT, pago_em TEXT)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS nova_fatura_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT, fatura_id INTEGER NOT NULL, ref TEXT NOT NULL,
                descricao TEXT, valor REAL)"""
        )
        con.execute("CREATE INDEX IF NOT EXISTS ix_nova_fatura_item_ref ON nova_fatura_item(ref)")
        con.execute("CREATE TABLE IF NOT EXISTS nova_migracao_ignorar (tipo TEXT, chave TEXT, PRIMARY KEY (tipo, chave))")
        colunas = {r[1] for r in con.execute("PRAGMA table_info(nova_ticket)")}
        for col, tipo in (("empresa_id", "INTEGER"), ("empresa_nome", "TEXT"), ("pagador", "TEXT"),
                          ("pagador_nome", "TEXT"), ("valor_manual", "REAL")):
            if col not in colunas:
                con.execute(f"ALTER TABLE nova_ticket ADD COLUMN {col} {tipo}")
        # "Empresa" digitada à mão nas versões anteriores vira empresa cadastrada
        for cid, nome in con.execute("SELECT cliente_id, empresa FROM nova_cliente_empresa").fetchall():
            v = con.execute("SELECT empresa_id FROM nova_motorista WHERE cliente_id = ?", (cid,)).fetchone()
            if not (v and v[0]):
                gravar_vinculo(con, cid, empresa_id=obter_ou_criar_empresa(con, nome), pagador="EMPRESA")


def agora_local():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def agora_utc_django():
    # Django (USE_TZ=True) grava datetimes em UTC no SQLite
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def utc_para_local(texto):
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(str(texto).replace("Z", "")).replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return texto


def local_para_utc(texto):
    """'2026-10-16 15:09:58' (hora local) -> formato UTC usado pelo Django no SQLite."""
    dt = datetime.fromisoformat(str(texto).replace("T", " ")).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in v else float(v)
    except ValueError:
        return None


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


# --------------------------------------------------------------------------
# Cadastros (tabela pesagem_cliente do sistema antigo)
# --------------------------------------------------------------------------
CAMPOS_CLIENTE = [
    "nome", "cnpj", "telefone", "email", "placa", "modelo", "peso_maximo",
    "ano_fabricacao", "tipo_carga", "peso_carga", "descricao_carga",
    "card_no", "card_type", "card_name", "card_status", "user_id",
]


def empresa_automatica(nome):
    """
    Empresas com vários caminhões são cadastradas como um registro por caminhão,
    com um número no fim do nome: "JOAO ARTUR ARGENTA 07", "ROBERTO BETO - 86",
    "RSFL115 -122". Removendo esse final sobra o nome da empresa.
    """
    n = re.sub(r"\s+", " ", str(nome or "").upper()).strip()
    n = re.sub(r"\s*-\s*\d+\s*$", "", n)
    n = re.sub(r"(\s+\d+)+\s*$", "", n)
    n = re.sub(r"\d+$", "", n).strip()
    return n or str(nome or "").upper().strip()


def cliente_dict(row, empresas_manuais=None, empresas=None, vinculos=None):
    """
    Um cadastro = um motorista/caminhão. A empresa para quem ele trabalha vem do
    vínculo (nova_motorista -> nova_empresa). Sem vínculo, vale o agrupamento antigo
    (nome sem o número do fim), que serve para as frotas ainda não cadastradas.
    """
    d = dict(row)
    v = (vinculos or {}).get(d["id"]) or {}
    e = (empresas or {}).get(v.get("empresa_id"))
    manual = (empresas_manuais or {}).get(d["id"])
    d["tara"] = d.get("peso_maximo")
    d["motorista_nome"] = v.get("motorista_nome") or ""
    # nome no cartão só vale quando é outra pessoa (ex.: cadastro "MARCOS ..." com cartão "DOMINGOS")
    cartao = d.get("card_name") or ""
    outro = normalizar(cartao) and normalizar(cartao.split()[0]) not in normalizar(d.get("nome"))
    d["motorista"] = d["motorista_nome"] or (cartao if outro else d.get("nome"))
    d["empresa_id"] = e["id"] if e else None
    d["empresa_vinculada"] = e["nome"] if e else ""
    d["empresa_manual"] = manual or ""
    d["empresa"] = d["empresa_vinculada"] or manual or empresa_automatica(d.get("nome"))
    # quem paga: a empresa (motorista prestador de serviço) ou o próprio motorista/dono do caminhão
    d["pagador"] = "EMPRESA" if e and v.get("pagador") != "MOTORISTA" else "MOTORISTA"
    d["titular"] = d["motorista_nome"] or (empresa_automatica(d.get("nome")) if e else d["empresa"])
    d["pagador_nome"] = e["nome"] if d["pagador"] == "EMPRESA" else d["titular"]
    d["plano_id"] = v.get("plano_id")
    d["empresa_plano_id"] = e.get("plano_id") if e else None
    d["inativo"] = bool(v.get("inativo"))
    d["unificado_em"] = v.get("unificado_em")
    d["nome_original"] = v.get("nome_original") or ""
    return d


def todos_clientes(con, inativos=False):
    manuais = dict(con.execute("SELECT cliente_id, empresa FROM nova_cliente_empresa").fetchall())
    empresas = {r["id"]: dict(r) for r in con.execute("SELECT * FROM nova_empresa")}
    vinculos = {r["cliente_id"]: dict(r) for r in con.execute("SELECT * FROM nova_motorista")}
    rows = con.execute("SELECT * FROM pesagem_cliente ORDER BY nome").fetchall()
    lista = [cliente_dict(r, manuais, empresas, vinculos) for r in rows]
    return lista if inativos else [c for c in lista if not c["inativo"]]


def obter_cliente(con, cid):
    return next((c for c in todos_clientes(con, True) if c["id"] == cid), None)


def gravar_vinculo(con, cliente_id, **campos):
    con.execute("INSERT OR IGNORE INTO nova_motorista (cliente_id) VALUES (?)", (cliente_id,))
    campos["atualizado_em"] = agora_local()
    sets = ", ".join(f"{k} = ?" for k in campos)
    con.execute(f"UPDATE nova_motorista SET {sets} WHERE cliente_id = ?", (*campos.values(), cliente_id))


def limpar_nome(nome):
    return re.sub(r"\s+", " ", str(nome or "")).upper().strip()


def obter_ou_criar_empresa(con, nome):
    nome = limpar_nome(nome)
    if not nome:
        return None
    alvo = normalizar(nome)
    for r in con.execute("SELECT id, nome FROM nova_empresa"):
        if normalizar(r["nome"]) == alvo:
            return r["id"]
    agora = agora_local()
    return con.execute("INSERT INTO nova_empresa (nome, ativa, criado_em, atualizado_em) VALUES (?, 1, ?, ?)",
                       (nome, agora, agora)).lastrowid


def contar_por_empresa(clientes):
    qtd = {}
    for c in clientes:
        qtd[c["empresa"]] = qtd.get(c["empresa"], 0) + 1
    for c in clientes:
        c["caminhoes_empresa"] = qtd[c["empresa"]]
    return clientes


def buscar_clientes(q="", limite=50, ocultos=False):
    with conectar() as con:
        todos = contar_por_empresa(todos_clientes(con, ocultos))
    if not q:
        return todos[:limite]
    alvo = normalizar(q)
    campos = ("nome", "placa", "user_id", "card_name", "empresa", "motorista_nome")
    achados = [c for c in todos if any(alvo in normalizar(c.get(k)) for k in campos)
               or str(c.get("card_no") or "").strip() == q.strip()]
    return achados[:limite]


def listar_empresas(q=""):
    with conectar() as con:
        todos = todos_clientes(con)
    grupos = {}
    for c in todos:
        g = grupos.setdefault(c["empresa"], {"empresa": c["empresa"], "caminhoes": 0, "placas": []})
        g["caminhoes"] += 1
        g["placas"].append(c["placa"])
    lista = sorted(grupos.values(), key=lambda g: g["empresa"])
    if q:
        alvo = normalizar(q)
        lista = [g for g in lista if alvo in normalizar(g["empresa"])
                 or any(alvo in normalizar(p) for p in g["placas"])]
    return lista


def caminhoes_da_empresa(empresa):
    with conectar() as con:
        todos = [c for c in todos_clientes(con) if c["empresa"] == empresa]
        abertos = {r["cliente_id"]: r["id"] for r in con.execute(
            "SELECT id, cliente_id FROM nova_ticket WHERE status='ABERTO' AND cliente_id IS NOT NULL")}
    for c in todos:
        c["ticket_aberto"] = abertos.get(c["id"])
        c["caminhoes_empresa"] = len(todos)
    return sorted(todos, key=lambda c: (c["nome"], c["placa"]))


def identificar_por_tag(codigo):
    """
    Como as tags funcionam neste projeto:
      - A tag/cartão RFID é lida pelo controlador Intelbras (CT-3000) e o InControl
        registra o evento com o NOME do usuário, ex.: "DOMINGOS - 41".
      - No cadastro (pesagem_cliente) esse mesmo texto fica em `user_id`
        e o número (41) fica em `card_no`.
    Aqui aceitamos qualquer um: "DOMINGOS - 41", "DOMINGOS-41", "41", placa ou nome.
    """
    codigo = (codigo or "").strip()
    if not codigo:
        return []
    with conectar() as con:
        todos = contar_por_empresa(todos_clientes(con))
    alvo = normalizar(codigo)
    m = re.search(r"(\d+)\s*$", codigo)
    numero = m.group(1) if m else None

    def pontos(r):
        if normalizar(r["user_id"]) == alvo:
            return 100
        if normalizar(r["placa"]) == alvo:
            return 95
        if normalizar(r["card_name"]) == alvo or normalizar(r["nome"]) == alvo:
            return 90
        if numero and str(r["card_no"] or "").strip() == numero and numero != "0":
            return 80
        if len(alvo) >= 3 and (alvo in normalizar(r["user_id"]) or alvo in normalizar(r["nome"])):
            return 50
        return 0

    achados = sorted(((pontos(r), r) for r in todos), key=lambda x: -x[0])
    return [dict(r, confianca=p) for p, r in achados if p > 0][:10]


def salvar_cliente(dados, cliente_id=None):
    valores = {}
    padroes = {"cnpj": "0000000000", "telefone": "00000000000", "email": "balancatranstino@gmail.com",
               "modelo": "", "ano_fabricacao": 0, "peso_carga": 0, "descricao_carga": "",
               "peso_maximo": 0, "tipo_carga": ""}
    for c in CAMPOS_CLIENTE:
        if c in dados:
            valores[c] = dados[c]
    for c in ("peso_maximo", "peso_carga"):
        if c in valores:
            valores[c] = num(valores[c]) or 0
    for c in ("ano_fabricacao", "card_type", "card_status"):
        if c in valores and valores[c] not in (None, ""):
            valores[c] = int(num(valores[c]) or 0)
    if "placa" in valores:
        valores["placa"] = str(valores["placa"]).upper().strip()[:8]
    empresa = dados.get("empresa_manual")
    vinc = {k: dados[k] for k in ("empresa_id", "pagador", "motorista_nome", "plano_id") if k in dados}
    for k in ("empresa_id", "plano_id"):
        if k in vinc:
            vinc[k] = int(num(vinc[k])) if str(vinc[k] or "").strip() else None
    if "motorista_nome" in vinc:
        vinc["motorista_nome"] = limpar_nome(vinc["motorista_nome"]) or None
    if "empresa_id" in vinc or "pagador" in vinc:
        if vinc.get("pagador") not in ("EMPRESA", "MOTORISTA"):
            vinc["pagador"] = "EMPRESA" if vinc.get("empresa_id") else "MOTORISTA"
    with conectar() as con:
        if vinc.get("empresa_id") and not con.execute(
                "SELECT 1 FROM nova_empresa WHERE id = ?", (vinc["empresa_id"],)).fetchone():
            raise ValueError("Empresa não encontrada.")
        if cliente_id:
            if valores:
                sets = ", ".join(f"{c} = ?" for c in valores)
                con.execute(f"UPDATE pesagem_cliente SET {sets} WHERE id = ?", (*valores.values(), cliente_id))
            novo_id = cliente_id
        else:
            if not valores.get("nome") or not valores.get("placa"):
                raise ValueError("Nome e placa são obrigatórios.")
            for k, v in padroes.items():
                if valores.get(k) in (None, ""):
                    valores[k] = v
            valores.setdefault("user_id", valores["nome"])
            valores.setdefault("card_name", valores["nome"])
            cols = ", ".join(valores)
            marks = ", ".join("?" for _ in valores)
            cur = con.execute(f"INSERT INTO pesagem_cliente ({cols}) VALUES ({marks})", tuple(valores.values()))
            novo_id = cur.lastrowid
        if empresa is not None:
            empresa = str(empresa).upper().strip()
            if empresa:
                con.execute("INSERT OR REPLACE INTO nova_cliente_empresa (cliente_id, empresa) VALUES (?, ?)",
                            (novo_id, empresa))
            else:
                con.execute("DELETE FROM nova_cliente_empresa WHERE cliente_id = ?", (novo_id,))
        if vinc:
            gravar_vinculo(con, novo_id, **vinc)
        return obter_cliente(con, novo_id)


# --------------------------------------------------------------------------
# Balança (API local do indicador WT3000 / LE 170 em 127.0.0.1:80)
# --------------------------------------------------------------------------
def ler_balanca():
    try:
        with urllib.request.urlopen(CONFIG["balanca_url"], timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "peso": None, "estavel": False, "unidade": "kg",
                "mensagem": f"Sem comunicação com a API da balança: {e}"}
    ok = data.get("status") == "ok" and data.get("gross") is not None
    return {
        "ok": ok,
        "peso": data.get("gross"),
        "liquido": data.get("net"),
        "tara_indicador": data.get("tare"),
        "estavel": bool(data.get("is_stable")),
        "unidade": data.get("unity") or "kg",
        "modelo": data.get("model"),
        "mensagem": data.get("status_msg") or ("OK" if ok else "Falha na leitura"),
    }


# --------------------------------------------------------------------------
# Log de falhas (logs/falhas.log): uma linha por problema, para conferir depois
# --------------------------------------------------------------------------
LOG_LOCK = threading.Lock()


def registrar_falha(tipo, mensagem, placa=""):
    linha = " | ".join([agora_local(), str(tipo or "-"), str(placa or "-"),
                        " ".join(str(mensagem or "").split())])
    print("FALHA:", linha)
    with LOG_LOCK:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(FALHAS_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")


def ler_falhas(limite=300):
    if not os.path.isfile(FALHAS_LOG):
        return []
    with open(FALHAS_LOG, encoding="utf-8", errors="replace") as f:
        linhas = f.read().splitlines()[-limite:]
    itens = []
    for ln in reversed(linhas):
        partes = (ln.split(" | ", 3) + ["", "", ""])[:4]
        itens.append({"quando": partes[0], "tipo": partes[1], "placa": partes[2], "mensagem": partes[3]})
    return itens


# --------------------------------------------------------------------------
# Impressão direta do ticket (sem janela): o Chrome sem tela tira a "foto" da
# página do ticket e o PowerShell manda essa imagem para a impressora escolhida.
# --------------------------------------------------------------------------
IMPRESSAO_LOCK = threading.Lock()
SEM_JANELA = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def chrome_exe():
    candidatos = [
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((c for c in candidatos if c and os.path.isfile(c)), None)


def listar_impressoras():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Printer | Select-Object -ExpandProperty Name; '---'; "
                        "(Get-CimInstance Win32_Printer -Filter 'Default=True').Name"],
                       capture_output=True, text=True, timeout=30, creationflags=SEM_JANELA)
    nomes, _, padrao = r.stdout.partition("---")
    return {"impressoras": [n.strip() for n in nomes.splitlines() if n.strip()], "padrao": padrao.strip()}


def imprimir_ticket_direto(tid, foto=False, placa=""):
    """Imprime o ticket na impressora da configuração (vazia = padrão do Windows)."""
    try:
        chrome = chrome_exe()
        if not chrome:
            raise RuntimeError("Chrome não encontrado para montar o ticket")
        pasta = os.path.join(BASE, "impressao")
        os.makedirs(pasta, exist_ok=True)
        png = os.path.join(pasta, f"ticket_{int(tid)}.png")
        if os.path.exists(png):
            os.remove(png)
        url = (f"http://127.0.0.1:{int(CONFIG.get('porta', 8080))}/?img={time.time():.0f}"
               f"#ticketimg={int(tid)}&foto={1 if foto else 0}")
        with IMPRESSAO_LOCK:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--force-device-scale-factor=2", "--window-size=794,1123", "--virtual-time-budget=15000",
                            f"--user-data-dir={os.path.join(BASE, 'chrome_impressao')}", f"--screenshot={png}", url],
                           capture_output=True, timeout=90, creationflags=SEM_JANELA)
            if not os.path.isfile(png) or os.path.getsize(png) < 5000:
                raise RuntimeError("não consegui montar a imagem do ticket")
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                os.path.join(BASE, "imprimir_ticket.ps1"), "-Imagem", png,
                                "-Impressora", CONFIG.get("impressora") or "",
                                "-Copias", str(max(1, int(CONFIG.get("vias_impressao") or 1)))],
                               capture_output=True, text=True, timeout=90, creationflags=SEM_JANELA)
            if r.returncode != 0 or "OK" not in r.stdout:
                erro = next((ln[5:].strip() for ln in r.stdout.splitlines() if ln.startswith("ERRO:")), None)
                raise RuntimeError(erro or (r.stderr or r.stdout or "erro desconhecido").strip()[-300:])
    except Exception as e:  # noqa: BLE001
        registrar_falha("falha_impressao", f"Ticket {tid}: {e}", placa)
        raise RuntimeError(str(e)) from e
    return {"ok": True, "impressora": CONFIG.get("impressora") or "padrão do Windows"}


# --------------------------------------------------------------------------
# Câmera da balança + leitura de placa
#
# O vídeo (RTSP) e a leitura de placa (fast-alpr, gratuito e local) rodam num
# programa auxiliar (camera_lpr.py) com Python próprio em lpr_venv/, porque
# precisam de OpenCV/ONNX. Este servidor continua só com a biblioteca padrão:
# ele inicia o auxiliar e repassa a foto e a placa lida para a tela.
# --------------------------------------------------------------------------
CAMERA_PY = os.path.join(BASE, "lpr_venv", "Scripts", "python.exe")
CAMERA_SCRIPT = os.path.join(BASE, "camera_lpr.py")
CAMERA = {"proc": None, "lock": threading.Lock()}
# letras que o OCR confunde com números (e vice-versa) em cada posição da placa
PARA_LETRA = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}
PARA_NUMERO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}


def camera_url_base():
    return f"http://127.0.0.1:{int(CONFIG['camera'].get('porta_auxiliar') or 8092)}"


def parar_camera():
    with CAMERA["lock"]:
        p = CAMERA["proc"]
        CAMERA["proc"] = None
    if p and p.poll() is None:
        if os.name == "nt":  # o python.exe do venv abre outro processo: fecha os dois
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def iniciar_camera():
    """(Re)inicia o programa auxiliar da câmera conforme o config.json."""
    parar_camera()
    if not CONFIG["camera"].get("ativo"):
        return
    if not os.path.isfile(CAMERA_PY):
        registrar_falha("camera", "Leitor de placas não instalado (pasta lpr_venv). Rode INSTALAR_CAMERA.bat.")
        return
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with CAMERA["lock"]:
        CAMERA["proc"] = subprocess.Popen([CAMERA_PY, CAMERA_SCRIPT, "--config", CONFIG_PATH, "--pai", str(os.getpid())], cwd=BASE,
                                          creationflags=flags)


def camera_get(caminho, timeout=4):
    with urllib.request.urlopen(camera_url_base() + caminho, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "application/octet-stream")


def camera_status():
    if not CONFIG["camera"].get("ativo"):
        return {"ativo": False}
    if not os.path.isfile(CAMERA_PY):
        return {"ativo": True, "ok": False, "mensagem": "Leitor de placas não instalado (rode INSTALAR_CAMERA.bat)"}
    try:
        corpo, _ = camera_get("/status", 2)
        return dict(json.loads(corpo), ativo=True)
    except Exception as e:  # noqa: BLE001
        p = CAMERA["proc"]
        if p is None or p.poll() is not None:
            iniciar_camera()  # o auxiliar caiu: tenta de novo
        return {"ativo": True, "ok": False, "mensagem": f"Programa da câmera iniciando… ({e})"}


def placa_padrao(texto):
    """Ajusta o texto lido pelo OCR ao formato de placa brasileira: AAA9999 (antiga) ou AAA9A99 (Mercosul)."""
    t = normalizar(texto)
    if len(t) != 7:
        return t
    c = list(t)
    for i in (0, 1, 2):
        c[i] = PARA_LETRA.get(c[i], c[i])
    for i in (3, 5, 6):
        c[i] = PARA_NUMERO.get(c[i], c[i])
    return "".join(c)


def chave_placa(placa):
    """Mesma chave para a placa antiga e a Mercosul (APZ9171 = APZ9B71): 5º caractere letra A-J vira número."""
    p = placa_padrao(placa)
    if len(p) == 7 and "A" <= p[4] <= "J":
        p = p[:4] + str(ord(p[4]) - ord("A")) + p[5:]
    return p


def buscar_por_placa(placa):
    chave = chave_placa(placa)
    with conectar() as con:
        todos = contar_por_empresa(todos_clientes(con))
        abertos = con.execute("SELECT id, placa, cliente_id FROM nova_ticket WHERE status='ABERTO' ORDER BY id DESC").fetchall()
    clientes = [dict(c, confianca=95) for c in todos if chave_placa(c["placa"]) == chave]
    ids = {c["id"] for c in clientes}
    ticket = next((t["id"] for t in abertos if chave_placa(t["placa"]) == chave or t["cliente_id"] in ids), None)
    return {"placa": placa_padrao(placa), "clientes": clientes, "ticket_aberto": ticket}


def ler_placa_camera():
    """Pede ao auxiliar a placa da imagem atual e procura o cadastro."""
    corpo, _ = camera_get("/placa", 15)
    leituras = json.loads(corpo).get("placas", [])
    validas = [x for x in leituras if (x.get("confianca") or 0) >= 0.6
               and re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}", placa_padrao(x["texto"]))]
    if not validas:
        return {"placa": None, "leituras": leituras}
    melhor = max(validas, key=lambda x: x.get("confianca") or 0)
    r = dict(buscar_por_placa(melhor["texto"]), confianca=melhor.get("confianca"), leituras=leituras)
    ULTIMA_PLACA.update(quando=time.time(), r=r)
    return r


# --------------------------------------------------------------------------
# Aviso no WhatsApp: quando um caminhão sobe na balança, espera a leitura da
# placa (a que a tela fez ou uma própria) e põe a mensagem numa fila. Quem
# envia é a extensão "whatsapp_extensao" instalada no Chrome onde o WhatsApp Web
# está conectado: ela pergunta aqui o que mandar e devolve o resultado.
# --------------------------------------------------------------------------
ULTIMA_PLACA = {"quando": 0, "r": None}
WHATS = {"fila": [], "seq": 0, "visto": 0, "estado": None, "ultimo": None, "erro": None, "enviadas": 0}
WHATS_LOCK = threading.Lock()


def numero_whatsapp(n):
    n = re.sub(r"\D", "", str(n))
    return "55" + n if len(n) in (10, 11) else n  # DDD + número, sem o 55


def enfileirar_whatsapp(numero, texto, placa=""):
    with WHATS_LOCK:
        WHATS["seq"] += 1
        WHATS["fila"].append({"id": WHATS["seq"], "numero": numero_whatsapp(numero), "texto": texto,
                              "placa": placa, "criado": time.time(), "entregue": 0})


def proximo_whatsapp(estado, so_estado=False):
    """A extensão pede a próxima mensagem (a cada 2 s, com o WhatsApp Web aberto)."""
    agora = time.time()
    WHATS.update(visto=agora, estado=estado)
    if so_estado:
        return {}
    with WHATS_LOCK:
        for m in [m for m in WHATS["fila"] if agora - m["criado"] > 900]:
            WHATS["fila"].remove(m)
            WHATS["erro"] = f"{agora_local()} — aviso para {m['numero']} descartado: o WhatsApp Web ficou 15 min sem enviar"
            registrar_falha("whatsapp", WHATS["erro"].split(" — ", 1)[1], m["placa"])
        for m in WHATS["fila"]:
            if agora - m["entregue"] > 120:  # entregue e sem resposta em 2 min: oferece de novo
                m["entregue"] = agora
                return {k: m[k] for k in ("id", "numero", "texto")}
    return {}


def resultado_whatsapp(d):
    with WHATS_LOCK:
        m = next((m for m in WHATS["fila"] if m["id"] == d.get("id")), None)
        if m:
            WHATS["fila"].remove(m)
    if not m:
        return
    if d.get("ok"):
        WHATS.update(ultimo=agora_local(), erro=None)
        WHATS["enviadas"] += 1
    else:
        WHATS["erro"] = f"{agora_local()} — aviso para {m['numero']} não enviado: {d.get('erro') or 'erro'}"
        registrar_falha("whatsapp", WHATS["erro"].split(" — ", 1)[1], m["placa"])


def status_whatsapp():
    aberto = time.time() - WHATS["visto"] < 15
    return {"estado": (WHATS["estado"] or "carregando") if aberto else "fechado", "fila": len(WHATS["fila"]),
            "ultimo": WHATS["ultimo"], "erro": WHATS["erro"], "enviadas": WHATS["enviadas"]}


def numeros_whatsapp():
    return [n.strip() for n in re.split(r"[,;\n]", (CONFIG.get("whatsapp") or {}).get("numeros") or "") if n.strip()]


def kg(v):
    return f"{int(round(v or 0)):,}".replace(",", ".")


def texto_aviso(r, b):
    linhas = ["🚛 *Caminhão entrou na balança*", ""]
    if r and r.get("placa"):
        linhas.append(f"Placa: *{r['placa']}*")
        c = (r.get("clientes") or [None])[0]
        if c:
            linhas.append(f"Motorista: {c.get('motorista') or c.get('nome')}")
            if c.get("empresa") and c["empresa"] != (c.get("motorista") or c.get("nome")):
                linhas.append(f"Empresa: {c['empresa']}")
        else:
            linhas.append("(placa sem cadastro)")
    else:
        linhas.append("Placa: não lida pela câmera")
    if b.get("ok") and b.get("peso") is not None:
        linhas.append(f"Peso agora: {kg(b['peso'])} kg")
    linhas.append(f"Horário: {datetime.now():%d/%m/%Y %H:%M}")
    link = ((CONFIG.get("whatsapp") or {}).get("link") or "").strip()
    if link:
        linhas += ["", f"Acompanhe a pesagem: {link}"]
    return "\n".join(linhas)


def avisar_entrada(inicio):
    cfg, cam = CONFIG.get("whatsapp") or {}, CONFIG.get("camera") or {}
    r = None
    if cam.get("ativo") and cam.get("ler_placa"):
        limite = inicio + int(cfg.get("espera_placa") or 25)
        while time.time() < limite:
            if ULTIMA_PLACA["quando"] >= inicio - 5:  # a tela (ou a leitura daqui) já achou a placa
                r = ULTIMA_PLACA["r"]
                break
            if time.time() - inicio > 6:  # a tela não leu (ou está fechada): lê aqui
                try:
                    if ler_placa_camera().get("placa"):
                        continue
                except (urllib.error.URLError, OSError, ValueError):
                    pass
            time.sleep(2)
    texto = texto_aviso(r, ler_balanca())
    for n in numeros_whatsapp():
        enfileirar_whatsapp(n, texto, (r or {}).get("placa") or "")


def vigiar_balanca():
    """Percebe a chegada do caminhão (peso acima do mínimo da câmera)."""
    na_balanca, vazio_desde = False, None
    while True:
        time.sleep(1)
        if not (CONFIG.get("whatsapp") or {}).get("ativo"):
            na_balanca = False
            continue
        b = ler_balanca()
        if not b["ok"] or b["peso"] is None:
            continue
        minimo = num((CONFIG.get("camera") or {}).get("peso_minimo"))
        if b["peso"] >= (100 if minimo is None else minimo):
            vazio_desde = None
            if not na_balanca:
                na_balanca = True
                threading.Thread(target=avisar_entrada, args=(time.time(),), daemon=True).start()
        else:
            vazio_desde = vazio_desde or time.time()
            if time.time() - vazio_desde >= 10:  # só conta como saída depois de 10 s vazia
                na_balanca = False


# --------------------------------------------------------------------------
# Espelho na internet (VPS): este computador continua sendo o sistema principal.
# Ele mesmo pergunta à VPS "tem algum pedido para mim?" e responde com o que o
# servidor local devolveria (não precisa abrir porta no roteador). Sem internet,
# nada muda aqui.
# --------------------------------------------------------------------------
ESPELHO = {"conectado": False, "ultimo": None, "erro": None, "pedidos": 0}


def bloqueado_remoto(metodo, caminho):
    """O que não pode ser feito pela internet (a VPS também bloqueia)."""
    p = urllib.parse.urlsplit(caminho).path
    return p.startswith("/api/backups") or (p.startswith("/api/config") and metodo != "GET")


def executar_pedido_remoto(p):
    metodo, caminho = p.get("metodo", "GET"), p.get("caminho", "/")
    if bloqueado_remoto(metodo, caminho) or not caminho.startswith("/"):
        corpo = json.dumps({"erro": "Isso só pode ser feito no computador da balança."}).encode()
        return {"id": p.get("id"), "status": 403, "cabecalhos": {"Content-Type": "application/json; charset=utf-8"},
                "corpo": base64.b64encode(corpo).decode()}
    dados = base64.b64decode(p.get("corpo") or "") if metodo in ("POST", "PUT", "DELETE") else None
    cab = {"X-Espelho": "1"}
    if p.get("tipo"):
        cab["Content-Type"] = p["tipo"]
    req = urllib.request.Request(f"http://127.0.0.1:{int(CONFIG.get('porta', 8080))}{caminho}",
                                 data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=55) as r:
            status, corpo, h = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, corpo, h = e.code, e.read(), e.headers
    cabecalhos = {k: h.get(k) for k in ("Content-Type", "Content-Disposition") if h.get(k)}
    return {"id": p.get("id"), "status": status, "cabecalhos": cabecalhos, "corpo": base64.b64encode(corpo).decode()}


def trabalhador_espelho():
    ctx = ssl.create_default_context()
    while True:
        cfg = CONFIG.get("espelho") or {}
        if not (cfg.get("ativo") and cfg.get("url") and cfg.get("token")):
            ESPELHO["conectado"] = False
            time.sleep(5)
            continue
        base = cfg["url"].rstrip("/")
        cab = {"X-Agente-Token": cfg["token"], "User-Agent": "BalancaTranstino-Agente/1.0"}
        try:
            req = urllib.request.Request(base + "/_agente/proximo", headers=cab)
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                texto = r.read() if r.status == 200 else b""
            ESPELHO.update(conectado=True, ultimo=agora_local(), erro=None)
            if not texto:
                continue
            resposta = executar_pedido_remoto(json.loads(texto))
            ESPELHO["pedidos"] += 1
            req = urllib.request.Request(base + "/_agente/resposta", data=json.dumps(resposta).encode(), method="POST",
                                         headers=dict(cab, **{"Content-Type": "application/json"}))
            urllib.request.urlopen(req, timeout=40, context=ctx).read()
        except Exception as e:  # noqa: BLE001
            if ESPELHO["conectado"] or ESPELHO["erro"] is None:
                print(f"Espelho: sem conexão com {base} ({e})")
            ESPELHO.update(conectado=False, erro=str(e)[:200])
            time.sleep(5)


# --------------------------------------------------------------------------
# InControl (leitura de tags) - API https://localhost:4441/v1/
# --------------------------------------------------------------------------
class InControl:
    def __init__(self):
        self.token = None
        self.esquema = None
        self.lock = threading.Lock()
        self.ctx = ssl._create_unverified_context()

    def _req(self, metodo, caminho, corpo=None, auth=True):
        cfg = CONFIG["incontrol"]
        url = cfg["url"].rstrip("/") + caminho
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"{self.esquema} {self.token}"
        data = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(url, data=data, method=metodo, headers=headers)
        with urllib.request.urlopen(req, timeout=6, context=self.ctx) as r:
            return json.loads(r.read().decode("utf-8", "ignore") or "null")

    def login(self):
        cfg = CONFIG["incontrol"]
        resp = self._req("POST", "/v1/auth/", {"username": cfg["usuario"], "password": cfg["senha"]}, auth=False)
        token = (resp or {}).get("token") or (resp or {}).get("access")
        if not token:
            raise RuntimeError(f"Login no InControl recusado: {resp}")
        self.token = token
        self.esquema = None

    def get(self, caminho):
        with self.lock:
            if not self.token:
                self.login()
            esquemas = [self.esquema] if self.esquema else ["JWT", "Bearer", "Token"]
            ultimo_erro = None
            for esq in esquemas:
                self.esquema = esq
                try:
                    return self._req("GET", caminho)
                except urllib.error.HTTPError as e:
                    ultimo_erro = e
                    if e.code not in (401, 403):
                        raise
            self.token = None  # força novo login na próxima
            self.esquema = None
            raise ultimo_erro

    def ultimo_evento(self):
        resp = self.get("/v1/evento/?limit=10&offset=0&ordering=-id")
        itens = resp.get("results", resp) if isinstance(resp, dict) else resp
        if not itens:
            return None, resp
        if isinstance(itens, dict):
            itens = [itens]

        def chave(ev):
            for k in ("id", "data_evento", "data", "data_hora", "created_at"):
                if k in ev and ev[k] is not None:
                    return str(ev[k]).zfill(20)
            return ""

        return sorted(itens, key=chave, reverse=True)[0], resp


INCONTROL = InControl()
PADRAO_USUARIO = re.compile(r"^[A-Za-zÀ-ú0-9 ().]+\s*-\s*\d+\s*$")


def extrair_usuario(ev):
    """Procura no evento o nome do usuário no formato 'NOME - 41'."""
    candidatos = []

    def varrer(obj, chave=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                varrer(v, k.lower())
        elif isinstance(obj, list):
            for v in obj:
                varrer(v, chave)
        elif isinstance(obj, str) and obj.strip():
            peso = 0
            if PADRAO_USUARIO.match(obj.strip()):
                peso += 10
            if any(p in chave for p in ("usuario", "user", "pessoa", "nome", "name")):
                peso += 5
            if peso:
                candidatos.append((peso, obj.strip()))

    varrer(ev)
    candidatos.sort(key=lambda x: -x[0])
    return candidatos[0][1] if candidatos else None


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
CAMPOS_TICKET = [
    "emissor", "cliente_id", "tag", "placa", "transportadora", "motorista", "item",
    "peso_inicial", "data_inicial", "operador_inicial", "balanca_inicial", "origem_inicial",
    "peso_final", "data_final", "operador_final", "balanca_final", "origem_final",
    "peso_origem", "local_descarga", "observacao",
    "empresa_id", "pagador", "pagador_nome", "valor_manual",
]


def ticket_calculado(t):
    t = dict(t)
    pi, pf = t.get("peso_inicial"), t.get("peso_final")
    if pi is not None and pf is not None:
        t["peso_liquido"] = abs(pf - pi)
        t["tara"] = min(pi, pf)
        t["bruto"] = max(pi, pf)
    origem = t.get("peso_origem")
    if t.get("peso_liquido") is not None and origem:
        dif = t["peso_liquido"] - origem
        t["diferenca_origem"] = dif
        t["diferenca_pct"] = round(dif / origem * 100, 2) if origem else 0
    else:
        t["diferenca_origem"] = 0
        t["diferenca_pct"] = 0
    if t.get("id"):
        t["foto"] = os.path.isfile(caminho_foto(t["id"]))
    return t


def caminho_foto(tid):
    return os.path.join(FOTOS_DIR, f"ticket_{int(tid)}.jpg")


def guardar_foto_ticket(tid):
    """Guarda a imagem atual da câmera (pequena) para sair no ticket. Sem câmera, não faz nada."""
    if not CONFIG["camera"].get("ativo"):
        return False
    for tentativa in range(3):
        try:
            corpo, _ = camera_get("/foto.jpg?w=640&idade=30", 4)
            break
        except (urllib.error.URLError, OSError) as e:
            print(f"Foto do ticket {tid}: câmera não respondeu ({e}), tentativa {tentativa + 1}")
            time.sleep(1)
    else:
        registrar_falha("foto", f"Ticket {tid}: a câmera não entregou a foto")
        return False
    os.makedirs(FOTOS_DIR, exist_ok=True)
    with open(caminho_foto(tid), "wb") as f:
        f.write(corpo)
    return True


def obter_ticket(con, tid):
    row = con.execute("SELECT * FROM nova_ticket WHERE id = ?", (tid,)).fetchone()
    return ticket_calculado(row) if row else None


def registrar_historico_antigo(con, t):
    """Grava também em pesagem_pesagem para aparecer nos relatórios do sistema antigo."""
    email = "Desconhecido"
    modelo = None
    if t.get("cliente_id"):
        c = con.execute("SELECT email, modelo FROM pesagem_cliente WHERE id = ?", (t["cliente_id"],)).fetchone()
        if c:
            email, modelo = c["email"] or email, c["modelo"]
    agora = agora_utc_django()
    cur = con.execute(
        """INSERT INTO pesagem_pesagem (placa, tag_rfid, modelo, cor, cadastrado_em, user_name, user_email,
                                        peso_final, peso_liquido, peso_maximo, data_pesagem)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ((t.get("placa") or "")[:10], (t.get("tag") or f"MANUAL-{t['id']}")[:50], modelo, "PESAGEM_NOVA",
         agora, (t.get("motorista") or t.get("transportadora") or "Manual")[:100], email[:100],
         t["bruto"], t["peso_liquido"], t["tara"], agora),
    )
    return cur.lastrowid


def atualizar_historico_antigo(con, t):
    """Mantém a cópia do ticket em pesagem_pesagem igual ao ticket editado."""
    if not t.get("pesagem_legado_id"):
        return
    con.execute(
        """UPDATE pesagem_pesagem SET placa=?, user_name=?, peso_final=?, peso_liquido=?, peso_maximo=?
           WHERE id=?""",
        ((t.get("placa") or "")[:10], (t.get("motorista") or t.get("transportadora") or "Manual")[:100],
         t["bruto"], t["peso_liquido"], t["tara"], t["pesagem_legado_id"]),
    )


def excluir_ticket(tid):
    with conectar() as con:
        t = obter_ticket(con, tid)
        if not t:
            raise ValueError("Ticket não encontrado.")
        if t.get("pesagem_legado_id"):
            con.execute("DELETE FROM pesagem_pesagem WHERE id = ?", (t["pesagem_legado_id"],))
        con.execute("DELETE FROM nova_ticket WHERE id = ?", (tid,))
    return {"ok": True, "id": tid}


def salvar_ticket(dados, tid=None):
    valores = {c: dados[c] for c in CAMPOS_TICKET if c in dados}
    for c in ("peso_inicial", "peso_final", "peso_origem", "valor_manual"):
        if c in valores:
            valores[c] = num(valores[c])
    if "empresa_id" in valores:
        valores["empresa_id"] = int(num(valores["empresa_id"])) if str(valores["empresa_id"] or "").strip() else None
    for c in ("placa",):
        if valores.get(c):
            valores[c] = str(valores[c]).upper().strip()
    agora = agora_local()
    if valores.get("peso_inicial") is not None and not valores.get("data_inicial"):
        valores["data_inicial"] = agora
    if valores.get("peso_final") is not None and not valores.get("data_final"):
        valores["data_final"] = agora
    valores["atualizado_em"] = agora

    with conectar() as con:
        # par motorista + empresa: o nome da empresa vem do cadastro de empresas
        if "empresa_id" in valores:
            if valores["empresa_id"]:
                e = con.execute("SELECT nome FROM nova_empresa WHERE id = ?", (valores["empresa_id"],)).fetchone()
                if not e:
                    raise ValueError("Empresa não encontrada no cadastro.")
                valores["empresa_nome"] = valores["transportadora"] = e["nome"]
            else:
                valores["empresa_nome"] = None
        if "pagador" in valores:
            if valores["pagador"] not in ("EMPRESA", "MOTORISTA"):
                raise ValueError("Informe quem paga: empresa ou motorista.")
            if valores["pagador"] == "EMPRESA":
                if not valores.get("empresa_nome"):
                    raise ValueError("Para cobrar da empresa, selecione a empresa.")
                valores["pagador_nome"] = valores["empresa_nome"]
            elif not str(valores.get("pagador_nome") or "").strip():
                valores["pagador_nome"] = valores.get("motorista") or valores.get("placa")
        if tid:
            atual = con.execute("SELECT status FROM nova_ticket WHERE id = ?", (tid,)).fetchone()
            if not atual:
                raise ValueError("Ticket não encontrado.")
            if atual["status"] != "ABERTO" and not dados.get("editar"):
                raise ValueError(f"Ticket {tid} já está {atual['status'].lower()}.")
            sets = ", ".join(f"{c} = ?" for c in valores)
            con.execute(f"UPDATE nova_ticket SET {sets} WHERE id = ?", (*valores.values(), tid))
        else:
            if valores.get("peso_inicial") is None:
                raise ValueError("Informe o peso inicial.")
            valores["criado_em"] = agora
            cols = ", ".join(valores)
            marks = ", ".join("?" for _ in valores)
            tid = con.execute(f"INSERT INTO nova_ticket ({cols}) VALUES ({marks})", tuple(valores.values())).lastrowid

        t = obter_ticket(con, tid)
        if t["peso_inicial"] is None:
            raise ValueError("Informe o peso inicial.")
        if t["status"] == "ENCERRADO":
            # edição de ticket já encerrado: recalcula e acerta o histórico antigo
            if t.get("peso_final") is None:
                raise ValueError("Ticket encerrado precisa do peso final.")
            con.execute("UPDATE nova_ticket SET peso_liquido=? WHERE id=?", (t["peso_liquido"], tid))
            atualizar_historico_antigo(con, t)
            t = obter_ticket(con, tid)
        elif dados.get("encerrar") and t.get("peso_final") is not None:
            legado = registrar_historico_antigo(con, t) if CONFIG.get("registrar_no_historico_antigo") else None
            con.execute(
                "UPDATE nova_ticket SET status='ENCERRADO', peso_liquido=?, pesagem_legado_id=? WHERE id=?",
                (t["peso_liquido"], legado, tid),
            )
            t = obter_ticket(con, tid)
    return t


def listar_tickets(status=None, q="", limite=200):
    sql = "SELECT * FROM nova_ticket WHERE 1=1"
    args = []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if q:
        sql += (" AND (placa LIKE ? OR motorista LIKE ? OR transportadora LIKE ? OR item LIKE ?"
                " OR empresa_nome LIKE ? OR pagador_nome LIKE ? OR CAST(id AS TEXT) = ?)")
        args += [f"%{q}%"] * 6 + [q]
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limite)
    with conectar() as con:
        return [ticket_calculado(r) for r in con.execute(sql, args).fetchall()]


def historico_antigo(q="", limite=200):
    sql = "SELECT * FROM pesagem_pesagem"
    args = []
    if q:
        sql += " WHERE placa LIKE ? OR user_name LIKE ?"
        args = [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limite)
    with conectar() as con:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        ligados = dict(con.execute(
            "SELECT pesagem_legado_id, id FROM nova_ticket WHERE pesagem_legado_id IS NOT NULL").fetchall())
    for r in rows:
        r["data_local"] = utc_para_local(r.get("data_pesagem") or r.get("cadastrado_em"))
        r["ticket_id"] = ligados.get(r["id"])  # registro gerado por um ticket do sistema novo
    return rows


def historico_cobranca(q, inicio="", fim=""):
    """
    Pesagens do histórico antigo de uma empresa ou motorista, para escolher e cobrar.
    A empresa vem do cadastro da placa (inclusive cadastros ocultos/unificados).
    """
    alvo = normalizar(q)
    if len(alvo) < 2:
        raise ValueError("Digite o nome da empresa, do motorista ou a placa.")
    with conectar() as con:
        clientes = todos_clientes(con, inativos=True)
        rows = [dict(r) for r in con.execute("SELECT * FROM pesagem_pesagem ORDER BY id")]
    por_placa = {}
    for c in sorted(clientes, key=lambda c: c["inativo"]):  # o cadastro ativo tem preferência
        por_placa.setdefault(chave_placa(c["placa"]), c)
    achados = []
    for r in rows:
        data = utc_para_local(r.get("data_pesagem") or r.get("cadastrado_em")) or ""
        if (inicio and data[:10] < inicio) or (fim and data[:10] > fim):
            continue
        c = por_placa.get(chave_placa(r["placa"])) or {}
        empresa = c.get("empresa") or ""
        motorista = c.get("motorista") or r.get("user_name") or ""
        if not any(alvo in normalizar(v) for v in (r.get("user_name"), empresa, motorista, c.get("nome")))                 and chave_placa(r["placa"]) != chave_placa(q):
            continue
        achados.append({"id": r["id"], "data": data, "placa": r["placa"], "nome": r.get("user_name") or "",
                        "motorista": motorista, "empresa": empresa, "empresa_id": c.get("empresa_id"),
                        "modelo": r.get("modelo") or "", "tara": r.get("peso_maximo"), "peso_final": r.get("peso_final"),
                        "liquido": r.get("peso_liquido")})
    achados.sort(key=lambda x: x["data"], reverse=True)
    empresas = sorted({x["empresa"] for x in achados if x["empresa"]})
    return {"q": q, "inicio": inicio, "fim": fim, "pesagens": achados, "empresas": empresas}


def relatorio_pesagens(inicio, fim, empresa="", q="", motorista="", pagador=""):
    """
    Junta as pesagens do sistema antigo (pesagem_pesagem) com os tickets encerrados
    do sistema novo. Registros do histórico que vieram de um ticket novo não são
    contados duas vezes. Datas inicio/fim em 'AAAA-MM-DD' (hora local).
    """
    ini_local, fim_local = f"{inicio} 00:00:00", f"{fim} 23:59:59"
    ini_utc = local_para_utc(ini_local)[:19]
    fim_utc = local_para_utc(fim_local)[:19] + ".999999"
    with conectar() as con:
        clientes = todos_clientes(con, True)
        por_id = {c["id"]: c for c in clientes}
        por_placa = {}
        for c in sorted(clientes, key=lambda c: not c["inativo"]):  # cadastro ativo tem preferência
            por_placa[normalizar(c["placa"])] = c
        ligados = {r[0] for r in con.execute(
            "SELECT pesagem_legado_id FROM nova_ticket WHERE pesagem_legado_id IS NOT NULL")}
        antigos = con.execute(
            """SELECT * FROM pesagem_pesagem
               WHERE COALESCE(data_pesagem, cadastrado_em) BETWEEN ? AND ?""", (ini_utc, fim_utc)).fetchall()
        novos = con.execute(
            """SELECT * FROM nova_ticket WHERE status = 'ENCERRADO' AND data_final BETWEEN ? AND ?""",
            (ini_local, fim_local)).fetchall()

    def atual(c):
        # cadastro unificado (oculto) -> usa o cadastro que ficou
        for _ in range(5):
            if not (c and c.get("unificado_em") in por_id):
                break
            c = por_id[c["unificado_em"]]
        return c

    def cobranca(c, nome_padrao):
        if c:
            return c["pagador"], c["pagador_nome"], c["plano_id"] if c["pagador"] == "MOTORISTA" else None
        return "MOTORISTA", empresa_automatica(nome_padrao), None

    linhas = []
    for r in antigos:
        if r["id"] in ligados:
            continue
        c = atual(por_placa.get(normalizar(r["placa"])))
        tipo, quem, plano = cobranca(c, r["user_name"])
        linhas.append({
            "origem": "antigo", "id": r["id"], "numero": f"H{r['id']}", "ref": f"antigo:{r['id']}",
            "data": utc_para_local(r["data_pesagem"] or r["cadastrado_em"]),
            "placa": r["placa"], "motorista": r["user_name"], "item": (c or {}).get("descricao_carga") or "",
            "empresa": c["empresa"] if c else empresa_automatica(r["user_name"]),
            "pagador_tipo": tipo, "pagador": quem, "plano_id": plano, "valor_manual": None,
            "tara": r["peso_maximo"], "bruto": r["peso_final"], "liquido": r["peso_liquido"],
        })
    for t in novos:
        t = ticket_calculado(t)
        c = atual(por_id.get(t["cliente_id"]) or por_placa.get(normalizar(t["placa"])))
        if t.get("pagador"):
            tipo, quem = t["pagador"], t.get("pagador_nome") or t.get("empresa_nome") or t["motorista"]
            plano = c["plano_id"] if c and tipo == "MOTORISTA" else None
        else:  # tickets feitos antes do cadastro de empresas: segue o cadastro
            tipo, quem, plano = cobranca(c, t["transportadora"] or t["motorista"])
        linhas.append({
            "origem": "novo", "id": t["id"], "numero": str(t["id"]), "ref": f"novo:{t['id']}", "data": t["data_final"],
            "placa": t["placa"], "motorista": t["motorista"], "item": t["item"] or "",
            "empresa": t.get("empresa_nome") or (c["empresa"] if c else empresa_automatica(t["transportadora"] or t["motorista"])),
            "pagador_tipo": tipo, "pagador": quem, "plano_id": plano, "valor_manual": t.get("valor_manual"),
            "tara": t.get("tara"), "bruto": t.get("bruto"), "liquido": t.get("peso_liquido"),
        })

    for campo, filtro in (("empresa", empresa), ("motorista", motorista), ("pagador", pagador)):
        if filtro:
            alvo = normalizar(filtro)
            linhas = [x for x in linhas if alvo in normalizar(x[campo])]
    if q:
        alvo = normalizar(q)
        linhas = [x for x in linhas if any(alvo in normalizar(x[k]) for k in ("placa", "motorista", "item", "numero"))]
    linhas.sort(key=lambda x: x["data"] or "", reverse=True)

    def agrupar(chave):
        g = {}
        for x in linhas:
            k = chave(x)
            a = g.setdefault(k, {"chave": k, "pesagens": 0, "liquido": 0.0, "placas": set()})
            a["pesagens"] += 1
            a["liquido"] += x["liquido"] or 0
            a["placas"].add(normalizar(x["placa"]))
        for a in g.values():
            a["caminhoes"] = len(a.pop("placas"))
        return list(g.values())

    total = sum(x["liquido"] or 0 for x in linhas)
    return {
        "inicio": inicio, "fim": fim, "empresa": empresa, "q": q, "motorista": motorista, "pagador": pagador,
        "totais": {"pesagens": len(linhas), "liquido": total,
                   "media": total / len(linhas) if linhas else 0,
                   "caminhoes": len({normalizar(x["placa"]) for x in linhas}),
                   "empresas": len({x["empresa"] for x in linhas})},
        "por_empresa": sorted(agrupar(lambda x: x["empresa"]), key=lambda a: -a["liquido"]),
        "por_motorista": sorted(agrupar(lambda x: x["motorista"] or "—"), key=lambda a: -a["liquido"]),
        "por_pagador": sorted(agrupar(lambda x: x["pagador"] or "—"), key=lambda a: -a["liquido"]),
        "por_dia": sorted(agrupar(lambda x: (x["data"] or "")[:10]), key=lambda a: a["chave"]),
        "linhas": linhas,
    }


def relatorio_csv(rel):
    def br(v):
        return "" if v is None else f"{v:.0f}".replace(".", ",")
    out = ["Nº;Data;Placa;Empresa;Motorista;Cobrar de;Pagador;Item;TARA (kg);Bruto (kg);Líquido (kg);Origem"]
    for x in rel["linhas"]:
        campos = [x["numero"], x["data"] or "", x["placa"] or "", x["empresa"] or "", x["motorista"] or "",
                  "Empresa" if x["pagador_tipo"] == "EMPRESA" else "Motorista", x["pagador"] or "",
                  x["item"] or "", br(x["tara"]), br(x["bruto"]), br(x["liquido"]),
                  "sistema antigo" if x["origem"] == "antigo" else "sistema novo"]
        out.append(";".join(str(c).replace(";", ",").replace("\n", " ") for c in campos))
    out.append(f";;;;;;;;;TOTAL;{br(rel['totais']['liquido'])};{rel['totais']['pesagens']} pesagens")
    return ("\ufeff" + "\r\n".join(out)).encode("utf-8")  # BOM: Excel abre com acentos certos


def dashboard(dias=30):
    """Indicadores do dashboard: período escolhido, comparação com o período anterior,
    12 meses, rankings, mapa de calor, pátio, qualidade dos cadastros e sistema."""
    dias = max(1, min(int(dias), 366))
    hoje = datetime.now().date()
    ini = hoje - timedelta(days=dias - 1)
    ant_ini, ant_fim = ini - timedelta(days=dias), ini - timedelta(days=1)
    y, m = hoje.year, hoje.month - 11
    while m <= 0:
        m += 12
        y -= 1
    ini12 = datetime(y, m, 1).date()
    base = relatorio_pesagens(min(ini12, ant_ini).isoformat(), hoje.isoformat())
    linhas = base["linhas"]

    def entre(a, b):
        a, b = a.isoformat(), b.isoformat()
        return [x for x in linhas if x["data"] and a <= x["data"][:10] <= b]

    def soma(rows):
        tot = sum(x["liquido"] or 0 for x in rows)
        return {"pesagens": len(rows), "liquido": tot, "media": tot / len(rows) if rows else 0,
                "caminhoes": len({normalizar(x["placa"]) for x in rows}),
                "empresas": len({x["empresa"] for x in rows})}

    per = entre(ini, hoje)
    mes_ini = hoje.replace(day=1)

    por_dia = []
    for i in range(dias):
        d = (ini + timedelta(days=i)).isoformat()
        rows = [x for x in per if x["data"][:10] == d]
        por_dia.append({"dia": d, "pesagens": len(rows), "liquido": sum(x["liquido"] or 0 for x in rows)})

    por_mes = []
    yy, mm = ini12.year, ini12.month
    for _ in range(12):
        chave = f"{yy}-{mm:02d}"
        rows = [x for x in linhas if (x["data"] or "")[:7] == chave]
        por_mes.append({"mes": chave, "pesagens": len(rows), "liquido": sum(x["liquido"] or 0 for x in rows)})
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1

    def ranking(chave, n, extra=None):
        g = {}
        for x in per:
            k = chave(x)
            a = g.setdefault(k, {"nome": k, "pesagens": 0, "liquido": 0.0})
            a["pesagens"] += 1
            a["liquido"] += x["liquido"] or 0
            if extra:
                extra(a, x)
        return sorted(g.values(), key=lambda a: -a["liquido"])[:n]

    def info_caminhao(a, x):
        a["placa"], a["empresa"] = x["placa"], x["empresa"]

    calor = [[0] * 24 for _ in range(7)]
    for x in per:
        try:
            dt = datetime.fromisoformat(x["data"])
            calor[dt.weekday()][dt.hour] += 1
        except ValueError:
            pass

    with conectar() as con:
        clientes = todos_clientes(con)
        total_hist = con.execute("SELECT COUNT(*), COALESCE(SUM(peso_liquido), 0) FROM pesagem_pesagem").fetchone()
        primeira = con.execute("SELECT MIN(COALESCE(data_pesagem, cadastrado_em)) FROM pesagem_pesagem").fetchone()[0]
    por_placa = {}
    for c in clientes:
        por_placa.setdefault(normalizar(c["placa"]), []).append(c)
    empresas = {}
    for c in clientes:
        empresas[c["empresa"]] = empresas.get(c["empresa"], 0) + 1
    duplicadas = [{"placa": v[0]["placa"], "nomes": [c["nome"] for c in v]}
                  for k, v in por_placa.items() if k and len(v) > 1]
    sem_tara = [{"id": c["id"], "nome": c["nome"], "placa": c["placa"]} for c in clientes if not (c["peso_maximo"] or 0) > 0]
    sem_tag = [{"id": c["id"], "nome": c["nome"], "placa": c["placa"]} for c in clientes
               if str(c.get("card_no") or "").strip() in ("", "0")]

    abertos = [{"id": t["id"], "placa": t["placa"], "motorista": t["motorista"], "peso_inicial": t["peso_inicial"],
                "data_inicial": t["data_inicial"]} for t in listar_tickets("ABERTO", limite=20)]

    return {
        "dias": dias, "inicio": ini.isoformat(), "fim": hoje.isoformat(),
        "periodo": soma(per), "anterior": soma(entre(ant_ini, ant_fim)),
        "hoje": soma(entre(hoje, hoje)), "mes": soma(entre(mes_ini, hoje)),
        "doze_meses": soma(entre(ini12, hoje)),
        "por_dia": por_dia, "por_mes": por_mes, "calor": calor,
        "top_empresas": ranking(lambda x: x["empresa"] or "SEM EMPRESA", 10),
        "top_itens": ranking(lambda x: (x["item"] or "SEM ITEM").strip().upper(), 8),
        "top_caminhoes": ranking(lambda x: normalizar(x["placa"]), 8, info_caminhao),
        "ultimas": linhas[:8],
        "abertos": abertos,
        "cadastros": {"total": len(clientes), "empresas": len(empresas),
                      "empresas_cadastradas": len({c["empresa_id"] for c in clientes if c["empresa_id"]}),
                      "empresas_frota": sum(1 for v in empresas.values() if v > 1),
                      "maior_frota": max(empresas.items(), key=lambda kv: kv[1]) if empresas else None,
                      "sem_tara": sem_tara, "sem_tag": sem_tag, "placas_duplicadas": duplicadas},
        "historico": {"pesagens": total_hist[0], "liquido": total_hist[1], "desde": utc_para_local(primeira)},
        "backup": resumo_backup(),
    }


def obter_historico(con, hid):
    row = con.execute("SELECT * FROM pesagem_pesagem WHERE id = ?", (hid,)).fetchone()
    if not row:
        return None
    r = dict(row)
    r["data_local"] = utc_para_local(r.get("data_pesagem") or r.get("cadastrado_em"))
    return r


def editar_historico(hid, dados):
    """Edita uma pesagem do sistema antigo. Líquido = peso final - TARA (mesma conta do sistema antigo)."""
    with conectar() as con:
        atual = obter_historico(con, hid)
        if not atual:
            raise ValueError("Registro não encontrado.")
        tara = num(dados.get("peso_maximo")) if "peso_maximo" in dados else atual["peso_maximo"]
        final = num(dados.get("peso_final")) if "peso_final" in dados else atual["peso_final"]
        if tara is None or final is None:
            raise ValueError("Informe a TARA e o peso final.")
        valores = {"peso_maximo": tara, "peso_final": final, "peso_liquido": final - tara}
        for c in ("placa", "user_name", "user_email", "modelo"):
            if c in dados:
                valores[c] = str(dados[c] or "").strip()
        if valores.get("placa") is not None:
            valores["placa"] = valores["placa"].upper()[:10]
            if not valores["placa"]:
                raise ValueError("Informe a placa.")
        for c in ("user_name", "user_email"):
            if c in valores and not valores[c]:
                valores[c] = "Desconhecido"
        if dados.get("data_local"):
            valores["data_pesagem"] = local_para_utc(dados["data_local"])
        sets = ", ".join(f"{c} = ?" for c in valores)
        con.execute(f"UPDATE pesagem_pesagem SET {sets} WHERE id = ?", (*valores.values(), hid))
        return obter_historico(con, hid)


def excluir_historico(hid):
    with conectar() as con:
        if not obter_historico(con, hid):
            raise ValueError("Registro não encontrado.")
        con.execute("UPDATE nova_ticket SET pesagem_legado_id = NULL WHERE pesagem_legado_id = ?", (hid,))
        con.execute("DELETE FROM pesagem_pesagem WHERE id = ?", (hid,))
    return {"ok": True, "id": hid}


def resumo_hoje():
    hoje = datetime.now().strftime("%Y-%m-%d")
    with conectar() as con:
        r = con.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(peso_liquido),0) total FROM nova_ticket
               WHERE status='ENCERRADO' AND substr(data_final,1,10)=?""", (hoje,)).fetchone()
        abertos = con.execute("SELECT COUNT(*) FROM nova_ticket WHERE status='ABERTO'").fetchone()[0]
        clientes = con.execute("SELECT COUNT(*) FROM pesagem_cliente").fetchone()[0]
        legado = con.execute("SELECT COUNT(*) FROM pesagem_pesagem").fetchone()[0]
    return {"tickets_hoje": r["n"], "liquido_hoje": r["total"], "abertos": abertos,
            "cadastros": clientes, "historico_antigo": legado}


# --------------------------------------------------------------------------
# Backup automático do banco (cópia segura com a API de backup do SQLite,
# funciona mesmo com o sistema antigo e o novo usando o banco ao mesmo tempo)
# --------------------------------------------------------------------------
BACKUP_LOCK = threading.Lock()
ULTIMO_BACKUP = {"arquivo": None, "quando": None, "erro": None}
PADRAO_BACKUP = re.compile(r"^db_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_[a-z_]+)?\.sqlite3$")


def pasta_backup():
    p = CONFIG["backup"]["pasta"]
    p = p if os.path.isabs(p) else os.path.normpath(os.path.join(BASE, p))
    os.makedirs(p, exist_ok=True)
    return p


def info_backup(caminho):
    st = os.stat(caminho)
    nome = os.path.basename(caminho)
    m = re.search(r"_([a-z_]+)\.sqlite3$", nome)
    return {"nome": nome, "tamanho": st.st_size, "motivo": m.group(1) if m else "automático",
            "quando": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")}


def listar_backups():
    pasta = pasta_backup()
    arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if PADRAO_BACKUP.match(f)]
    arquivos.sort(key=os.path.getmtime, reverse=True)
    return [info_backup(a) for a in arquivos]


def caminho_backup(nome):
    if not PADRAO_BACKUP.match(nome or ""):
        raise ValueError("Nome de backup inválido.")
    caminho = os.path.join(pasta_backup(), nome)
    if not os.path.isfile(caminho):
        raise ValueError("Backup não encontrado.")
    return caminho


def abrir_somente_leitura(caminho):
    # modo "ro": se o arquivo não existir dá erro, em vez de criar um banco vazio
    if not os.path.isfile(caminho):
        raise ValueError(f"Arquivo não encontrado: {caminho}")
    uri = "file:" + urllib.request.pathname2url(os.path.abspath(caminho)) + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def copiar_banco(origem, destino):
    src = origem if isinstance(origem, sqlite3.Connection) else abrir_somente_leitura(origem)
    dst = sqlite3.connect(destino, timeout=30)
    try:
        src.backup(dst)
        return dst.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        dst.close()
        src.close()


def limpar_backups_antigos():
    """
    Automáticos: mantém os N mais recentes. "Antes de restaurar": mantém os 10 últimos.
    Backups manuais nunca são apagados.
    """
    manter = max(1, int(CONFIG["backup"].get("manter") or 60))
    todos = listar_backups()
    sobrando = [b for b in todos if b["motivo"] == "automático"][manter:]
    sobrando += [b for b in todos if b["motivo"] == "antes_restaurar"][10:]
    for b in sobrando:
        try:
            os.remove(os.path.join(pasta_backup(), b["nome"]))
        except OSError:
            pass


def fazer_backup(motivo=""):
    with BACKUP_LOCK:
        sufixo = f"_{motivo}" if motivo else ""
        nome = f"db_{datetime.now():%Y-%m-%d_%H-%M-%S}{sufixo}.sqlite3"
        destino = os.path.join(pasta_backup(), nome)
        try:
            ok = copiar_banco(caminho_banco(), destino)
            if ok != "ok":
                os.remove(destino)
                raise RuntimeError(f"verificação do backup falhou: {ok}")
        except Exception as e:  # noqa: BLE001
            ULTIMO_BACKUP.update(erro=str(e), quando=agora_local())
            print(f"[{time.strftime('%H:%M:%S')}] ERRO no backup: {e}")
            raise
        ULTIMO_BACKUP.update(arquivo=nome, quando=agora_local(), erro=None)
        print(f"[{time.strftime('%H:%M:%S')}] Backup criado: {destino}")
        limpar_backups_antigos()
        return info_backup(destino)


def restaurar_backup(nome):
    # 1) carrega o backup na memória e confere se é um banco válido do sistema
    memoria = sqlite3.connect(":memory:")
    src = abrir_somente_leitura(caminho_backup(nome))
    try:
        src.backup(memoria)
        if memoria.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup corrompido, restauração cancelada.")
    except sqlite3.DatabaseError:
        raise ValueError("Este arquivo não é um banco de dados válido. Restauração cancelada.")
    finally:
        src.close()
    tabelas = {r[0] for r in memoria.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"pesagem_cliente", "pesagem_pesagem"} <= tabelas:
        raise ValueError("Este arquivo não é um backup válido do sistema de pesagem.")
    # 2) guarda o estado atual (dá para desfazer) e 3) restaura a partir da memória
    seguranca = fazer_backup("antes_restaurar")
    with BACKUP_LOCK:
        try:
            ok = copiar_banco(memoria, caminho_banco())
        finally:
            memoria.close()
    preparar_banco()
    return {"ok": ok == "ok", "restaurado": nome, "backup_de_seguranca": seguranca["nome"]}


def resumo_backup():
    lista = listar_backups()
    ultimo = lista[0] if lista else None
    horas = None
    if ultimo:
        horas = (datetime.now() - datetime.fromisoformat(ultimo["quando"])).total_seconds() / 3600
    return {"ativo": CONFIG["backup"]["ativo"], "ultimo": ultimo, "horas_desde_ultimo": horas,
            "erro": ULTIMO_BACKUP["erro"], "quantidade": len(lista), "pasta": pasta_backup()}


def agendador_backup():
    """Confere a cada minuto; faz backup quando passou o intervalo desde o último."""
    time.sleep(5)
    while True:
        try:
            cfg = CONFIG["backup"]
            if cfg.get("ativo"):
                r = resumo_backup()
                intervalo = float(cfg.get("intervalo_horas") or 6)
                if r["horas_desde_ultimo"] is None or r["horas_desde_ultimo"] >= intervalo:
                    fazer_backup()
        except Exception:  # noqa: BLE001
            pass  # erro já registrado em ULTIMO_BACKUP; tenta de novo no próximo ciclo
        time.sleep(60)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Empresas (cadastro próprio do sistema novo)
# --------------------------------------------------------------------------
CAMPOS_EMPRESA = ["nome", "documento", "telefone", "email", "contato", "endereco", "observacao", "plano_id", "ativa"]


def listar_empresas_cad(q=""):
    with conectar() as con:
        empresas = [dict(r) for r in con.execute("SELECT * FROM nova_empresa ORDER BY nome")]
        clientes = todos_clientes(con)
        planos = {p["id"]: p for p in listar_planos(con)}
        tickets = dict(con.execute(
            "SELECT empresa_id, COUNT(*) FROM nova_ticket WHERE empresa_id IS NOT NULL GROUP BY empresa_id").fetchall())
    por_empresa = {}
    for c in clientes:
        if c["empresa_id"]:
            por_empresa.setdefault(c["empresa_id"], []).append(
                {"id": c["id"], "nome": c["nome"], "motorista": c["motorista"], "placa": c["placa"], "pagador": c["pagador"]})
    for e in empresas:
        e["motoristas"] = por_empresa.get(e["id"], [])
        e["plano"] = planos.get(e["plano_id"])
        e["tickets"] = tickets.get(e["id"], 0)
    if q:
        alvo = normalizar(q)
        empresas = [e for e in empresas if alvo in normalizar(e["nome"]) or alvo in normalizar(e["documento"])
                    or any(alvo in normalizar(m["nome"]) or alvo in normalizar(m["placa"]) for m in e["motoristas"])]
    return empresas


def salvar_empresa(dados, eid=None):
    valores = {c: dados[c] for c in CAMPOS_EMPRESA if c in dados}
    if "nome" in valores:
        valores["nome"] = limpar_nome(valores["nome"])
        if not valores["nome"]:
            raise ValueError("Informe o nome da empresa.")
    elif not eid:
        raise ValueError("Informe o nome da empresa.")
    if "plano_id" in valores:
        valores["plano_id"] = int(num(valores["plano_id"])) if str(valores["plano_id"] or "").strip() else None
    if "ativa" in valores:
        valores["ativa"] = 1 if valores["ativa"] else 0
    for c in ("documento", "telefone", "email", "contato", "endereco", "observacao"):
        if c in valores:
            valores[c] = str(valores[c] or "").strip()
    valores["atualizado_em"] = agora_local()
    with conectar() as con:
        if valores.get("nome"):
            alvo = normalizar(valores["nome"])
            for r in con.execute("SELECT id, nome FROM nova_empresa"):
                if normalizar(r["nome"]) == alvo and r["id"] != eid:
                    raise ValueError(f"Já existe a empresa {r['nome']} (nº {r['id']}).")
        if eid:
            antigo = con.execute("SELECT nome FROM nova_empresa WHERE id = ?", (eid,)).fetchone()
            if not antigo:
                raise ValueError("Empresa não encontrada.")
            sets = ", ".join(f"{c} = ?" for c in valores)
            con.execute(f"UPDATE nova_empresa SET {sets} WHERE id = ?", (*valores.values(), eid))
        else:
            valores["criado_em"] = valores["atualizado_em"]
            valores.setdefault("ativa", 1)
            cols = ", ".join(valores)
            eid = con.execute(f"INSERT INTO nova_empresa ({cols}) VALUES ({', '.join('?' for _ in valores)})",
                              tuple(valores.values())).lastrowid
    return next(e for e in listar_empresas_cad() if e["id"] == eid)


def excluir_empresa(eid):
    with conectar() as con:
        usados = con.execute("SELECT COUNT(*) FROM nova_ticket WHERE empresa_id = ?", (eid,)).fetchone()[0]
        if usados:
            raise ValueError(f"A empresa tem {usados} ticket(s). Desmarque \"Ativa\" para desativar em vez de excluir.")
        n = con.execute("SELECT COUNT(*) FROM nova_motorista WHERE empresa_id = ?", (eid,)).fetchone()[0]
        con.execute("UPDATE nova_motorista SET empresa_id = NULL, pagador = 'MOTORISTA' WHERE empresa_id = ?", (eid,))
        con.execute("DELETE FROM nova_empresa WHERE id = ?", (eid,))
    return {"ok": True, "motoristas_desvinculados": n}


# --------------------------------------------------------------------------
# Tabela de valores (planos) e faturamento
# --------------------------------------------------------------------------
TIPOS_PLANO = {"PESAGEM": "Por pesagem", "TONELADA": "Por tonelada", "MENSAL": "Pacote mensal"}


def listar_planos(con=None):
    if con is None:
        with conectar() as c2:
            return listar_planos(c2)
    planos = [dict(r) for r in con.execute("SELECT * FROM nova_plano ORDER BY ativo DESC, nome")]
    uso_e = dict(con.execute("SELECT plano_id, COUNT(*) FROM nova_empresa WHERE plano_id IS NOT NULL GROUP BY plano_id").fetchall())
    uso_m = dict(con.execute("SELECT plano_id, COUNT(*) FROM nova_motorista WHERE plano_id IS NOT NULL GROUP BY plano_id").fetchall())
    for p in planos:
        p["tipo_nome"] = TIPOS_PLANO.get(p["tipo"], p["tipo"])
        p["empresas"], p["motoristas"] = uso_e.get(p["id"], 0), uso_m.get(p["id"], 0)
    return planos


def salvar_plano(dados, pid=None):
    nome = limpar_nome(dados.get("nome"))
    tipo = dados.get("tipo")
    if not nome:
        raise ValueError("Informe o nome da tabela de valor.")
    if tipo not in TIPOS_PLANO:
        raise ValueError("Tipo de cobrança inválido.")
    valor = num(dados.get("valor"))
    if valor is None or valor < 0:
        raise ValueError("Informe o valor.")
    v = {"nome": nome, "tipo": tipo, "valor": valor,
         "franquia": int(num(dados.get("franquia")) or 0) if tipo == "MENSAL" else 0,
         "valor_excedente": (num(dados.get("valor_excedente")) or 0) if tipo == "MENSAL" else 0,
         "padrao": 1 if dados.get("padrao") else 0, "ativo": 0 if dados.get("ativo") is False else 1,
         "observacao": str(dados.get("observacao") or "").strip(), "atualizado_em": agora_local()}
    with conectar() as con:
        if v["padrao"]:
            con.execute("UPDATE nova_plano SET padrao = 0")
        if pid:
            if not con.execute("SELECT 1 FROM nova_plano WHERE id = ?", (pid,)).fetchone():
                raise ValueError("Tabela de valor não encontrada.")
            con.execute(f"UPDATE nova_plano SET {', '.join(f'{k} = ?' for k in v)} WHERE id = ?", (*v.values(), pid))
        else:
            v["criado_em"] = v["atualizado_em"]
            pid = con.execute(f"INSERT INTO nova_plano ({', '.join(v)}) VALUES ({', '.join('?' for _ in v)})",
                              tuple(v.values())).lastrowid
        return next(p for p in listar_planos(con) if p["id"] == pid)


def excluir_plano(pid):
    with conectar() as con:
        usado = con.execute("SELECT (SELECT COUNT(*) FROM nova_empresa WHERE plano_id = ?) + "
                            "(SELECT COUNT(*) FROM nova_motorista WHERE plano_id = ?)", (pid, pid)).fetchone()[0]
        if usado:
            con.execute("UPDATE nova_plano SET ativo = 0, padrao = 0 WHERE id = ?", (pid,))
            return {"ok": True, "desativado": True, "em_uso": usado}
        con.execute("DELETE FROM nova_plano WHERE id = ?", (pid,))
    return {"ok": True, "desativado": False}


def meses_do_periodo(inicio, fim):
    a = datetime.fromisoformat(inicio).date().replace(day=1)
    b = datetime.fromisoformat(fim).date()
    meses = []
    while a <= b and len(meses) < 60:
        meses.append(f"{a.year}-{a.month:02d}")
        a = (a.replace(day=28) + timedelta(days=4)).replace(day=1)
    return meses


def calcular_faturamento(inicio, fim, q="", chave=None):
    """
    Fechamento por PAGADOR (quem recebe a cobrança): a empresa, quando o motorista
    presta serviço para ela, ou o próprio motorista/dono do caminhão.
      - Valor manual digitado na pesagem sempre vale (e não conta na franquia do pacote).
      - Por pesagem: valor fixo por pesagem. Por tonelada: líquido/1000 x valor.
      - Pacote mensal: mensalidade por mês do período; passando da franquia,
        cada pesagem a mais custa o valor excedente.
    Pesagens e mensalidades que já estão em uma fatura aparecem marcadas e não
    entram no "a faturar".
    """
    rel = relatorio_pesagens(inicio, fim)
    with conectar() as con:
        planos = {p["id"]: p for p in listar_planos(con)}
        empresas = {normalizar(r["nome"]): dict(r) for r in con.execute("SELECT * FROM nova_empresa")}
        clientes = todos_clientes(con)
        faturados = dict(con.execute(
            """SELECT i.ref, i.fatura_id FROM nova_fatura_item i JOIN nova_fatura f ON f.id = i.fatura_id
               WHERE f.status != 'CANCELADA'""").fetchall())
    padrao = next((p for p in planos.values() if p["padrao"] and p["ativo"]), None)
    meses = meses_do_periodo(inicio, fim)
    grupos = {}

    def grupo(nome, tipo):
        k = normalizar(nome) or "SEMPAGADOR"
        g = grupos.setdefault(k, {"chave": k, "pagador": nome or "—", "tipo": tipo, "linhas": [], "plano_motorista": None})
        if tipo == "EMPRESA":
            g["tipo"] = "EMPRESA"
        return g

    for x in rel["linhas"]:
        g = grupo(x["pagador"], x["pagador_tipo"])
        g["linhas"].append(dict(x))
        if x.get("plano_id") and not g["plano_motorista"]:
            g["plano_motorista"] = x["plano_id"]
    # quem tem pacote mensal paga a mensalidade mesmo sem pesagem no período
    for e in empresas.values():
        p = planos.get(e["plano_id"])
        if e["ativa"] and p and p["tipo"] == "MENSAL":
            grupo(e["nome"], "EMPRESA")
    for c in clientes:
        p = planos.get(c["plano_id"])
        if c["pagador"] == "MOTORISTA" and p and p["tipo"] == "MENSAL":
            grupo(c["titular"], "MOTORISTA")["plano_motorista"] = c["plano_id"]

    resultado = []
    for k, g in grupos.items():
        if chave and k != chave:
            continue
        e = empresas.get(k)
        p = (planos.get(e["plano_id"]) if e else None) or planos.get(g["plano_motorista"]) or padrao
        if p and not p["ativo"]:
            p = padrao
        if e:
            g["tipo"], g["pagador"], g["empresa_id"] = "EMPRESA", e["nome"], e["id"]
        mensalidades = []
        for x in sorted(g["linhas"], key=lambda x: x["data"] or ""):
            x["fatura"] = faturados.get(x["ref"])
            if x["valor_manual"] is not None:
                x["valor"], x["regra"] = x["valor_manual"], "manual"
            elif not p:
                x["valor"], x["regra"] = 0, "sem_tabela"
            elif p["tipo"] == "PESAGEM":
                x["valor"], x["regra"] = p["valor"], "pesagem"
            elif p["tipo"] == "TONELADA":
                x["valor"], x["regra"] = round((x["liquido"] or 0) / 1000 * p["valor"], 2), "tonelada"
            else:
                x["valor"], x["regra"] = 0, "pacote"
        if p and p["tipo"] == "MENSAL":
            for mes in meses:
                do_mes = [x for x in g["linhas"] if (x["data"] or "")[:7] == mes and x["regra"] == "pacote"]
                for i, x in enumerate(sorted(do_mes, key=lambda x: x["data"] or "")):
                    if p["franquia"] and i >= p["franquia"]:
                        x["valor"], x["regra"] = p["valor_excedente"], "excedente"
                ref = f"mensal:{mes}:{k}"
                mensalidades.append({"mes": mes, "ref": ref, "valor": p["valor"], "usadas": len(do_mes),
                                     "franquia": p["franquia"], "fatura": faturados.get(ref),
                                     "excedentes": max(0, len(do_mes) - p["franquia"]) if p["franquia"] else 0})
        g["linhas"].sort(key=lambda x: x["data"] or "", reverse=True)
        motoristas = {}
        for x in g["linhas"]:
            m = motoristas.setdefault(normalizar(x["motorista"]) or "-", {"nome": x["motorista"] or "—", "placas": set(),
                                                                           "pesagens": 0, "liquido": 0.0, "valor": 0.0})
            m["placas"].add(x["placa"])
            m["pesagens"] += 1
            m["liquido"] += x["liquido"] or 0
            m["valor"] += x["valor"]
        for m in motoristas.values():
            m["placas"] = sorted(m["placas"])
        total = sum(x["valor"] for x in g["linhas"]) + sum(m["valor"] for m in mensalidades)
        a_faturar = (sum(x["valor"] for x in g["linhas"] if not x["fatura"])
                     + sum(m["valor"] for m in mensalidades if not m["fatura"]))
        pendentes = sum(1 for x in g["linhas"] if not x["fatura"]) + sum(1 for m in mensalidades if not m["fatura"])
        resultado.append({
            "chave": k, "pagador": g["pagador"], "tipo": g["tipo"], "empresa_id": g.get("empresa_id"),
            "plano": p, "plano_padrao": bool(p and padrao and p["id"] == padrao["id"] and not (e and e["plano_id"])
                                              and not g["plano_motorista"]),
            "pesagens": len(g["linhas"]), "liquido": sum(x["liquido"] or 0 for x in g["linhas"]),
            "valor": round(total, 2), "a_faturar": round(a_faturar, 2), "pendentes": pendentes,
            "sem_valor": sum(1 for x in g["linhas"] if x["regra"] == "sem_tabela"),
            "motoristas": sorted(motoristas.values(), key=lambda m: -m["liquido"]),
            "mensalidades": mensalidades, "linhas": g["linhas"],
        })
    if q:
        alvo = normalizar(q)
        resultado = [g for g in resultado if alvo in normalizar(g["pagador"])
                     or any(alvo in normalizar(m["nome"]) or any(alvo in normalizar(p) for p in m["placas"])
                            for m in g["motoristas"])]
    resultado.sort(key=lambda g: (-g["valor"], -g["liquido"], g["pagador"]))
    return {
        "inicio": inicio, "fim": fim, "q": q, "meses": meses, "plano_padrao": padrao,
        "totais": {"pagadores": len(resultado), "pesagens": sum(g["pesagens"] for g in resultado),
                   "liquido": sum(g["liquido"] for g in resultado), "valor": round(sum(g["valor"] for g in resultado), 2),
                   "a_faturar": round(sum(g["a_faturar"] for g in resultado), 2),
                   "sem_valor": sum(g["sem_valor"] for g in resultado)},
        "pagadores": resultado,
    }


def faturamento_csv(fat):
    def br(v, casas=0):
        return "" if v is None else f"{v:.{casas}f}".replace(".", ",")
    regras = {"manual": "valor manual", "pesagem": "por pesagem", "tonelada": "por tonelada", "pacote": "no pacote",
              "excedente": "excedente do pacote", "sem_tabela": "sem tabela de valor"}
    out = ["Pagador;Tipo;Nº;Data;Placa;Motorista;Empresa;Item;Líquido (kg);Valor (R$);Regra;Fatura"]
    for g in fat["pagadores"]:
        tipo = "Empresa" if g["tipo"] == "EMPRESA" else "Motorista"
        for m in g["mensalidades"]:
            out.append(";".join([g["pagador"], tipo, "", m["mes"], "", "", "", "Mensalidade do pacote", "",
                                 br(m["valor"], 2), "mensalidade", str(m["fatura"] or "")]))
        for x in g["linhas"]:
            campos = [g["pagador"], tipo, x["numero"], x["data"] or "", x["placa"] or "", x["motorista"] or "",
                      x["empresa"] or "", x["item"] or "", br(x["liquido"]), br(x["valor"], 2),
                      regras.get(x["regra"], x["regra"]), str(x["fatura"] or "")]
            out.append(";".join(str(c).replace(";", ",").replace("\n", " ") for c in campos))
        out.append(f"{g['pagador']};SUBTOTAL;;;;;;;{br(g['liquido'])};{br(g['valor'], 2)};;")
    t = fat["totais"]
    out.append(f"TOTAL GERAL;;;;;;;;{br(t['liquido'])};{br(t['valor'], 2)};;")
    return ("﻿" + "\r\n".join(out)).encode("utf-8")


def gerar_fatura(inicio, fim, chave, observacao=""):
    if not (inicio and fim and chave):
        raise ValueError("Informe o período e o pagador.")
    fat = calcular_faturamento(inicio, fim, chave=chave)
    if not fat["pagadores"]:
        raise ValueError("Pagador não encontrado no período.")
    g = fat["pagadores"][0]
    linhas = [x for x in g["linhas"] if not x["fatura"]]
    mensal = [m for m in g["mensalidades"] if not m["fatura"]]
    if not linhas and not mensal:
        raise ValueError("Nada a faturar: tudo deste período já está em outra fatura.")
    valor = round(sum(x["valor"] for x in linhas) + sum(m["valor"] for m in mensal), 2)
    detalhes = {"plano": g["plano"], "linhas": linhas, "mensalidades": mensal,
                "motoristas": [m for m in g["motoristas"]]}
    with conectar() as con:
        fid = con.execute(
            """INSERT INTO nova_fatura (pagador, pagador_chave, pagador_tipo, empresa_id, inicio, fim, pesagens,
                                        liquido, valor, status, detalhes, observacao, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', ?, ?, ?)""",
            (g["pagador"], chave, g["tipo"], g["empresa_id"], inicio, fim, len(linhas),
             sum(x["liquido"] or 0 for x in linhas), valor, json.dumps(detalhes, ensure_ascii=False, default=str),
             str(observacao or "").strip(), agora_local())).lastrowid
        con.executemany("INSERT INTO nova_fatura_item (fatura_id, ref, descricao, valor) VALUES (?, ?, ?, ?)",
                        [(fid, x["ref"], f"Pesagem {x['numero']} {x['placa']}", x["valor"]) for x in linhas]
                        + [(fid, m["ref"], f"Mensalidade {m['mes']}", m["valor"]) for m in mensal])
    return obter_fatura(fid)


def obter_fatura(fid):
    with conectar() as con:
        r = con.execute("SELECT * FROM nova_fatura WHERE id = ?", (fid,)).fetchone()
    if not r:
        return None
    f = dict(r)
    f["detalhes"] = json.loads(f["detalhes"] or "{}")
    return f


def listar_faturas(status="", q=""):
    sql, args = "SELECT id, pagador, pagador_tipo, inicio, fim, pesagens, liquido, valor, status, observacao, criado_em, pago_em FROM nova_fatura WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if q:
        sql += " AND (pagador LIKE ? OR CAST(id AS TEXT) = ?)"
        args += [f"%{q}%", q]
    with conectar() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY id DESC LIMIT 300", args)]


def atualizar_fatura(fid, dados):
    with conectar() as con:
        if not con.execute("SELECT 1 FROM nova_fatura WHERE id = ?", (fid,)).fetchone():
            raise ValueError("Fatura não encontrada.")
        if "status" in dados:
            if dados["status"] not in ("ABERTA", "PAGA"):
                raise ValueError("Situação inválida.")
            con.execute("UPDATE nova_fatura SET status = ?, pago_em = ? WHERE id = ?",
                        (dados["status"], agora_local() if dados["status"] == "PAGA" else None, fid))
        if "observacao" in dados:
            con.execute("UPDATE nova_fatura SET observacao = ? WHERE id = ?", (str(dados["observacao"] or "").strip(), fid))
        if "itens" in dados:
            editar_itens_fatura(con, fid, dados["itens"])
    return obter_fatura(fid)


def editar_itens_fatura(con, fid, itens):
    """
    Edição da fatura: `itens` = [{ref, valor}] com o que FICA na fatura e o valor de cada um.
    O que sair volta para o "a faturar". Totais e resumo por motorista são recalculados.
    """
    novos = {str(i["ref"]): num(i.get("valor")) or 0.0 for i in itens or []}
    if not novos:
        raise ValueError("A fatura precisa ter pelo menos um item. Para tirar tudo, exclua a fatura.")
    d = json.loads(con.execute("SELECT detalhes FROM nova_fatura WHERE id = ?", (fid,)).fetchone()[0] or "{}")
    linhas = [dict(x, valor=round(novos[x["ref"]], 2)) for x in d.get("linhas", []) if x["ref"] in novos]
    mensal = [dict(m, valor=round(novos[m["ref"]], 2)) for m in d.get("mensalidades", []) if m["ref"] in novos]
    antes = {x["ref"]: x["valor"] for x in d.get("linhas", [])}
    for x in linhas:
        if abs(x["valor"] - (antes.get(x["ref"]) or 0)) > 0.004:
            x["regra"] = "manual"  # valor mudado na edição da fatura
    motoristas = {}
    for x in linhas:
        m = motoristas.setdefault(normalizar(x.get("motorista")) or "-", {"nome": x.get("motorista") or "—", "placas": [],
                                                                       "pesagens": 0, "liquido": 0.0, "valor": 0.0})
        if x.get("placa") and x["placa"] not in m["placas"]:
            m["placas"].append(x["placa"])
        m["pesagens"] += 1
        m["liquido"] += x.get("liquido") or 0
        m["valor"] += x["valor"]
    d.update(linhas=linhas, mensalidades=mensal, motoristas=sorted(motoristas.values(), key=lambda m: -m["liquido"]))
    valor = round(sum(x["valor"] for x in linhas) + sum(m["valor"] for m in mensal), 2)
    con.execute("UPDATE nova_fatura SET detalhes = ?, valor = ?, pesagens = ?, liquido = ? WHERE id = ?",
                (json.dumps(d, ensure_ascii=False, default=str), valor, len(linhas),
                 sum(x.get("liquido") or 0 for x in linhas), fid))
    con.execute("DELETE FROM nova_fatura_item WHERE fatura_id = ?", (fid,))
    con.executemany("INSERT INTO nova_fatura_item (fatura_id, ref, descricao, valor) VALUES (?, ?, ?, ?)",
                    [(fid, x["ref"], f"Pesagem {x.get('numero')} {x.get('placa')}", x["valor"]) for x in linhas]
                    + [(fid, m["ref"], f"Mensalidade {m.get('mes')}", m["valor"]) for m in mensal])


def excluir_fatura(fid):
    """Exclui a fatura; as pesagens dela voltam para o "a faturar"."""
    with conectar() as con:
        con.execute("DELETE FROM nova_fatura_item WHERE fatura_id = ?", (fid,))
        con.execute("DELETE FROM nova_fatura WHERE id = ?", (fid,))
    return {"ok": True, "id": fid}


# --------------------------------------------------------------------------
# Organizar cadastros antigos (separar motorista/empresa, unificar duplicados)
# Nada é apagado: o nome original fica guardado e cadastros duplicados só ficam ocultos.
# --------------------------------------------------------------------------
ANOTACOES = re.compile(r"\b(BLOQ\w*|FALTA DE PAGAMENTO|VERIFICAR CADASTRO|VERIFICAR)\b.*$")


def sugerir_separacao(c):
    nome = limpar_nome(c["nome"])
    cartao = limpar_nome(c.get("card_name"))
    primeiro = normalizar(cartao.split()[0]) if cartao else ""
    m = re.match(r"^(.*?)\(\s*(.*?)\s*\)(.*)$", nome)
    if m:
        dentro = m.group(2).strip()
        if ANOTACOES.search(dentro):
            return None  # é anotação ("bloqueado por falta de pagamento"), não empresa
        fora = ANOTACOES.sub("", f"{m.group(1)} {m.group(3)}").strip()
        fora = empresa_automatica(fora)
        if not fora or not dentro:
            return None
        palavras_fora = {normalizar(p) for p in fora.split()}
        palavras_dentro = {normalizar(p) for p in dentro.split()}
        if primeiro and primeiro in palavras_fora and primeiro not in palavras_dentro:
            motorista, empresa = fora, dentro
        else:
            motorista, empresa = dentro, fora
        return {"motorista_nome": motorista, "empresa_nome": empresa,
                "motivo": "nome com outra pessoa entre parênteses"}
    if primeiro and not re.search(r"\d", cartao) and primeiro not in normalizar(nome):
        return {"motorista_nome": cartao, "empresa_nome": empresa_automatica(nome),
                "motivo": "nome no cartão (tag) é de outra pessoa"}
    return None


def sugestoes_migracao():
    with conectar() as con:
        todos = todos_clientes(con, True)
        ignorar = {(r[0], r[1]) for r in con.execute("SELECT tipo, chave FROM nova_migracao_ignorar")}
        tickets = dict(con.execute("SELECT cliente_id, COUNT(*) FROM nova_ticket GROUP BY cliente_id").fetchall())
    ativos = [c for c in todos if not c["inativo"]]
    resumo = lambda c: {k: c.get(k) for k in ("id", "nome", "placa", "user_id", "card_no", "card_name", "tara", "modelo",
                                             "empresa", "empresa_vinculada", "motorista_nome", "nome_original")}

    separar = []
    for c in ativos:
        if c["empresa_id"] or c["motorista_nome"] or ("separar", str(c["id"])) in ignorar:
            continue
        s = sugerir_separacao(c)
        if s:
            separar.append({**resumo(c), **s})

    grupos = {}
    for c in ativos:
        if normalizar(c["placa"]):
            grupos.setdefault(normalizar(c["placa"]), []).append(c)
    duplicados = []
    for placa, membros in grupos.items():
        if len(membros) < 2 or ("unificar", placa) in ignorar:
            continue
        # fica o cadastro com tag de verdade ("NOME - 41") e mais tickets
        def nota(c):
            tag = bool(re.search(r"-\s*\d+\s*$", c.get("user_id") or "")) and str(c.get("card_no") or "0").strip() not in ("", "0")
            return (tag, bool(c["empresa_id"]), tickets.get(c["id"], 0), -c["id"])
        manter = max(membros, key=nota)
        empresa = next((c["empresa_vinculada"] for c in membros if c["empresa_vinculada"]), "")
        if not empresa:
            for c in membros:
                s = sugerir_separacao(c)
                if c is not manter and s and normalizar(s["motorista_nome"]) and \
                        normalizar(s["motorista_nome"]).startswith(normalizar((manter.get("card_name") or "x").split()[0])):
                    empresa = s["empresa_nome"]
        duplicados.append({"placa": membros[0]["placa"], "chave": placa, "manter": manter["id"], "empresa_nome": empresa,
                           "membros": [{**resumo(c), "tickets": tickets.get(c["id"], 0)} for c in membros]})

    por_grupo = {}
    for c in ativos:
        if not c["empresa_id"]:
            por_grupo.setdefault(c["empresa"], []).append(c)
    with conectar() as con:
        cadastradas = {normalizar(r[0]) for r in con.execute("SELECT nome FROM nova_empresa")}
    # frotas ainda sem empresa cadastrada, e caminhões cujo nome já é de uma empresa cadastrada
    frotas = [{"nome": nome, "caminhoes": len(cs), "placas": [c["placa"] for c in cs],
               "existe": normalizar(nome) in cadastradas}
              for nome, cs in sorted(por_grupo.items())
              if (len({normalizar(c["placa"]) for c in cs}) > 1 or normalizar(nome) in cadastradas)
              and ("frota", normalizar(nome)) not in ignorar]

    feitos = [{**resumo(c), "inativo": c["inativo"], "unificado_em": c["unificado_em"]}
              for c in todos if c["nome_original"] or c["inativo"]]
    return {"separar": separar, "duplicados": duplicados, "frotas": frotas, "feitos": feitos,
            "ignorados": len(ignorar)}


def aplicar_migracao(acao, dados):
    if acao not in ("separar", "desfazer", "unificar", "frotas", "ignorar", "restaurar_ignorados"):
        raise ValueError("Ação inválida.")
    if acao in ("separar", "unificar", "frotas"):
        fazer_backup("antes_migracao")
    feitos = 0
    with conectar() as con:
        if acao == "separar":
            for it in dados.get("itens", []):
                c = obter_cliente(con, int(it["cliente_id"]))
                motorista = limpar_nome(it.get("motorista_nome"))
                if not c or not motorista:
                    continue
                eid = obter_ou_criar_empresa(con, it.get("empresa_nome"))
                campos = {"motorista_nome": motorista, "empresa_id": eid,
                          "pagador": it.get("pagador") if eid and it.get("pagador") in ("EMPRESA", "MOTORISTA")
                          else ("EMPRESA" if eid else "MOTORISTA")}
                if it.get("renomear", True) and normalizar(motorista) != normalizar(c["nome"]):
                    if not c["nome_original"]:
                        campos["nome_original"] = c["nome"]
                    con.execute("UPDATE pesagem_cliente SET nome = ? WHERE id = ?", (motorista[:255], c["id"]))
                gravar_vinculo(con, c["id"], **campos)
                feitos += 1
        elif acao == "desfazer":
            cid = int(dados["cliente_id"])
            c = obter_cliente(con, cid)
            if not c:
                raise ValueError("Cadastro não encontrado.")
            if c["nome_original"]:
                con.execute("UPDATE pesagem_cliente SET nome = ? WHERE id = ?", (c["nome_original"], cid))
            gravar_vinculo(con, cid, motorista_nome=None, empresa_id=None, pagador=None, nome_original=None,
                           inativo=0, unificado_em=None)
            feitos = 1
        elif acao == "unificar":
            copiar = ("user_id", "card_no", "card_name", "modelo", "peso_maximo", "ano_fabricacao",
                      "descricao_carga", "tipo_carga")
            vazio = lambda v: v is None or str(v).strip() in ("", "0", "0.0")
            for g in dados.get("grupos", []):
                manter = int(g["manter"])
                fica = obter_cliente(con, manter)
                if not fica:
                    continue
                for oid in g.get("ocultar", []):
                    oid = int(oid)
                    if oid == manter:
                        continue
                    o = obter_cliente(con, oid)
                    if not o:
                        continue
                    for campo in copiar:  # completa o que estiver em branco no cadastro que fica
                        if vazio(fica.get(campo)) and not vazio(o.get(campo)):
                            con.execute(f"UPDATE pesagem_cliente SET {campo} = ? WHERE id = ?", (o[campo], manter))
                            fica[campo] = o[campo]
                    gravar_vinculo(con, oid, inativo=1, unificado_em=manter)
                    con.execute("UPDATE nova_ticket SET cliente_id = ? WHERE cliente_id = ? AND status = 'ABERTO'", (manter, oid))
                if g.get("empresa_nome"):
                    gravar_vinculo(con, manter, empresa_id=obter_ou_criar_empresa(con, g["empresa_nome"]), pagador="EMPRESA")
                feitos += 1
        elif acao == "frotas":
            todos = todos_clientes(con)
            for nome in dados.get("nomes", []):
                eid = obter_ou_criar_empresa(con, nome)
                for c in todos:
                    if c["empresa"] == nome and not c["empresa_id"]:
                        gravar_vinculo(con, c["id"], empresa_id=eid, pagador="EMPRESA")
                feitos += 1
        elif acao == "ignorar":
            chave = normalizar(dados["chave"]) if dados["tipo"] == "frota" else str(dados["chave"])
            con.execute("INSERT OR IGNORE INTO nova_migracao_ignorar (tipo, chave) VALUES (?, ?)", (dados["tipo"], chave))
            feitos = 1
        elif acao == "restaurar_ignorados":
            feitos = con.execute("DELETE FROM nova_migracao_ignorar").rowcount
    return {**sugestoes_migracao(), "ok": True, "aplicados": feitos}


TIPOS = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon",
         ".svg": "image/svg+xml"}


def config_publica():
    c = json.loads(json.dumps(CONFIG))
    c["incontrol"]["senha"] = "********" if c["incontrol"].get("senha") else ""
    c["camera"]["senha"] = "********" if c["camera"].get("senha") else ""
    c["espelho"]["token"] = "********" if c["espelho"].get("token") else ""
    c["camera"]["instalado"] = os.path.isfile(CAMERA_PY)
    c["banco_absoluto"] = caminho_banco()
    return c


class Handler(BaseHTTPRequestHandler):
    server_version = "PesagemTranstino/1.0"

    def log_message(self, fmt, *args):
        if any(x in str(args[0] if args else "") for x in ("/api/peso", "/api/tag/ultima", "/api/camera/")):
            return
        sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _rota(self):
        u = urllib.parse.urlparse(self.path)
        partes = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        return partes, q

    def _arquivo(self, nome):
        caminho = os.path.normpath(os.path.join(STATIC_DIR, nome))
        if not caminho.startswith(STATIC_DIR) or not os.path.isfile(caminho):
            self.send_error(404)
            return
        with open(caminho, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(os.path.splitext(caminho)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _executar(self, metodo):
        partes, q = self._rota()
        try:
            if not partes or partes[0] != "api":
                return self._arquivo("/".join(partes) or "index.html")
            r = partes[1:]

            if r == ["status"]:
                return self._json({"config": config_publica(), "resumo": resumo_hoje(), "backup": resumo_backup(),
                                   "espelho": ESPELHO})

            if r[:1] == ["backups"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json({"resumo": resumo_backup(), "arquivos": listar_backups()})
                if len(r) == 1 and metodo == "POST":
                    return self._json(fazer_backup("manual"))
                nome = r[1]
                if len(r) == 3 and r[2] == "restaurar" and metodo == "POST":
                    return self._json(restaurar_backup(nome))
                if len(r) == 3 and r[2] == "baixar":
                    caminho = caminho_backup(nome)
                    with open(caminho, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="{nome}"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if metodo == "DELETE":
                    os.remove(caminho_backup(nome))
                    return self._json({"ok": True})
            if r == ["peso"]:
                return self._json(ler_balanca())

            if r == ["falhas"]:
                if metodo == "POST":
                    d = self._corpo()
                    registrar_falha(d.get("tipo"), d.get("mensagem"), d.get("placa"))
                    return self._json({"ok": True})
                return self._json(ler_falhas(int(q.get("limite", 300))))
            if r == ["impressoras"]:
                return self._json(listar_impressoras())

            if r[:1] == ["camera"]:
                if r[1:] == ["status"]:
                    return self._json(camera_status())
                if r[1:] == ["placa"]:
                    try:
                        return self._json(ler_placa_camera())
                    except (urllib.error.URLError, OSError) as e:
                        return self._json({"placa": None, "erro": f"Câmera indisponível: {e}"})
                if r[1:] == ["buscar"]:
                    return self._json(buscar_por_placa(q.get("placa", "")))
                if r[1:] == ["foto.jpg"]:
                    try:
                        largura = int(q.get("w") or 1280)
                        body, tipo = camera_get(f"/foto.jpg?w={largura}", 4)
                    except (urllib.error.URLError, OSError):
                        self.send_error(503)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", tipo)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return

            if r[:1] == ["whatsapp"]:
                if r[1:] == ["status"]:
                    return self._json(status_whatsapp())
                if r[1:] in (["proximo"], ["resultado"]):
                    if self.headers.get("X-Espelho"):  # só a extensão deste computador
                        return self._json({"erro": "Só no computador da balança."}, 403)
                    if r[1:] == ["proximo"]:
                        return self._json(proximo_whatsapp(q.get("estado", ""), bool(q.get("so_estado"))))
                    if metodo == "POST":
                        resultado_whatsapp(self._corpo())
                        return self._json({"ok": True})
                if r[1:] == ["teste"] and metodo == "POST":
                    numeros = numeros_whatsapp()
                    if not numeros:
                        return self._json({"erro": "Informe pelo menos um número."}, 400)
                    texto = "✅ Teste do aviso da Balança Transtino\n\n" + texto_aviso(None, ler_balanca())
                    for n in numeros:
                        enfileirar_whatsapp(n, texto)
                    return self._json({"ok": True, "numeros": numeros})

            if r[:1] == ["config"]:
                if metodo == "POST":
                    novo = self._corpo()
                    for k, v in novo.items():
                        if k not in DEFAULT_CONFIG:
                            continue
                        if isinstance(DEFAULT_CONFIG[k], dict) and isinstance(v, dict):
                            for sk, sv in v.items():
                                if sk in ("senha", "token") and sv == "********":
                                    continue
                                if sk in DEFAULT_CONFIG[k]:
                                    CONFIG[k][sk] = sv
                        elif not isinstance(DEFAULT_CONFIG[k], dict):
                            CONFIG[k] = v
                    salvar_config(CONFIG)
                    INCONTROL.token = None
                    if "camera" in novo:
                        threading.Thread(target=iniciar_camera, daemon=True).start()
                return self._json(config_publica())

            if r[:1] == ["clientes"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json(buscar_clientes(q.get("q", ""), int(q.get("limite", 50)), bool(q.get("ocultos"))))
                if len(r) == 1 and metodo == "POST":
                    return self._json(salvar_cliente(self._corpo()))
                cid = int(r[1])
                if len(r) == 3 and r[2] == "reativar" and metodo == "POST":
                    with conectar() as con:
                        gravar_vinculo(con, cid, inativo=0, unificado_em=None)
                        return self._json(obter_cliente(con, cid))
                if metodo == "PUT":
                    return self._json(salvar_cliente(self._corpo(), cid))
                if metodo == "DELETE":
                    with conectar() as con:
                        con.execute("DELETE FROM pesagem_cliente WHERE id = ?", (cid,))
                        con.execute("DELETE FROM nova_cliente_empresa WHERE cliente_id = ?", (cid,))
                        con.execute("DELETE FROM nova_motorista WHERE cliente_id = ?", (cid,))
                    return self._json({"ok": True})
                with conectar() as con:
                    c = obter_cliente(con, cid)
                return self._json(c, 200 if c else 404)

            if r == ["empresas"]:
                return self._json(listar_empresas(q.get("q", "")))
            if r[:1] == ["empresas-cad"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json(listar_empresas_cad(q.get("q", "")))
                if len(r) == 1 and metodo == "POST":
                    return self._json(salvar_empresa(self._corpo()))
                eid = int(r[1])
                if metodo == "PUT":
                    return self._json(salvar_empresa(self._corpo(), eid))
                if metodo == "DELETE":
                    return self._json(excluir_empresa(eid))
                e = next((x for x in listar_empresas_cad() if x["id"] == eid), None)
                return self._json(e, 200 if e else 404)
            if r[:1] == ["planos"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json(listar_planos())
                if len(r) == 1 and metodo == "POST":
                    return self._json(salvar_plano(self._corpo()))
                pid = int(r[1])
                if metodo == "PUT":
                    return self._json(salvar_plano(self._corpo(), pid))
                if metodo == "DELETE":
                    return self._json(excluir_plano(pid))
            if r and r[0] in ("faturamento", "faturamento.csv"):
                hoje = datetime.now().strftime("%Y-%m-%d")
                fat = calcular_faturamento(q.get("inicio") or hoje[:8] + "01", q.get("fim") or hoje, q.get("q", ""))
                if r[0] == "faturamento":
                    return self._json(fat)
                body = faturamento_csv(fat)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="faturamento_{fat["inicio"]}_a_{fat["fim"]}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if r[:1] == ["faturas"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json(listar_faturas(q.get("status", ""), q.get("q", "")))
                if len(r) == 1 and metodo == "POST":
                    d = self._corpo()
                    return self._json(gerar_fatura(d.get("inicio"), d.get("fim"), d.get("chave"), d.get("observacao", "")))
                fid = int(r[1])
                if metodo == "PUT":
                    return self._json(atualizar_fatura(fid, self._corpo()))
                if metodo == "DELETE":
                    return self._json(excluir_fatura(fid))
                f = obter_fatura(fid)
                return self._json(f, 200 if f else 404)
            if r[:1] == ["migracao"]:
                if len(r) == 1:
                    return self._json(sugestoes_migracao())
                if metodo == "POST":
                    return self._json(aplicar_migracao(r[1], self._corpo()))
            if r == ["empresas", "caminhoes"]:
                return self._json(caminhoes_da_empresa(q.get("nome", "")))

            if r[:1] == ["tag"]:
                if r[1:] == ["buscar"]:
                    return self._json(identificar_por_tag(q.get("codigo", "")))
                if r[1:] == ["ultima"]:
                    if not CONFIG["incontrol"].get("ativo"):
                        return self._json({"ativo": False})
                    try:
                        ev, bruto = INCONTROL.ultimo_evento()
                    except Exception as e:  # noqa: BLE001
                        return self._json({"ativo": True, "erro": str(e)})
                    usuario = extrair_usuario(ev) if ev else None
                    res = {"ativo": True, "evento": ev, "usuario": usuario,
                           "chave": json.dumps(ev, sort_keys=True, default=str)[:300] if ev else None,
                           "clientes": identificar_por_tag(usuario) if usuario else []}
                    if q.get("debug"):
                        res["resposta_bruta"] = bruto
                    return self._json(res)

            if r[:1] == ["tickets"]:
                if len(r) == 1 and metodo == "GET":
                    return self._json(listar_tickets(q.get("status"), q.get("q", "")))
                if len(r) == 1 and metodo == "POST":
                    d = self._corpo()
                    t = salvar_ticket(d)
                    if d.get("encerrar") and guardar_foto_ticket(t["id"]):
                        t["foto"] = True
                    return self._json(t)
                tid = int(r[1])
                if len(r) == 3 and r[2] == "imprimir" and metodo == "POST":
                    d = self._corpo()
                    return self._json(imprimir_ticket_direto(tid, bool(d.get("foto")), d.get("placa", "")))
                if len(r) == 3 and r[2] == "foto.jpg":
                    if not os.path.isfile(caminho_foto(tid)):
                        self.send_error(404)
                        return
                    with open(caminho_foto(tid), "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if len(r) == 3 and r[2] == "cancelar":
                    with conectar() as con:
                        con.execute("UPDATE nova_ticket SET status='CANCELADO', atualizado_em=? WHERE id=? AND status='ABERTO'",
                                    (agora_local(), tid))
                        return self._json(obter_ticket(con, tid))
                if metodo == "PUT":
                    d = self._corpo()
                    t = salvar_ticket(d, tid)
                    if d.get("encerrar") and not t.get("foto") and guardar_foto_ticket(tid):
                        t["foto"] = True
                    return self._json(t)
                if metodo == "DELETE":
                    return self._json(excluir_ticket(tid))
                with conectar() as con:
                    t = obter_ticket(con, tid)
                return self._json(t, 200 if t else 404)

            if r == ["historico"]:
                return self._json(historico_antigo(q.get("q", "")))
            if r == ["historico", "cobranca"]:
                return self._json(historico_cobranca(q.get("q", ""), q.get("inicio", ""), q.get("fim", "")))
            if r == ["dashboard"]:
                return self._json(dashboard(q.get("dias", 30)))

            if r and r[0] in ("relatorio", "relatorio.csv"):
                hoje = datetime.now().strftime("%Y-%m-%d")
                rel = relatorio_pesagens(q.get("inicio") or hoje, q.get("fim") or hoje, q.get("empresa", ""),
                                         q.get("q", ""), q.get("motorista", ""), q.get("pagador", ""))
                if r[0] == "relatorio":
                    return self._json(rel)
                body = relatorio_csv(rel)
                nome = f"relatorio_pesagens_{rel['inicio']}_a_{rel['fim']}.csv"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{nome}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if r[:1] == ["historico"] and len(r) == 2:
                hid = int(r[1])
                if metodo == "PUT":
                    return self._json(editar_historico(hid, self._corpo()))
                if metodo == "DELETE":
                    return self._json(excluir_historico(hid))
                with conectar() as con:
                    h = obter_historico(con, hid)
                return self._json(h, 200 if h else 404)

            return self._json({"erro": "rota não encontrada"}, 404)
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"erro": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        self._executar("GET")

    def do_POST(self):
        self._executar("POST")

    def do_PUT(self):
        self._executar("PUT")

    def do_DELETE(self):
        self._executar("DELETE")


def abrir_navegador(url):
    if CONFIG.get("chrome_impressao_direta"):
        candidatos = [
            shutil.which("chrome"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((c for c in candidatos if c and os.path.isfile(c)), None)
        if chrome:
            perfil = os.path.join(BASE, "chrome_perfil")
            subprocess.Popen([chrome, f"--app={url}", "--kiosk-printing", f"--user-data-dir={perfil}"])
            return
    webbrowser.open(url)


def main():
    if not os.path.exists(caminho_banco()):
        print(f"ERRO: banco de dados não encontrado em {caminho_banco()}")
        print("Ajuste 'banco_dados' no arquivo config.json.")
        input("Enter para sair...")
        return
    preparar_banco()
    porta = int(CONFIG.get("porta", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", porta), Handler)
    url = f"http://127.0.0.1:{porta}/"
    print("=" * 60)
    print(f"  {CONFIG['empresa']} - Sistema de Pesagem")
    print(f"  Abra no navegador: {url}")
    print(f"  Banco de dados:    {caminho_banco()}")
    print(f"  Balança (API):     {CONFIG['balanca_url']}")
    print(f"  Backups em:        {pasta_backup()}")
    print("  Para encerrar, feche esta janela.")
    print("=" * 60)
    threading.Thread(target=agendador_backup, daemon=True).start()
    for _ in range(max(1, int((CONFIG.get("espelho") or {}).get("conexoes") or 6))):
        threading.Thread(target=trabalhador_espelho, daemon=True).start()
    iniciar_camera()
    threading.Thread(target=vigiar_balanca, daemon=True).start()
    if CONFIG.get("abrir_navegador", True):
        threading.Timer(1.0, abrir_navegador, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        parar_camera()


if __name__ == "__main__":
    main()
