"""Configuracao de log: console legivel e arquivo rotativo."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configura_log(pasta_logs: str | Path = "logs", verboso: bool = False) -> Path:
    """Prepara o log e devolve o caminho do arquivo."""
    pasta = Path(pasta_logs)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "bot_imea.log"

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG if verboso else logging.INFO)
    raiz.handlers.clear()

    # Arquivo: guarda ate 5 arquivos de 1 MB.
    em_arquivo = RotatingFileHandler(
        arquivo, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    em_arquivo.setLevel(logging.DEBUG)
    em_arquivo.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    raiz.addHandler(em_arquivo)

    # Console
    no_console = logging.StreamHandler(sys.stdout)
    no_console.setLevel(logging.DEBUG if verboso else logging.INFO)
    no_console.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
    raiz.addHandler(no_console)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return arquivo
