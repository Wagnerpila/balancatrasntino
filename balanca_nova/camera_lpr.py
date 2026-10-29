# -*- coding: utf-8 -*-
"""
Programa auxiliar da câmera da balança (iniciado sozinho pelo servidor.py).

- Conecta no vídeo da câmera (RTSP) e guarda sempre a imagem mais recente.
- Leitura de placa com o fast-alpr (gratuito, roda neste computador, sem internet
  e sem limite de leituras): https://github.com/ankandrew/fast-alpr
- Responde só para este computador (127.0.0.1):
    /status    -> se o vídeo está chegando
    /foto.jpg  -> imagem atual
    /placa     -> placas lidas na imagem atual

Roda com o Python da pasta lpr_venv (instalado pelo INSTALAR_CAMERA.bat).
"""
import argparse
import base64
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
import cv2  # noqa: E402

ESTADO = {"frame": None, "quando": 0.0, "erro": "Conectando…", "lock": threading.Lock()}
ALPR = {"modelo": None, "lock": threading.Lock(), "erro": None}


def url_camera(cam):
    """Monta rtsp://usuario:senha@ip/... a partir do config.json."""
    url = (cam.get("url") or "").strip()
    u = urllib.parse.urlsplit(url)
    if cam.get("usuario") and "@" not in u.netloc:
        cred = urllib.parse.quote(cam["usuario"], safe="")
        if cam.get("senha"):
            cred += ":" + urllib.parse.quote(cam["senha"], safe="")
        url = urllib.parse.urlunsplit((u.scheme, f"{cred}@{u.netloc}", u.path, u.query, u.fragment))
    return url


def ler_video(url):
    while True:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            ESTADO["erro"] = "Não conectou no vídeo da câmera (confira endereço, usuário e senha)"
            time.sleep(5)
            continue
        falhas = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                falhas += 1
                if falhas > 50:
                    ESTADO["erro"] = "O vídeo da câmera parou — reconectando…"
                    break
                time.sleep(0.1)
                continue
            falhas = 0
            with ESTADO["lock"]:
                ESTADO["frame"], ESTADO["quando"], ESTADO["erro"] = frame, time.time(), None
        cap.release()
        time.sleep(2)


def frame_atual(idade=10):
    """Imagem mais recente e a hora em que chegou (identifica o quadro do vídeo)."""
    with ESTADO["lock"]:
        if ESTADO["frame"] is None or time.time() - ESTADO["quando"] > idade:
            return None, None
        return ESTADO["frame"].copy(), ESTADO["quando"]


def modelo_alpr():
    with ALPR["lock"]:
        if ALPR["modelo"] is None:
            from fast_alpr import ALPR as Leitor
            ALPR["modelo"] = Leitor(detector_model="yolo-v9-s-608-license-plate-end2end",
                                    ocr_model="cct-s-v2-global-model")
        return ALPR["modelo"]


def ler_placas(frame):
    resultados = []
    for r in modelo_alpr().predict(frame):
        if not r.ocr or not r.ocr.text:
            continue
        texto = r.ocr.text.strip()
        conf = r.ocr.confidence
        if isinstance(conf, (list, tuple)):  # um valor por caractere (o resto é preenchimento)
            conf = conf[:len(texto)] or conf
            conf = sum(conf) / len(conf) if conf else 0
        resultados.append({"texto": texto, "confianca": round(float(conf), 3),
                           "deteccao": round(float(r.detection.confidence), 3),
                           "pais": getattr(r.ocr, "region", None)})
    return resultados


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _enviar(self, corpo, tipo, status=200):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, obj, status=200):
        self._enviar(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self):
        caminho = urllib.parse.urlsplit(self.path).path
        if caminho == "/status":
            idade = time.time() - ESTADO["quando"] if ESTADO["quando"] else None
            ok = idade is not None and idade < 10
            return self._json({"ok": ok, "mensagem": "Vídeo OK" if ok else ESTADO["erro"],
                               "leitor_placa": ALPR["erro"] or ("pronto" if ALPR["modelo"] else "carrega na 1ª leitura")})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        frame, quando = frame_atual(min(float(q.get("idade", ["10"])[0]), 60))
        if frame is None:
            return self._json({"erro": ESTADO["erro"] or "Sem imagem"}, 503)
        if caminho == "/foto.jpg":
            h, w = frame.shape[:2]
            largura = min(int(q.get("w", ["1280"])[0]), 1280)
            if w > largura:
                frame = cv2.resize(frame, (largura, int(h * largura / w)))
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            return self._enviar(jpg.tobytes(), "image/jpeg")
        if caminho == "/placa":
            try:
                placas = ler_placas(frame)
                ALPR["erro"] = None
            except Exception as e:  # noqa: BLE001
                ALPR["erro"] = f"{type(e).__name__}: {e}"
                return self._json({"placas": [], "erro": ALPR["erro"]})
            res = {"placas": placas, "quando": quando}
            if placas and q.get("foto"):  # a imagem exata em que a placa foi lida
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    res["foto"] = base64.b64encode(jpg.tobytes()).decode()
            return self._json(res)
        self._json({"erro": "rota não encontrada"}, 404)


def vigiar_pai(pid):
    """Fecha este programa quando o servidor principal for fechado."""
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if h:
            k.WaitForSingleObject(h, 0xFFFFFFFF)
    else:
        while os.getppid() == pid:
            time.sleep(2)
    os._exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    ap.add_argument("--pai", type=int)
    a = ap.parse_args()
    with open(a.config, "r", encoding="utf-8") as f:
        cam = json.load(f).get("camera", {})
    if a.pai:
        threading.Thread(target=vigiar_pai, args=(a.pai,), daemon=True).start()
    threading.Thread(target=ler_video, args=(url_camera(cam),), daemon=True).start()
    if cam.get("ler_placa", True):  # já carrega o leitor para a 1ª placa sair rápido
        threading.Thread(target=modelo_alpr, daemon=True).start()
    porta = int(cam.get("porta_auxiliar") or 8092)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    except OSError as e:
        print(f"Câmera: porta {porta} ocupada ({e})", file=sys.stderr)
        os._exit(1)  # sai de vez (as linhas do vídeo não podem segurar o processo aberto)
    srv.serve_forever()


if __name__ == "__main__":
    main()
