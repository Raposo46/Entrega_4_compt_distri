#!/usr/bin/env python3
"""Módulo de extração de links (baseado em step4/step5 de ibnesayeed/linkextractor).

Baixa o HTML da URL informada com timeouts explícitos de conexão e leitura
e extrai todas as âncoras <a href="..."> no formato oficial do Link Extractor:
    [{"text": "Texto do link ou [IMG]", "href": "https://url.absoluta/..."}]
"""

import os
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "3"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))
MAX_BYTES = 5 * 1024 * 1024  # limite defensivo de 5 MB por página
USER_AGENT = "Mozilla/5.0 (compatible; LinkExtractor-T4/1.0; +https://github.com/ibnesayeed/linkextractor)"


class ErroExtracao(Exception):
    """Erro controlado de extração com código HTTP apropriado (400, 502 ou 504)."""

    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def extract_links(url: str) -> list[dict[str, str]]:
    """Baixa a página com timeout controlado e devolve [{'text': ..., 'href': ...}]."""
    try:
        resp = requests.get(
            url,
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT),
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        try:
            if resp.status_code >= 400:
                raise ErroExtracao(502, f"site de origem respondeu HTTP {resp.status_code}")
            pedacos, total = [], 0
            for pedaco in resp.iter_content(chunk_size=65536):
                total += len(pedaco)
                if total > MAX_BYTES:
                    raise ErroExtracao(502, "página excede o limite de 5 MB")
                pedacos.append(pedaco)
            corpo = b"".join(pedacos)
            base = resp.url
        finally:
            resp.close()
    except requests.exceptions.Timeout:
        raise ErroExtracao(504, "timeout ao acessar o site de origem")
    except requests.exceptions.RequestException as erro:
        if "timed out" in str(erro).lower():
            raise ErroExtracao(504, "timeout ao acessar o site de origem")
        raise ErroExtracao(502, f"falha ao acessar o site de origem: {type(erro).__name__}")

    soup = BeautifulSoup(corpo, "lxml")
    tag_base = soup.find("base", href=True)
    if tag_base and tag_base["href"].strip():
        base = urljoin(base, tag_base["href"].strip())

    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        absoluto = urljoin(base, href)
        if urlparse(absoluto).scheme not in ("http", "https"):
            continue
        texto = " ".join(tag.get_text().split()) or "[IMG]"
        links.append({"text": texto, "href": absoluto})
    return links


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"\nUsage:\n\t{sys.argv[0]} <URL>\n")
        sys.exit(1)
    for item in extract_links(sys.argv[-1]):
        print(f"[{item['text']}]({item['href']})")

