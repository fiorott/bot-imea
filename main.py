"""Bot IMEA - coleta diaria dos indicadores e geracao da base para Power BI.

Uso tipico:
    python main.py                 # coleta as cadeias ativas no config.yaml
    python main.py --cadeia boi    # coleta apenas o boi
    python main.py --listar        # mostra os boxes do site sem gravar nada
    python main.py --forcar        # regrava mesmo sem mudanca de data
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from src.coletor import ColetorIMEA, ErroColeta  # noqa: E402
from src.config import carrega_config  # noqa: E402
from src.log import configura_log  # noqa: E402
from src.robo import RoboIMEA  # noqa: E402

logger = logging.getLogger("bot_imea")


def monta_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coleta os indicadores do IMEA e gera a base para o Power BI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cadeia",
        help="Coleta apenas a cadeia informada (boi, soja, milho, algodao, suino, leite).",
    )
    parser.add_argument(
        "--config",
        default=str(RAIZ / "config.yaml"),
        help="Caminho do arquivo de configuracao.",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Grava os dados mesmo que a data ja esteja registrada.",
    )
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Apenas lista os boxes encontrados no site, sem gravar nada.",
    )
    parser.add_argument("--verboso", action="store_true", help="Log detalhado.")
    return parser


def lista_boxes(config, cadeias) -> int:
    coletor = ColetorIMEA(
        timeout=config.timeout,
        tentativas=config.tentativas,
        espera=config.espera,
        user_agent=config.user_agent or None,
    )
    for cadeia in cadeias:
        print(f"\n=== {cadeia.rotulo.upper()} | {cadeia.url} ===")
        try:
            boxes = coletor.coleta_cadeia(cadeia.url)
        except ErroColeta as erro:
            print(f"  ERRO: {erro}")
            continue
        for box in boxes:
            data = box.data_referencia
            print(
                f"  {box.indicador.ordem:2d}. {box.indicador.titulo:<42} "
                f"| {len(box.cotacoes):3d} linhas "
                f"| {box.indicador.unidade:<10} "
                f"| {data.strftime('%d/%m/%Y') if data else 'sem data'}"
            )
        print(f"  TOTAL: {len(boxes)} boxes")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = monta_argumentos().parse_args(argv)

    arquivo_log = configura_log(RAIZ / "logs", verboso=args.verboso)
    config = carrega_config(args.config)

    if args.cadeia:
        cadeia = config.busca_cadeia(args.cadeia)
        if not cadeia:
            disponiveis = ", ".join(c.nome for c in config.cadeias)
            logger.error("Cadeia %r nao existe. Disponiveis: %s", args.cadeia, disponiveis)
            return 2
        cadeias = [cadeia]
    else:
        cadeias = config.cadeias_ativas()

    if not cadeias:
        logger.error("Nenhuma cadeia ativa no config.yaml. Marque 'ativo: true'.")
        return 2

    if args.listar:
        return lista_boxes(config, cadeias)

    logger.info("Bot IMEA iniciado | log em %s", arquivo_log)
    logger.info("Pasta de saida: %s", config.pasta_saida)

    robo = RoboIMEA(config)
    houve_erro = False
    resultados = []

    for cadeia in cadeias:
        resultado = robo.executa(cadeia, forcar=args.forcar)
        resultados.append(resultado)
        houve_erro = houve_erro or bool(resultado.erro)

    logger.info("=" * 70)
    logger.info("EXECUCAO CONCLUIDA")
    for resultado in resultados:
        if resultado.erro:
            logger.info("  %-10s ERRO: %s", resultado.cadeia, resultado.erro)
        else:
            logger.info(
                "  %-10s %d boxes | %d atualizados | %d linhas novas",
                resultado.cadeia,
                resultado.boxes_totais,
                resultado.boxes_atualizados,
                resultado.linhas_inseridas,
            )
    logger.info("=" * 70)

    return 1 if houve_erro else 0


if __name__ == "__main__":
    raise SystemExit(main())
