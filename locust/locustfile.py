"""Comportamento do Usuário Virtual no Locust - Trabalho 4 (Link Extractor).

REGRA OBRIGATÓRIA DO ENUNCIADO:
Cada usuário virtual realiza uma SEQUÊNCIA DE 10 INVOCAÇÕES ao serviço de extração de links,
passando uma URL DIFERENTE como parâmetro a cada invocação (lista definida em locust/urls.json).

Implementação:
- Utiliza `SequentialTaskSet` com 10 tasks geradas a partir de `urls.json` (10 domínios reais,
  estáveis e distintos), garantindo execução estritamente sequencial de 1 a 10.
- Valida rigorosamente o status HTTP 200 e o payload JSON retornado (`[{"text": ..., "href": ...}]`),
  marcando qualquer erro HTTP (4xx/5xx, incluindo 502/504 de timeout da API), timeout do cliente
  ou resposta inválida/vazia como FALHA contabilizada no Locust.

Variáveis de ambiente opcionais:
  LE_URLS            caminho para o JSON com as 10 URLs (padrão: locust/urls.json)
  LE_ALVO            "api"       -> GET /api/<url>       (padrão, rota oficial do Link Extractor)
                     "api-query" -> GET /api?url=<url>
                     "web"       -> GET /?url=<url>      (passando pelo front-end PHP)
  LE_WAIT_MIN/MAX    tempo de reflexão entre invocações em s (padrão: 0.1 a 0.5)
  LE_TIMEOUT         timeout por requisição no Locust em s   (padrão: 8)
  LE_UMA_SEQUENCIA   "1" encerra o usuário após concluir 1 sequência de 10 URLs (padrão: "0")
"""

import json
import os
from pathlib import Path
from urllib.parse import quote

from locust import SequentialTaskSet, between
from locust.contrib.fasthttp import FastHttpUser

ARQUIVO_URLS = Path(os.environ.get("LE_URLS") or Path(__file__).with_name("urls.json"))
ALVO = os.environ.get("LE_ALVO", "api")
WAIT_MIN = float(os.environ.get("LE_WAIT_MIN", "0.1"))
WAIT_MAX = float(os.environ.get("LE_WAIT_MAX", "0.5"))
TIMEOUT = float(os.environ.get("LE_TIMEOUT", "8"))
UMA_SEQUENCIA = os.environ.get("LE_UMA_SEQUENCIA", "0") == "1"

with open(ARQUIVO_URLS, encoding="utf-8") as arquivo:
    URLS = json.load(arquivo)

assert len(URLS) == 10, f"O enunciado exige exatamente 10 URLs; {ARQUIVO_URLS} possui {len(URLS)}"
assert len(set(URLS)) == 10, "As 10 URLs de urls.json devem ser todas distintas"
assert ALVO in ("api", "api-query", "web"), "LE_ALVO deve ser 'api', 'api-query' ou 'web'"


def montar_caminho(url: str) -> str:
    if ALVO == "api":
        return "/api/" + quote(url, safe=":/")
    if ALVO == "api-query":
        return "/api?url=" + quote(url, safe="")
    return "/?url=" + quote(url, safe="")


def validar_corpo(resposta) -> tuple[bool, str]:
    if ALVO == "web":
        if 'id="links"' in resposta.text:
            return True, ""
        return False, "HTML do front-end sem lista de links extraídos"
    try:
        dados = json.loads(resposta.text)
    except ValueError:
        return False, "resposta não é JSON válido"
    if not isinstance(dados, list) or len(dados) == 0:
        return False, "lista de links vazia ou inválida"
    primeiro = dados[0]
    if isinstance(primeiro, dict) and "href" not in primeiro:
        return False, "objeto de link sem campo href"
    return True, ""


def criar_invocacao(indice: int, url: str):
    """Gera a task sequencial `indice + 1` (de 01 a 10) para uma URL específica."""
    rotulo = f"{indice + 1:02d} {url.split('//', 1)[-1]}"
    caminho = montar_caminho(url)

    def invocar(self):
        with self.client.get(caminho, name=rotulo, catch_response=True) as resposta:
            if resposta.status_code != 200:
                resposta.failure(f"HTTP {resposta.status_code}")
            else:
                ok, motivo = validar_corpo(resposta)
                if not ok:
                    resposta.failure(motivo)

        if UMA_SEQUENCIA and indice == len(URLS) - 1:
            self.user.stop()

    invocar.__name__ = f"invocacao_{indice + 1:02d}"
    return invocar


class SequenciaDeDezInvocacoes(SequentialTaskSet):
    """Executa sequencialmente as 10 invocações, cada uma com uma URL distinta."""

    tasks = [criar_invocacao(i, url) for i, url in enumerate(URLS)]


class UsuarioLinkExtractor(FastHttpUser):
    tasks = [SequenciaDeDezInvocacoes]
    wait_time = between(WAIT_MIN, WAIT_MAX)
    connection_timeout = TIMEOUT
    network_timeout = TIMEOUT
    max_retries = 0
