#!/usr/bin/env python3
"""Geração de gráficos em alta resolução para o Google Slides - Trabalho 4 (Link Extractor).

Lê `resultados/tabela_consolidada_trabalho4.csv` e gera na pasta `graficos/` (formato 16:9, 220 DPI):
  1. 01_tempo_resposta_media_mediana.png     -> Média e Mediana: Python vs Ruby (Sem vs Com Cache)
  2. 02_percentis_painel_comparativo.png     -> Painel consolidado p50/p90/p95/p99 nos 3 níveis U1, U2, U3
     02_percentis_U1.png / U2.png / U3.png   -> Percentis detalhados por nível de carga
  3. 03_vazao_rps.png                        -> Vazão (Requests/s) com destaque do ganho com Redis
  4. 04_taxa_perda.png                       -> Taxa de Perda (%) comprovando o limite <= 10%
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RAIZ = Path(__file__).resolve().parent
TAMANHO_SLIDE = (13.333, 7.5)  # Proporção widescreen 16:9 nativa do Google Slides
DPI = 220

# Paleta de alto contraste: Python em tons de azul, Ruby em tons de vermelho/coral;
# barras "Com Cache" em tom forte com hachura sutil, "Sem Cache" em tom sólido claro.
SERIES = [
    ("Python", "Sem Cache", "#6baed6", ""),
    ("Python", "Com Cache", "#08519c", "//"),
    ("Ruby", "Sem Cache", "#fc9272", ""),
    ("Ruby", "Com Cache", "#a50f15", "//"),
]

plt.rcParams.update({
    "font.size": 12.5,
    "axes.titlesize": 15.5,
    "axes.titleweight": "bold",
    "axes.labelsize": 13,
    "legend.fontsize": 12.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.28,
    "axes.axisbelow": True,
})


def rotulo_nivel(df: pd.DataFrame) -> dict[str, str]:
    usuarios = df.groupby("Nível")["Usuários Virtuais"].first()
    return {n: f"{n}\n({int(u)} usuários)" for n, u in usuarios.items()}


def valor(df: pd.DataFrame, lang: str, cache: str, filtro_col: str, filtro_val: str, coluna: str) -> float:
    s = df[(df["Linguagem"] == lang) & (df["Modo de Cache"] == cache) & (df[filtro_col] == filtro_val)][coluna]
    return float(s.iloc[0]) if len(s) else np.nan


def formatar(v: float) -> str:
    if np.isnan(v):
        return ""
    if v >= 100:
        return f"{v:,.0f}".replace(",", ".")
    if v >= 10:
        return f"{v:.1f}".replace(".", ",")
    return f"{v:.2f}".replace(".", ",")


def barras_agrupadas(
    ax,
    grupos: list[str],
    rotulos: list[str],
    df: pd.DataFrame,
    filtro_col: str,
    coluna: str,
    log: bool = False,
    rotulos_valores: bool = True,
    sufixo: str = "",
    fonte_valor: float = 9.0,
):
    largura = 0.20
    x = np.arange(len(grupos))
    todos_positivos = []
    for i, (lang, cache, cor, hachura) in enumerate(SERIES):
        valores = [valor(df, lang, cache, filtro_col, g, coluna) for g in grupos]
        todos_positivos.extend([v for v in valores if not np.isnan(v) and v > 0])
        # Em escala logarítmica, evita barra de altura <= 0
        valores_plot = [max(v, 0.5) if (log and not np.isnan(v)) else v for v in valores]
        posicoes = x + (i - 1.5) * largura
        barras = ax.bar(
            posicoes,
            valores_plot,
            largura * 0.94,
            label=f"{lang} – {cache}",
            color=cor,
            hatch=hachura,
            edgecolor="white",
            linewidth=0.8,
        )
        if rotulos_valores:
            for barra, v_real in zip(barras, valores):
                if not np.isnan(v_real):
                    ax.annotate(
                        formatar(v_real) + sufixo,
                        (barra.get_x() + barra.get_width() / 2.0, barra.get_height()),
                        ha="center",
                        va="bottom",
                        fontsize=fonte_valor,
                        fontweight="bold",
                        xytext=(0, 3),
                        textcoords="offset points",
                    )
    ax.set_xticks(x)
    ax.set_xticklabels(rotulos)
    if log and todos_positivos:
        ax.set_yscale("log")
        ymin = max(0.4, min(todos_positivos) * 0.55)
        ymax = max(todos_positivos) * 2.6
        ax.set_ylim(ymin, ymax)
    else:
        topo = ax.get_ylim()[1]
        ax.set_ylim(0, topo * 1.16 if topo > 0 else 1.0)


def salvar(fig, caminho: Path):
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [OK] {caminho}")


def legenda_inferior(fig, ax):
    handles, nomes = ax.get_legend_handles_labels()
    fig.legend(handles, nomes, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.01))


def grafico_tempo_resposta(df: pd.DataFrame, saida: Path, log: bool):
    niveis = sorted(df["Nível"].unique())
    rotulos = [rotulo_nivel(df)[n] for n in niveis]
    fig, eixos = plt.subplots(1, 2, figsize=TAMANHO_SLIDE, sharey=True)
    pares = [
        ("Média (ms)", "Média do Tempo de Resposta"),
        ("Mediana (ms)", "Mediana (p50) do Tempo de Resposta"),
    ]
    for ax, (coluna, titulo) in zip(eixos, pares):
        barras_agrupadas(ax, niveis, rotulos, df, "Nível", coluna, log=log)
        ax.set_title(titulo)
        ax.set_xlabel("Nível de Carga Calibrado")
    eixos[0].set_ylabel("Tempo de Resposta (ms)" + (" [escala log]" if log else ""))
    fig.suptitle(
        "Link Extractor: Tempo de Resposta (Média e Mediana) — Python vs. Ruby (Sem e Com Redis)",
        fontsize=17,
        fontweight="bold",
        y=1.01,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    legenda_inferior(fig, eixos[0])
    salvar(fig, saida / "01_tempo_resposta_media_mediana.png")


def grafico_percentis(df: pd.DataFrame, saida: Path, log: bool):
    percentis = [
        ("Mediana (ms)", "p50\n(Mediana)"),
        ("P90 (ms)", "p90"),
        ("P95 (ms)", "p95"),
        ("P99 (ms)", "p99"),
    ]
    colunas = [c for c, _ in percentis]
    rotulos_p = [r for _, r in percentis]
    niveis = sorted(df["Nível"].unique())

    # 1) Um gráfico individual detalhado por nível (U1, U2, U3)
    for nivel in niveis:
        sub = df[df["Nível"] == nivel]
        usuarios = int(sub["Usuários Virtuais"].iloc[0])
        fig, ax = plt.subplots(figsize=TAMANHO_SLIDE)
        largura = 0.20
        x = np.arange(len(colunas))
        positivos = []
        for i, (lang, cache, cor, hachura) in enumerate(SERIES):
            linha = sub[(sub["Linguagem"] == lang) & (sub["Modo de Cache"] == cache)]
            valores = [float(linha[c].iloc[0]) if len(linha) else np.nan for c in colunas]
            positivos.extend([v for v in valores if not np.isnan(v) and v > 0])
            valores_plot = [max(v, 0.5) if (log and not np.isnan(v)) else v for v in valores]
            barras = ax.bar(
                x + (i - 1.5) * largura,
                valores_plot,
                largura * 0.94,
                label=f"{lang} – {cache}",
                color=cor,
                hatch=hachura,
                edgecolor="white",
                linewidth=0.8,
            )
            for barra, v_real in zip(barras, valores):
                if not np.isnan(v_real):
                    ax.annotate(
                        formatar(v_real),
                        (barra.get_x() + barra.get_width() / 2.0, barra.get_height()),
                        ha="center",
                        va="bottom",
                        fontsize=9.2,
                        fontweight="bold",
                        xytext=(0, 3),
                        textcoords="offset points",
                    )
        ax.set_xticks(x)
        ax.set_xticklabels(rotulos_p)
        if log and positivos:
            ax.set_yscale("log")
            ax.set_ylim(max(0.4, min(positivos) * 0.55), max(positivos) * 2.5)
        else:
            ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
        ax.set_ylabel("Tempo de Resposta (ms)" + (" [escala log]" if log else ""))
        ax.set_title(f"Cauda de Latência (p50, p90, p95, p99) — Nível {nivel} ({usuarios} usuários virtuais)")
        fig.tight_layout(rect=(0, 0.05, 1, 1))
        legenda_inferior(fig, ax)
        salvar(fig, saida / f"02_percentis_{nivel}.png")

    # 2) Painel consolidado 1x3 (U1 | U2 | U3) ideal para 1 slide panorâmico
    fig, eixos = plt.subplots(1, len(niveis), figsize=(15.5, 7.5), sharey=True)
    if len(niveis) == 1:
        eixos = [eixos]
    todos_pos = []
    for ax, nivel in zip(eixos, niveis):
        sub = df[df["Nível"] == nivel]
        usuarios = int(sub["Usuários Virtuais"].iloc[0])
        largura = 0.20
        x = np.arange(len(colunas))
        for i, (lang, cache, cor, hachura) in enumerate(SERIES):
            linha = sub[(sub["Linguagem"] == lang) & (sub["Modo de Cache"] == cache)]
            valores = [float(linha[c].iloc[0]) if len(linha) else np.nan for c in colunas]
            todos_pos.extend([v for v in valores if not np.isnan(v) and v > 0])
            valores_plot = [max(v, 0.5) if (log and not np.isnan(v)) else v for v in valores]
            barras = ax.bar(
                x + (i - 1.5) * largura,
                valores_plot,
                largura * 0.94,
                label=f"{lang} – {cache}",
                color=cor,
                hatch=hachura,
                edgecolor="white",
                linewidth=0.7,
            )
            for barra, v_real in zip(barras, valores):
                if not np.isnan(v_real):
                    ax.annotate(
                        formatar(v_real),
                        (barra.get_x() + barra.get_width() / 2.0, barra.get_height()),
                        ha="center",
                        va="bottom",
                        fontsize=7.8,
                        rotation=90 if len(niveis) >= 3 else 0,
                        xytext=(0, 3),
                        textcoords="offset points",
                    )
        ax.set_xticks(x)
        ax.set_xticklabels(["p50", "p90", "p95", "p99"])
        ax.set_title(f"{nivel} ({usuarios} usuários)")
    if log and todos_pos:
        eixos[0].set_yscale("log")
        eixos[0].set_ylim(max(0.4, min(todos_pos) * 0.5), max(todos_pos) * 4.2)
    eixos[0].set_ylabel("Tempo de Resposta (ms)" + (" [escala log]" if log else ""))
    fig.suptitle(
        "Comparativo de Percentis de Latência (p50, p90, p95, p99) — Python vs. Ruby (Sem e Com Cache)",
        fontsize=17,
        fontweight="bold",
        y=1.01,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    legenda_inferior(fig, eixos[0])
    salvar(fig, saida / "02_percentis_painel_comparativo.png")


def grafico_vazao(df: pd.DataFrame, saida: Path):
    niveis = sorted(df["Nível"].unique())
    rotulos = [rotulo_nivel(df)[n] for n in niveis]
    fig, ax = plt.subplots(figsize=TAMANHO_SLIDE)
    barras_agrupadas(ax, niveis, rotulos, df, "Nível", "Vazão (req/s)", log=False, fonte_valor=9.5)

    # Anota ganho multiplicativo (Com Cache / Sem Cache) no topo de cada grupo
    for idx, nivel in enumerate(niveis):
        ganhos = []
        for lang in ("Python", "Ruby"):
            sem = valor(df, lang, "Sem Cache", "Nível", nivel, "Vazão (req/s)")
            com = valor(df, lang, "Com Cache", "Nível", nivel, "Vazão (req/s)")
            if sem and sem > 0 and not np.isnan(com):
                ganhos.append(f"{lang}: {com / sem:.1f}x")
        if ganhos:
            topo_grupo = max(
                valor(df, l, c, "Nível", nivel, "Vazão (req/s)")
                for l, c, _, _ in SERIES
            )
            ax.annotate(
                "Ganho Redis → " + " | ".join(ganhos),
                (idx, topo_grupo),
                ha="center",
                va="bottom",
                fontsize=9.5,
                color="#1b4f72",
                fontweight="bold",
                xytext=(0, 18),
                textcoords="offset points",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": "#ebf5fb", "edgecolor": "#aed6f1"},
            )

    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    ax.set_xlabel("Nível de Carga Calibrado")
    ax.set_ylabel("Vazão — Requisições por Segundo (RPS)")
    ax.set_title("Link Extractor: Vazão (Requests/s) — Ganho de Throughput com Redis Cache")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    legenda_inferior(fig, ax)
    salvar(fig, saida / "03_vazao_rps.png")


def grafico_perda(df: pd.DataFrame, saida: Path, teto: float = 10.0):
    niveis = sorted(df["Nível"].unique())
    rotulos = [rotulo_nivel(df)[n] for n in niveis]
    fig, ax = plt.subplots(figsize=TAMANHO_SLIDE)
    barras_agrupadas(ax, niveis, rotulos, df, "Nível", "% de Perda", log=False, sufixo="%", fonte_valor=9.5)
    ax.axhline(teto, color="#c0392b", linestyle="--", linewidth=2.2)
    ax.annotate(
        f"Limite Máximo Exigido pelo Professor: {teto:.0f}% de Perda",
        (ax.get_xlim()[0] + 0.05, teto),
        xytext=(4, 6),
        textcoords="offset points",
        color="#c0392b",
        fontsize=11.5,
        fontweight="bold",
    )
    ax.set_ylim(0, max(teto * 1.25, ax.get_ylim()[1]))
    ax.set_xlabel("Nível de Carga Calibrado")
    ax.set_ylabel("Taxa de Perda / Falhas (%)")
    ax.set_title("Link Extractor: Taxa de Perda (%) — Calibragem Empírica Respeitando o Teto de 10%")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    legenda_inferior(fig, ax)
    salvar(fig, saida / "04_taxa_perda.png")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resultados", type=Path, default=RAIZ / "resultados")
    p.add_argument("--saida", type=Path, default=RAIZ / "graficos")
    p.add_argument("--escala-linear", action="store_true", help="usa escala linear nos gráficos de latência")
    args = p.parse_args()

    tabela = args.resultados / "tabela_consolidada_trabalho4.csv"
    if not tabela.exists():
        sys.exit(f"ERRO: planilha {tabela} não encontrada. Execute consolidar_metricas.py antes.")
    df = pd.read_csv(tabela)
    args.saida.mkdir(parents=True, exist_ok=True)

    log = not args.escala_linear
    print(f"Gerando gráficos de apresentação em {args.saida}...")
    grafico_tempo_resposta(df, args.saida, log)
    grafico_percentis(df, args.saida, log)
    grafico_vazao(df, args.saida)
    grafico_perda(df, args.saida)


if __name__ == "__main__":
    main()
