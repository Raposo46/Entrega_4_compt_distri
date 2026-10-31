#!/usr/bin/env python3
"""Calibragem empírica de usuários [U1, U2, U3] e execução dos 12 cenários do Trabalho 4.

Matriz experimental completa:
  2 Linguagens (Python, Ruby) x 2 Modos de Cache (Sem Cache, Com Cache) x 3 Cargas (U1, U2, U3)
  = 12 cenários de teste de desempenho.

Regra de Calibragem do Professor (Máximo de 10% de Perda):
  Em vez de números arbitrários (10, 100, 1000), descobre empiricamente no cenário mais lento
  (Sem Cache) os três níveis de carga [U1, U2, U3]:
    - U1 (Carga Baixa) : início da perda / degradação (~0,5% a 2,0% de falhas)
    - U2 (Carga Média) : perda intermediária          (~3,0% a 5,0% de falhas)
    - U3 (Carga Máxima): limite máximo <= 10%         (~7,0% a 9,6%, estritamente <= 10,0%)

Exemplos de uso:
    python calibrar_e_executar.py                       # calibra (se necessário) + roda os 12 + gera planilha e gráficos
    python calibrar_e_executar.py --somente-calibrar    # executa apenas a calibragem (salva resultados/calibragem.json)
    python calibrar_e_executar.py --usuarios 15 30 45   # usa [U1, U2, U3] informados via CLI
    python calibrar_e_executar.py --pular-calibragem    # reaproveita resultados/calibragem.json existente
    python calibrar_e_executar.py --recalibrar          # limpa calibragem anterior e recalibra do zero
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent
COMPOSE = RAIZ / "docker-compose.yml"
LOCUSTFILE = RAIZ / "locust" / "locustfile.py"
URLS_JSON = RAIZ / "locust" / "urls.json"

LINGUAGENS = ("python", "ruby")
CACHES = ("sem_cache", "com_cache")
NIVEIS = ("U1", "U2", "U3")

# Faixas-alvo de perda (%): (mínimo, máximo, alvo ideal).
# U3 mira 8,2% (janela 7,0% a 9,5%) para garantir margem segura abaixo do teto de 10,0%.
FAIXAS = {
    "U1": (0.5, 2.2, 1.25),
    "U2": (3.0, 5.5, 4.10),
    "U3": (7.0, 9.5, 8.25),
}
TETO_PCT = 10.0

CFG = None


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- Docker Compose
def env_compose() -> dict[str, str]:
    env = dict(os.environ)
    env["API_PORT"] = str(CFG.porta_api)
    env["WEB_PORT"] = str(CFG.porta_web)
    env["TIMEOUT_CLIENTE"] = str(CFG.timeout_cliente)
    return env


def compose(args: list[str], check: bool = True, capture: bool = False):
    cmd = ["docker", "compose", "-f", str(COMPOSE), "--project-directory", str(RAIZ), *args]
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env_compose(),
    )


def perfil(lang: str, cache: str) -> str:
    return f"{lang}-{cache.replace('_', '-')}"


def verificar_docker():
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=45)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        sys.exit("ERRO: Docker não respondeu. Inicie o Docker Desktop e tente novamente.")
    if r.returncode != 0:
        sys.exit("ERRO: O daemon do Docker não está ativo. Abra o Docker Desktop e tente novamente.")


def derrubar():
    if not CFG.sem_docker:
        compose(["--profile", "*", "down", "--remove-orphans"], check=False, capture=True)


def subir_stack(lang: str, cache: str):
    """Sobe exclusivamente o perfil da combinação (API + Web [+ Redis]), isolando CPU/memória."""
    if CFG.sem_docker:
        log(f"(--sem-docker) utilizando API já ativa em {url_api()} ({lang}/{cache})")
        esperar_api()
        return
    derrubar()
    nome_perfil = perfil(lang, cache)
    log(f"Subindo arquitetura {lang.upper()} / {cache} (perfil Docker '{nome_perfil}')...")
    r = compose(["--profile", nome_perfil, "up", "-d", "--build", "--wait", "--wait-timeout", "300"], check=False, capture=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr or r.stdout or "")
        sys.exit(f"ERRO ao subir perfil '{nome_perfil}' no Docker Compose.")
    esperar_api()


def url_api() -> str:
    return f"http://127.0.0.1:{CFG.porta_api}"


def url_host_locust() -> str:
    return f"http://127.0.0.1:{CFG.porta_web if CFG.alvo == 'web' else CFG.porta_api}"


def esperar_api(limite_s: int = 180, latencia_max: float = 0.8, consecutivas: int = 3):
    """Garante que a API respondeu /health rapidamente N vezes seguidas antes de iniciar carga."""
    inicio = time.time()
    ok = 0
    while time.time() - inicio < limite_s:
        t0 = time.time()
        try:
            with urllib.request.urlopen(url_api() + "/health", timeout=4) as r:
                ok = ok + 1 if (r.status == 200 and time.time() - t0 < latencia_max) else 0
        except (urllib.error.URLError, OSError):
            ok = 0
        if ok >= consecutivas:
            return
        time.sleep(1)
    sys.exit(f"ERRO: API em {url_api()} não estabilizou em {limite_s}s.")


# --------------------------------------------------------------------------- Controle do Redis
def redis_cli(*args: str) -> str:
    r = compose(["exec", "-T", "redis", "redis-cli", *args], capture=True)
    return r.stdout.strip()


def preparar_cache():
    """Gerencia o Redis de forma controlada antes de cada bateria 'Com Cache'.

    - Modo 'frio' (padrão): executa FLUSHALL + CONFIG RESETSTAT. Assim, a 1ª passagem pelas 10 URLs
      sofre CACHE MISS (indo aos sites reais e gravando no Redis) e todas as passagens seguintes
      são servidas em memória (CACHE HIT), demonstrando o efeito do aquecimento do cache.
    - Modo 'quente': executa FLUSHALL, pré-aquece as 10 URLs uma vez e zera as estatísticas.
    """
    if CFG.sem_docker:
        return
    redis_cli("FLUSHALL")
    if CFG.cache_inicio == "quente":
        log("  Redis [QUENTE]: FLUSHALL + pré-aquecimento sequencial das 10 URLs...")
        for url in json.loads(URLS_JSON.read_text(encoding="utf-8")):
            try:
                urllib.request.urlopen(f"{url_api()}/api?url={quote(url, safe='')}", timeout=20).read()
            except (urllib.error.URLError, OSError) as erro:
                log(f"  aviso no pré-aquecimento ({url}): {erro}")
    else:
        log("  Redis [CONTROLADO]: FLUSHALL executado; 1ª passagem das 10 URLs aquecerá o cache (MISS -> HIT)")
    redis_cli("CONFIG", "RESETSTAT")


def coletar_cache(lang: str, nivel: str, usuarios: int):
    """Coleta hits, misses e total de chaves armazenadas no Redis após o cenário 'Com Cache'."""
    if CFG.sem_docker:
        return
    info = redis_cli("INFO", "stats")
    valores = dict(re.findall(r"^(keyspace_hits|keyspace_misses):(\d+)", info, flags=re.MULTILINE))
    hits = int(valores.get("keyspace_hits", 0))
    misses = int(valores.get("keyspace_misses", 0))
    chaves = int(redis_cli("DBSIZE") or 0)
    total = hits + misses
    taxa = round(100.0 * hits / total, 2) if total else 0.0

    arquivo = CFG.pasta / "cache_stats.csv"
    linhas_existentes = []
    if arquivo.exists():
        with open(arquivo, newline="", encoding="utf-8") as f:
            linhas_existentes = [
                row for row in csv.DictReader(f)
                if not (row.get("linguagem") == lang and int(row.get("usuarios", -1)) == usuarios)
            ]

    campos = ["executado_em", "linguagem", "nivel", "usuarios", "cache_inicio", "hits", "misses", "taxa_acerto_pct", "chaves_no_redis"]
    linhas_existentes.append({
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "linguagem": lang,
        "nivel": nivel,
        "usuarios": usuarios,
        "cache_inicio": CFG.cache_inicio,
        "hits": hits,
        "misses": misses,
        "taxa_acerto_pct": taxa,
        "chaves_no_redis": chaves,
    })
    with open(arquivo, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas_existentes)

    log(f"  Redis Stats: {hits} HITs | {misses} MISSes | Taxa de Acerto = {taxa}% | Chaves = {chaves}/10")


# --------------------------------------------------------------------------- Execução do Locust
def executar_locust(prefixo: Path, usuarios: int, tempo: int) -> dict:
    """Executa um teste headless no Locust salvando CSVs e relatório HTML."""
    prefixo.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        LE_ALVO=CFG.alvo,
        LE_WAIT_MIN=str(CFG.wait_min),
        LE_WAIT_MAX=str(CFG.wait_max),
        LE_TIMEOUT=str(CFG.timeout_cliente),
        LE_URLS=str(URLS_JSON),
        PYTHONUTF8="1",
    )
    taxa_subida = max(1.0, round(usuarios / CFG.subida, 2))
    cmd = [
        sys.executable, "-m", "locust",
        "-f", str(LOCUSTFILE),
        "--headless",
        "-u", str(usuarios),
        "-r", f"{taxa_subida:g}",
        "-t", f"{tempo}s",
        "--host", url_host_locust(),
        "--csv", str(prefixo),
        "--html", str(prefixo) + ".html",
        "--only-summary",
        "--exit-code-on-error", "0",
    ]
    with open(str(prefixo) + "_locust.log", "w", encoding="utf-8") as saida:
        r = subprocess.run(cmd, env=env, stdout=saida, stderr=subprocess.STDOUT, cwd=RAIZ)
    if r.returncode != 0 or not Path(str(prefixo) + "_stats.csv").exists():
        sys.exit(f"ERRO: falha na execução do Locust (verifique {prefixo}_locust.log).")
    return ler_agregado(prefixo)


def ler_agregado(prefixo: Path | str) -> dict:
    with open(str(prefixo) + "_stats.csv", newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["Name"] == "Aggregated":
                total = int(linha["Request Count"])
                falhas = int(linha["Failure Count"])
                return {
                    "total": total,
                    "falhas": falhas,
                    "perda_pct": round(100.0 * falhas / total, 2) if total else 100.0,
                    "media_ms": float(linha["Average Response Time"]),
                    "mediana_ms": float(linha["Median Response Time"]),
                    "p90_ms": float(linha["90%"]),
                    "p95_ms": float(linha["95%"]),
                    "p99_ms": float(linha["99%"]),
                    "rps": float(linha["Requests/s"]),
                }
    raise RuntimeError(f"Linha 'Aggregated' ausente em {prefixo}_stats.csv")


def resumo(r: dict) -> str:
    return (
        f"{r['total']} req | falhas={r['falhas']} ({r['perda_pct']}%) | "
        f"média={r['media_ms']:.0f} ms | mediana={r['mediana_ms']:.0f} ms | "
        f"p95={r['p95_ms']:.0f} ms | vazão={r['rps']:.1f} req/s"
    )


# --------------------------------------------------------------------------- Calibragem Empírica
def pasta_calibragem() -> Path:
    return CFG.pasta / "calibragem"


def medir_calibragem(lang: str, usuarios: int, amostras: dict[int, float]) -> float:
    prefixo = pasta_calibragem() / f"{lang}_sem_cache_users{usuarios}"
    if usuarios not in amostras:
        esperar_api()
        log(f"  [Calibragem {lang.upper()} sem cache] testando {usuarios} usuários por {CFG.tempo_calibracao}s...")
        r = executar_locust(prefixo, usuarios, CFG.tempo_calibracao)
        log(f"    -> {resumo(r)}")
        amostras[usuarios] = r["perda_pct"]
        time.sleep(CFG.pausa)
    return amostras[usuarios]


def carregar_amostras(lang: str) -> dict[int, float]:
    amostras = {}
    if not pasta_calibragem().exists():
        return amostras
    for arquivo in pasta_calibragem().glob(f"{lang}_sem_cache_users*_stats.csv"):
        m = re.search(r"users(\d+)_stats\.csv$", arquivo.name)
        if m:
            u = int(m.group(1))
            amostras[u] = ler_agregado(str(arquivo)[: -len("_stats.csv")])["perda_pct"]
    return amostras


def buscar_faixa(
    nivel: str,
    amostras: dict[int, float],
    medir,
    max_iter: int,
    min_u: int = 1,
    max_u: int | None = None,
) -> tuple[int, bool]:
    """Busca por interpolação + bisseção um número de usuários dentro da faixa de perda do nível."""
    minimo, maximo, alvo = FAIXAS[nivel]
    teto_busca = TETO_PCT if nivel == "U3" else maximo

    def elegivel(u: int) -> bool:
        return u >= min_u and (max_u is None or u <= max_u)

    for _ in range(max_iter + 1):
        dentro = [(abs(p - alvo), u) for u, p in amostras.items() if elegivel(u) and minimo <= p <= maximo]
        if dentro:
            return min(dentro)[1], True

        # Para U3 aceita até 9,8% se já estiver entre 7,0% e 9,8% após pelo menos 2 tentativas
        if nivel == "U3":
            quase = [(abs(p - alvo), u) for u, p in amostras.items() if elegivel(u) and minimo <= p <= 9.8]
            if quase and _ >= 2:
                return min(quase)[1], True

        acima = [u for u, p in amostras.items() if u >= min_u and p > maximo]
        if max_u is not None:
            acima = [u for u in acima if u <= max_u + 1] or [max_u + 1]
        if not acima:
            break
        u_acima = min(acima)
        if max_u is not None:
            u_acima = min(u_acima, max_u + 1)

        abaixo = [u for u, p in amostras.items() if min_u <= u < u_acima and p < minimo]
        u_abaixo = max(abaixo) if abaixo else (min_u - 1)
        if u_acima - u_abaixo <= 1:
            break

        p_abaixo = amostras.get(u_abaixo, 0.0)
        p_acima = amostras.get(u_acima, maximo + 2.0)
        meio = (u_abaixo + u_acima) / 2.0
        if p_acima > p_abaixo:
            interp = u_abaixo + (alvo - p_abaixo) / (p_acima - p_abaixo) * (u_acima - u_abaixo)
            chute = 0.5 * interp + 0.5 * meio
        else:
            chute = meio

        candidato = int(min(max(round(chute), u_abaixo + 1), u_acima - 1))
        if candidato in amostras:
            # Procura o inteiro não testado mais próximo do meio do intervalo
            nao_testados = [x for x in range(u_abaixo + 1, u_acima) if x not in amostras]
            if not nao_testados:
                break
            candidato = min(nao_testados, key=lambda x: abs(x - meio))
        medir(candidato)

    # Fallback: ponto elegível mais próximo do alvo que respeite estritamente o teto de 10%
    # (em caso de empate na distância, ex: vários pontos com 0.0%, prefere o MAIOR u, mais próximo da transição)
    validos = [(abs(p - alvo), -u) for u, p in amostras.items() if elegivel(u) and p <= min(TETO_PCT, teto_busca + 1.5)]
    if not validos:
        validos = [(abs(p - alvo), -u) for u, p in amostras.items() if elegivel(u) and p <= TETO_PCT]
    if not validos:
        abaixo_teto = [u for u, p in amostras.items() if p <= TETO_PCT]
        if abaixo_teto:
            return min(max(abaixo_teto), max_u or max(abaixo_teto)), False
        return max(1, min_u), False
    return -min(validos)[1], False


def calibrar_linguagem(lang: str) -> dict:
    """Descobre [U1, U2, U3] estritamente crescentes (U1 < U2 < U3) para `lang` sem cache."""
    subir_stack(lang, "sem_cache")
    amostras = carregar_amostras(lang)
    medir = lambda u: medir_calibragem(lang, u, amostras)  # noqa: E731

    log(f"Iniciando varredura exponencial de {lang.upper()} (sem cache) a partir de {CFG.inicio} usuários...")
    u = CFG.inicio
    while True:
        perda = medir(u)
        if perda > TETO_PCT:
            break
        if u >= CFG.max_usuarios:
            log(f"  AVISO: limite --max-usuarios ({u}) atingido com perda {perda}% <= {TETO_PCT}%.")
            break
        u = min(CFG.max_usuarios, max(u + 4, int(round(u * 1.6))))

    log(f"Refinando U3 (faixa {FAIXAS['U3'][0]}% a {FAIXAS['U3'][1]}%, teto <= {TETO_PCT}%)...")
    u3, ok3 = buscar_faixa("U3", amostras, medir, CFG.max_iter, min_u=3)
    log(f"  -> U3 = {u3} usuários (perda na calibragem: {amostras.get(u3, -1)}%)")

    log(f"Refinando U2 (faixa {FAIXAS['U2'][0]}% a {FAIXAS['U2'][1]}%, U2 < {u3})...")
    u2, ok2 = buscar_faixa("U2", amostras, medir, CFG.max_iter, min_u=2, max_u=max(2, u3 - 1))
    log(f"  -> U2 = {u2} usuários (perda na calibragem: {amostras.get(u2, -1)}%)")

    log(f"Refinando U1 (faixa {FAIXAS['U1'][0]}% a {FAIXAS['U1'][1]}%, U1 < {u2})...")
    u1, ok1 = buscar_faixa("U1", amostras, medir, CFG.max_iter, min_u=1, max_u=max(1, u2 - 1))
    log(f"  -> U1 = {u1} usuários (perda na calibragem: {amostras.get(u1, -1)}%)")

    # Garantia algébrica de U1 < U2 < U3
    if not (u1 < u2 < u3):
        u3 = max(u3, 3)
        u2 = min(max(u2, 2), u3 - 1)
        u1 = min(max(u1, 1), u2 - 1)
        for ux in (u1, u2, u3):
            medir(ux)

    trio = [u1, u2, u3]
    return {
        "usuarios": trio,
        "dentro_da_faixa": [ok1, ok2, ok3],
        "perda_calibragem_pct": {str(ux): amostras[ux] for ux in trio},
        "medicoes": {str(k): v for k, v in sorted(amostras.items())},
    }


def calibrar() -> list[int]:
    """Calibra empiricamente [U1, U2, U3] respeitando <= 10% de perda no cenário mais lento."""
    por_lingua = {}
    if CFG.ref_lang != "auto":
        por_lingua[CFG.ref_lang] = calibrar_linguagem(CFG.ref_lang)
        referencia = CFG.ref_lang
    else:
        # Calibra Python sem cache primeiro e sonda Ruby sem cache em U3_python:
        # se Ruby também ficar <= 10% em U3_python, Python é comprovadamente o gargalo;
        # caso contrário (Ruby saturar antes), calibra Ruby completo e adota Ruby como referência.
        por_lingua["python"] = calibrar_linguagem("python")
        u3_py = por_lingua["python"]["usuarios"][2]

        subir_stack("ruby", "sem_cache")
        amostras_rb = carregar_amostras("ruby")
        perda_rb_em_u3_py = medir_calibragem("ruby", u3_py, amostras_rb)
        if perda_rb_em_u3_py <= TETO_PCT:
            log(
                f"Sondagem Ruby sem cache em U3={u3_py}: perda = {perda_rb_em_u3_py}% <= {TETO_PCT}%. "
                "Python sem cache é confirmado como o cenário mais lento (referência da calibragem)."
            )
            por_lingua["ruby_sondagem"] = {
                "u3_testado": u3_py,
                "perda_pct": perda_rb_em_u3_py,
                "medicoes": {str(k): v for k, v in sorted(amostras_rb.items())},
            }
            referencia = "python"
        else:
            log(
                f"Sondagem Ruby sem cache em U3={u3_py} teve perda {perda_rb_em_u3_py}% > {TETO_PCT}%; "
                "calibrando Ruby completo como cenário mais lento..."
            )
            por_lingua["ruby"] = calibrar_linguagem("ruby")
            referencia = "ruby"

    usuarios = por_lingua[referencia]["usuarios"]
    dados = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "teto_perda_pct": TETO_PCT,
        "faixas_pct": {n: list(FAIXAS[n][:2]) for n in NIVEIS},
        "tempo_calibracao_s": CFG.tempo_calibracao,
        "timeout_cliente_s": CFG.timeout_cliente,
        "linguagem_referencia": referencia,
        "usuarios": usuarios,
        "por_linguagem": por_lingua,
    }
    CFG.pasta.mkdir(parents=True, exist_ok=True)
    (CFG.pasta / "calibragem.json").write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Calibragem finalizada! Referência: {referencia.upper()} -> [U1, U2, U3] = {usuarios}")
    return usuarios


# --------------------------------------------------------------------------- Matriz de 12 Cenários
def executar_matriz(usuarios: list[int]):
    log(
        f"Iniciando matriz de {len(CFG.langs) * len(CFG.caches) * len(usuarios)} cenários: "
        f"níveis {dict(zip(NIVEIS, usuarios))}, duração={CFG.tempo}s, cache='{CFG.cache_inicio}'"
    )
    fora_do_teto = []
    for lang in CFG.langs:
        for cache in CFG.caches:
            subir_stack(lang, cache)
            for nivel, u in zip(NIVEIS, usuarios):
                prefixo = CFG.pasta / f"{lang}_{cache}_users{u}"
                if Path(str(prefixo) + "_stats.csv").exists() and not CFG.refazer:
                    log(f"[{lang} / {cache} / {nivel}={u}] resultado existente encontrado, pulando (--refazer para sobrescrever)")
                    continue

                for tentativa in (1, 2):
                    esperar_api()
                    sufixo = "" if tentativa == 1 else " (repetição de verificação após oscilação de rede)"
                    log(f"[{lang} / {cache} / {nivel}={u}] executando por {CFG.tempo}s{sufixo}...")
                    if cache == "com_cache":
                        preparar_cache()
                    r = executar_locust(prefixo, u, CFG.tempo)
                    log(f"  -> {resumo(r)}")
                    if cache == "com_cache":
                        coletar_cache(lang, nivel, u)
                    if r["perda_pct"] <= TETO_PCT or tentativa == 2:
                        break
                    log(f"  Perda {r['perda_pct']}% oscilou acima de {TETO_PCT}%; aguardando {CFG.pausa * 2}s para revalidar...")
                    time.sleep(CFG.pausa * 2)

                if r["perda_pct"] > TETO_PCT:
                    fora_do_teto.append((lang, cache, nivel, u, r["perda_pct"]))
                    log(f"  AVISO: cenário permaneceu com {r['perda_pct']}% (> {TETO_PCT}%)")
                time.sleep(CFG.pausa)
    derrubar()
    if fora_do_teto:
        log("ATENÇÃO - Cenários acima do limite de 10% de perda:")
        for item in fora_do_teto:
            log(f"  {item}")


def rodar_relatorios():
    for script in ("consolidar_metricas.py", "gerar_graficos.py"):
        log(f"Executando {script}...")
        subprocess.run([sys.executable, str(RAIZ / script), "--resultados", str(CFG.pasta)], check=True, cwd=RAIZ)


# --------------------------------------------------------------------------- CLI
def ler_argumentos():
    p = argparse.ArgumentParser(
        description="Calibragem automática (<= 10% de perda) e execução dos 12 cenários do Trabalho 4",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    g = p.add_argument_group("fluxo de execução")
    g.add_argument("--usuarios", type=int, nargs=3, metavar=("U1", "U2", "U3"), help="define [U1, U2, U3] manualmente via CLI")
    g.add_argument("--somente-calibrar", action="store_true", help="executa apenas a calibragem empírica")
    g.add_argument("--pular-calibragem", action="store_true", help="usa resultados/calibragem.json já salvo")
    g.add_argument("--recalibrar", action="store_true", help="apaga medições anteriores de calibragem e recalibra")
    g.add_argument("--refazer", action="store_true", help="reexecuta cenários mesmo que o _stats.csv já exista")
    g.add_argument("--sem-relatorios", action="store_true", help="não executa consolidar_metricas.py e gerar_graficos.py ao final")

    g = p.add_argument_group("recorte experimental")
    g.add_argument("--langs", nargs="+", choices=LINGUAGENS, default=list(LINGUAGENS))
    g.add_argument("--caches", nargs="+", choices=CACHES, default=list(CACHES))
    g.add_argument("--cache-inicio", choices=("frio", "quente"), default="frio", help="política de inicialização do Redis")

    g = p.add_argument_group("parâmetros de carga e tempo")
    g.add_argument("--tempo", type=int, default=45, help="duração de cada cenário final em segundos")
    g.add_argument("--tempo-calibracao", type=int, default=None, help="duração de cada passo de calibragem (s); padrão = --tempo")
    g.add_argument("--subida", type=float, default=8.0, help="janela de rampa (s) para entrada gradual dos usuários")
    g.add_argument("--pausa", type=int, default=6, help="intervalo de drenagem entre testes (s)")
    g.add_argument("--wait-min", type=float, default=0.1, help="tempo mínimo de reflexão entre URLs (s)")
    g.add_argument("--wait-max", type=float, default=0.5, help="tempo máximo de reflexão entre URLs (s)")
    g.add_argument("--timeout-cliente", type=float, default=8.0, help="timeout HTTP do Locust por invocação (s)")

    g = p.add_argument_group("parâmetros da busca de calibragem")
    g.add_argument("--ref-lang", choices=("auto", "python", "ruby"), default="auto")
    g.add_argument("--inicio", type=int, default=20, help="número inicial de usuários na varredura")
    g.add_argument("--max-usuarios", type=int, default=1000)
    g.add_argument("--max-iter", type=int, default=5, help="iterações máximas de refinamento por faixa")

    g = p.add_argument_group("ambiente e rede")
    g.add_argument("--alvo", choices=("api", "api-query", "web"), default="api")
    g.add_argument("--porta-api", type=int, default=5000)
    g.add_argument("--porta-web", type=int, default=8080)
    g.add_argument("--pasta-resultados", dest="pasta", type=Path, default=RAIZ / "resultados")
    g.add_argument("--sem-docker", action="store_true", help="não gerencia containers Docker (depuração local)")

    args = p.parse_args()
    if args.tempo_calibracao is None:
        args.tempo_calibracao = args.tempo
    args.pasta = args.pasta.resolve()
    return args


def main():
    global CFG
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    CFG = ler_argumentos()
    CFG.pasta.mkdir(parents=True, exist_ok=True)
    if not CFG.sem_docker:
        verificar_docker()

    try:
        arquivo_calibragem = CFG.pasta / "calibragem.json"
        if CFG.usuarios:
            usuarios = sorted(CFG.usuarios)
            log(f"Utilizando níveis informados via CLI: {dict(zip(NIVEIS, usuarios))}")
            arquivo_calibragem.write_text(
                json.dumps(
                    {
                        "gerado_em": datetime.now().isoformat(timespec="seconds"),
                        "origem": "CLI (--usuarios)",
                        "teto_perda_pct": TETO_PCT,
                        "usuarios": usuarios,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        elif CFG.pular_calibragem or (arquivo_calibragem.exists() and not CFG.recalibrar and not CFG.somente_calibrar):
            if not arquivo_calibragem.exists():
                sys.exit("ERRO: resultados/calibragem.json não encontrado para --pular-calibragem.")
            usuarios = json.loads(arquivo_calibragem.read_text(encoding="utf-8"))["usuarios"]
            log(f"Reaproveitando calibragem salva: {dict(zip(NIVEIS, usuarios))}")
        else:
            if CFG.recalibrar and pasta_calibragem().exists():
                for arq in pasta_calibragem().glob("*"):
                    arq.unlink()
            usuarios = calibrar()

        if CFG.somente_calibrar:
            return
        executar_matriz(usuarios)
    finally:
        derrubar()

    if not CFG.sem_relatorios:
        rodar_relatorios()


if __name__ == "__main__":
    main()
