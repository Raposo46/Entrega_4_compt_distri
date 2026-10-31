#!/usr/bin/env python3
"""Serviço de API do Link Extractor - versão Python (Flask + Gunicorn + Redis opcional).

Baseado nas etapas step4/step5 do repositório oficial ibnesayeed/linkextractor:
  GET /               -> mensagem de uso
  GET /api/<url>      -> lista JSON [{"text": ..., "href": ...}] dos links de <url>
  GET /api?url=<url>  -> mesma operação recebendo a URL via query string
  GET /health         -> verificação de saúde (usada pelo Docker Compose e orquestrador)

Variáveis de ambiente:
  CACHE_ENABLED    "true" ativa o cache Redis; "false" extrai direto a cada chamada
  REDIS_URL        endereço do Redis (padrão: redis://redis:6379/0)
  CACHE_TTL        TTL das chaves no Redis em segundos (padrão: 3600)
  CONNECT_TIMEOUT  timeout de conexão HTTP externa em s (padrão: 3)
  REQUEST_TIMEOUT  timeout de leitura HTTP externa em s (padrão: 5)
"""

import json
import logging
import os
import re
import threading
from urllib.parse import urlparse

import redis
from flask import Flask, jsonify, request

from linkextractor import ErroExtracao, extract_links

CACHE_ENABLED = os.getenv("CACHE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "sim")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("linkextractor.python")

app = Flask(__name__)
app.url_map.merge_slashes = False

cache = None
if CACHE_ENABLED:
    cache = redis.Redis.from_url(REDIS_URL, socket_timeout=1.5, socket_connect_timeout=1.5)
    log.info("Cache Redis HABILITADO (%s, ttl=%ss)", REDIS_URL, CACHE_TTL)
else:
    log.info("Cache DESABILITADO: toda chamada extrai os links diretamente da URL")


def normalizar_url(url: str) -> str:
    """Aceita 'https://site', 'https:/site' (barra colapsada por proxy/WSGI) ou 'site'."""
    url = (url or "").strip()
    url = re.sub(r"^(https?):/+", r"\1://", url, flags=re.IGNORECASE)
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "http://" + url
    partes = urlparse(url)
    if not partes.netloc:
        raise ErroExtracao(400, "URL inválida")
    return url


_guarda_locks = threading.Lock()
_locks_por_chave: dict[str, threading.Lock] = {}


def _lock_chave(chave: str) -> threading.Lock:
    with _guarda_locks:
        lk = _locks_por_chave.get(chave)
        if lk is None:
            lk = threading.Lock()
            _locks_por_chave[chave] = lk
        return lk


def obter_links(url: str) -> tuple[str, str]:
    """Retorna (json_str, status_cache) onde status_cache é HIT, MISS ou BYPASS."""
    if cache is None:
        return json.dumps(extract_links(url)), "BYPASS"

    chave = "links:" + url
    try:
        guardado = cache.get(chave)
        if guardado is not None:
            return guardado.decode("utf-8"), "HIT"
    except redis.RedisError as erro:
        log.warning("Redis indisponível na leitura (%s); extraindo sem cache", erro)
        return json.dumps(extract_links(url)), "BYPASS"

    # Coalescência de cache miss (evita thundering herd quando múltiplas threads pedem a mesma URL fria)
    with _lock_chave(chave):
        try:
            guardado = cache.get(chave)
            if guardado is not None:
                return guardado.decode("utf-8"), "HIT"
        except redis.RedisError:
            pass

        conteudo = json.dumps(extract_links(url))
        try:
            cache.set(chave, conteudo, ex=CACHE_TTL)
        except redis.RedisError as erro:
            log.warning("Redis indisponível na escrita (%s)", erro)
        return conteudo, "MISS"


@app.get("/")
def index():
    return "Usage: http://<hostname>[:<prt>]/api/<url>"


@app.get("/api")
@app.get("/api/<path:url>")
def api(url=None):
    if url is None:
        url = request.args.get("url", "")
    elif request.query_string:
        url += "?" + request.query_string.decode("utf-8", "replace")
    try:
        conteudo, origem = obter_links(normalizar_url(url))
    except ErroExtracao as erro:
        resposta = jsonify(error=erro.mensagem, url=url)
        resposta.status_code = erro.status
        return resposta
    return app.response_class(conteudo, status=200, mimetype="application/json", headers={"X-Cache": origem})


@app.get("/health")
def health():
    redis_ok = None
    if cache is not None:
        try:
            redis_ok = bool(cache.ping())
        except redis.RedisError:
            redis_ok = False
    return jsonify(status="ok", linguagem="python", cache=CACHE_ENABLED, redis=redis_ok)
