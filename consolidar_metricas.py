#!/usr/bin/env python3
"""Consolidação de métricas e geração da planilha final do Trabalho 4 (Link Extractor).

Extrai a linha 'Aggregated' de cada arquivo `resultados/{lang}_{cache}_users{u}_stats.csv`
e exporta a tabela consolidada nos três formatos:
    - resultados/tabela_consolidada_trabalho4.csv
    - resultados/tabela_consolidada_trabalho4.xlsx  (com aba extra 'Cache Redis' se disponível)
    - resultados/tabela_consolidada_trabalho4.md

Métricas consolidadas:
  - Linguagem (Python ou Ruby)
  - Modo de Cache (Sem Cache ou Com Cache)
  - Nível (U1, U2, U3) e Número de Usuários Virtuais
  - Total de Requisições, Falhas, % de Perda e conformidade (Perda <= 10%)
  - Média e Mediana (50%) do Tempo de Resposta (ms)
  - Percentis 90%, 95%, 99% e Máximo do Tempo de Resposta (ms)
  - Vazão (Requests/s - RPS)
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent
PADRAO = re.compile(r"^(python|ruby)_(sem|com)_cache_users(\d+)_stats\.csv$")
NOME_LINGUAGEM = {"python": "Python", "ruby": "Ruby"}
NOME_CACHE = {"sem": "Sem Cache", "com": "Com Cache"}

COLUNAS = [
    "Linguagem",
    "Modo de Cache",
    "Nível",
    "Usuários Virtuais",
    "Total de Requisições",
    "Falhas",
    "% de Perda",
    "Perda <= 10%",
    "Média (ms)",
    "Mediana (ms)",
    "P90 (ms)",
    "P95 (ms)",
    "P99 (ms)",
    "Máximo (ms)",
    "Vazão (req/s)",
]


def ler_agregado(arquivo: Path) -> dict:
    with open(arquivo, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["Name"] == "Aggregated":
                return linha
    raise ValueError(f"Linha 'Aggregated' não encontrada em {arquivo}")


def niveis_calibrados(pasta: Path) -> list[int] | None:
    arquivo = pasta / "calibragem.json"
    if arquivo.exists():
        usuarios = json.loads(arquivo.read_text(encoding="utf-8")).get("usuarios")
        if usuarios and len(usuarios) == 3:
            return [int(u) for u in usuarios]
    return None


def montar_tabela(pasta: Path, teto: float) -> pd.DataFrame:
    arquivos = []
    for arquivo in sorted(pasta.glob("*_stats.csv")):
        m = PADRAO.match(arquivo.name)
        if m:
            arquivos.append((arquivo, m.group(1), m.group(2), int(m.group(3))))
    if not arquivos:
        sys.exit(f"ERRO: nenhum arquivo *_stats.csv encontrado em {pasta}. Execute calibrar_e_executar.py primeiro.")

    calibrados = niveis_calibrados(pasta)
    if calibrados:
        # Filtra apenas os arquivos pertencentes aos 3 níveis calibrados atuais (caso haja resíduos antigos)
        filtrados = [item for item in arquivos if item[3] in set(calibrados)]
        if filtrados:
            arquivos = filtrados

    usuarios_distintos = sorted({u for _, _, _, u in arquivos})
    referencia = calibrados if calibrados and set(usuarios_distintos) <= set(calibrados) else usuarios_distintos
    nivel_de = {u: f"U{i + 1}" for i, u in enumerate(sorted(referencia))}

    linhas = []
    for arquivo, lang, cache, usuarios in arquivos:
        a = ler_agregado(arquivo)
        total = int(a["Request Count"])
        falhas = int(a["Failure Count"])
        perda = 100.0 * falhas / total if total else 100.0
        linhas.append({
            "Linguagem": NOME_LINGUAGEM[lang],
            "Modo de Cache": NOME_CACHE[cache],
            "Nível": nivel_de.get(usuarios, f"U({usuarios})"),
            "Usuários Virtuais": usuarios,
            "Total de Requisições": total,
            "Falhas": falhas,
            "% de Perda": round(perda, 2),
            "Perda <= 10%": "Sim" if round(perda, 2) <= teto else "NÃO",
            "Média (ms)": round(float(a["Average Response Time"]), 2),
            "Mediana (ms)": round(float(a["Median Response Time"]), 2),
            "P90 (ms)": round(float(a["90%"]), 2),
            "P95 (ms)": round(float(a["95%"]), 2),
            "P99 (ms)": round(float(a["99%"]), 2),
            "Máximo (ms)": round(float(a["Max Response Time"]), 2),
            "Vazão (req/s)": round(float(a["Requests/s"]), 2),
        })

    df = pd.DataFrame(linhas, columns=COLUNAS)
    df["_l"] = df["Linguagem"].map({"Python": 0, "Ruby": 1})
    df["_c"] = df["Modo de Cache"].map({"Sem Cache": 0, "Com Cache": 1})
    df = df.sort_values(["_l", "_c", "Usuários Virtuais"]).drop(columns=["_l", "_c"]).reset_index(drop=True)
    return df


def carregar_cache_df(pasta: Path) -> pd.DataFrame | None:
    arq = pasta / "cache_stats.csv"
    if not arq.exists():
        return None
    df_c = pd.read_csv(arq)
    calibrados = niveis_calibrados(pasta)
    if calibrados and "usuarios" in df_c.columns:
        df_c = df_c[df_c["usuarios"].isin(calibrados)].copy()
    if df_c.empty:
        return None
    return df_c.sort_values(["linguagem", "usuarios"]).reset_index(drop=True)


def df_para_md(df: pd.DataFrame) -> str:
    cab = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    corpo = ["| " + " | ".join(str(v) for v in linha) + " |" for linha in df.itertuples(index=False)]
    return "\n".join([cab, sep, *corpo])


def para_markdown(df: pd.DataFrame, df_cache: pd.DataFrame | None, teto: float) -> str:
    blocos = [
        "# Trabalho 4 – Link Extractor: Tabela Consolidada de Desempenho",
        "",
        f"- **Fonte:** linha `Aggregated` dos relatórios `*_stats.csv` do Locust.",
        f"- **Unidades:** latências em milissegundos (`ms`); vazão em requisições por segundo (`req/s`).",
        f"- **Regra de Calibragem:** Taxa de Perda = `Failure Count / Request Count × 100` (limite máximo exigido: **{teto}%**).",
        "",
        "## Métricas dos 12 Cenários",
        "",
        df_para_md(df),
        "",
    ]
    if df_cache is not None:
        blocos.extend([
            "## Estatísticas do Cache Redis (Baterias Com Cache)",
            "",
            df_para_md(df_cache),
            "",
        ])
    return "\n".join(blocos)


def formatar_aba(planilha):
    from openpyxl.styles import Alignment, Font, PatternFill

    for celula in planilha[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="1F4E78")
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for coluna in planilha.columns:
        largura = max(len(str(c.value)) if c.value is not None else 0 for c in coluna)
        planilha.column_dimensions[coluna[0].column_letter].width = max(13, largura + 3)
    planilha.freeze_panes = "A2"


def gravar_xlsx(df: pd.DataFrame, df_cache: pd.DataFrame | None, destino: str):
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Consolidado_12_Cenarios")
        formatar_aba(writer.sheets["Consolidado_12_Cenarios"])
        if df_cache is not None:
            df_cache.to_excel(writer, index=False, sheet_name="Cache_Redis")
            formatar_aba(writer.sheets["Cache_Redis"])


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resultados", type=Path, default=RAIZ / "resultados")
    p.add_argument("--teto", type=float, default=10.0, help="teto máximo de perda (%%)")
    args = p.parse_args()

    df = montar_tabela(args.resultados, args.teto)
    df_cache = carregar_cache_df(args.resultados)
    base = args.resultados / "tabela_consolidada_trabalho4"

    df.to_csv(str(base) + ".csv", index=False, encoding="utf-8-sig")
    gravar_xlsx(df, df_cache, str(base) + ".xlsx")
    Path(str(base) + ".md").write_text(para_markdown(df, df_cache, args.teto), encoding="utf-8")

    print(df.to_string(index=False))
    print(f"\nPlanilha consolidada salva em:\n  - {base}.csv\n  - {base}.xlsx\n  - {base}.md\nTotal: {len(df)} cenários.")
    if len(df) != 12:
        print(f"AVISO: esperado = 12 cenários, encontrado = {len(df)}.")
    acima = df[df["Perda <= 10%"] == "NÃO"]
    if not acima.empty:
        print(f"AVISO: {len(acima)} cenário(s) ultrapassaram o teto de {args.teto}%:")
        print(acima[["Linguagem", "Modo de Cache", "Nível", "Usuários Virtuais", "% de Perda"]].to_string(index=False))


if __name__ == "__main__":
    main()
