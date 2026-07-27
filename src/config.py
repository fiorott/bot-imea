"""Leitura do arquivo de configuracao."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Cadeia:
    nome: str
    rotulo: str
    url: str
    ativo: bool = False


@dataclass
class Config:
    pasta_saida: Path
    arquivo_banco: str
    prefixo_excel: str
    timeout: int
    tentativas: int
    espera: int
    user_agent: str
    cadeias: list[Cadeia] = field(default_factory=list)

    @property
    def caminho_banco(self) -> Path:
        return self.pasta_saida / self.arquivo_banco

    def caminho_excel(self, cadeia: str) -> Path:
        return self.pasta_saida / f"{self.prefixo_excel}_{cadeia}.xlsx"

    def cadeias_ativas(self) -> list[Cadeia]:
        return [c for c in self.cadeias if c.ativo]

    def busca_cadeia(self, nome: str) -> Cadeia | None:
        alvo = nome.strip().lower()
        for cadeia in self.cadeias:
            if cadeia.nome.lower() == alvo:
                return cadeia
        return None


def carrega_config(caminho: str | Path) -> Config:
    caminho = Path(caminho)
    with open(caminho, encoding="utf-8") as fh:
        bruto = yaml.safe_load(fh) or {}

    saida = bruto.get("saida", {})
    coleta = bruto.get("coleta", {})

    pasta = Path(saida.get("pasta", "dados"))
    if not pasta.is_absolute():
        # Caminho relativo e resolvido a partir da pasta do projeto.
        pasta = (caminho.parent / pasta).resolve()

    cadeias = [
        Cadeia(
            nome=str(item["nome"]),
            rotulo=str(item.get("rotulo", item["nome"]).title()),
            url=str(item["url"]),
            ativo=bool(item.get("ativo", False)),
        )
        for item in bruto.get("cadeias", [])
    ]

    return Config(
        pasta_saida=pasta,
        arquivo_banco=str(saida.get("banco", "imea.sqlite")),
        prefixo_excel=str(saida.get("prefixo_excel", "imea")),
        timeout=int(coleta.get("timeout_segundos", 60)),
        tentativas=int(coleta.get("tentativas", 3)),
        espera=int(coleta.get("espera_entre_tentativas", 5)),
        user_agent=str(coleta.get("user_agent", "")).strip(),
        cadeias=cadeias,
    )
