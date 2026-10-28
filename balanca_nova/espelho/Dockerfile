# Espelho da Balança Transtino (Easypanel). Só biblioteca padrão do Python.
FROM python:3.12-slim
WORKDIR /app
COPY relay.py /app/relay.py
ENV PORTA=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/_saude',timeout=4)"
CMD ["python", "relay.py"]
