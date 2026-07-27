"""Coleta os indicadores do IMEA reproduzindo a logica da pagina.

Fluxo:
1. Baixa o HTML da pagina da cadeia (ex.: indicador-boi).
2. Le a definicao dos boxes (dinamica, sem lista fixa no codigo).
3. Chama a API publica de cotacoes.
4. Cruza cada cotacao com o seu box por ``IndicadorFinalId`` + ``Safra``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import requests

from .parser_pagina import Indicador, extrai_definicao

logger = logging.getLogger(__name__)


class ErroColeta(RuntimeError):
    """Falha ao obter dados do IMEA."""


@dataclass
class Cotacao:
    """Uma linha de um box."""

    localidade: str
    valor: float | None
    variacao: float | None
    data_referencia: date | None


@dataclass
class BoxColetado:
    """Um box da pagina com todas as suas linhas."""

    indicador: Indicador
    cotacoes: list[Cotacao]

    @property
    def data_referencia(self) -> date | None:
        """Data de atualizacao exibida no rodape do box.

        A pagina usa a data da primeira cotacao; aqui adotamos a mais recente
        entre as linhas, o que e equivalente e mais robusto.
        """
        datas = [c.data_referencia for c in self.cotacoes if c.data_referencia]
        return max(datas) if datas else None

    @property
    def vazio(self) -> bool:
        return not self.cotacoes


def _converte_data(valor: Any) -> date | None:
    """Converte a data da API para ``date``. Aceita ISO e dd/mm/aaaa."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    if not texto:
        return None

    # Formato mais comum: "2026-07-27 00:00:00" / "2026-07-27T00:00:00"
    texto_iso = texto.replace("T", " ").split(".")[0]
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(texto_iso, formato).date()
        except ValueError:
            continue

    logger.warning("Data em formato desconhecido, ignorada: %r", valor)
    return None


def _converte_numero(valor: Any) -> float | None:
    """Converte o valor da API para float, aceitando tambem texto pt-BR."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip().replace("%", "").replace("R$", "").strip()
    if not texto or texto == "-":
        return None

    # Formato pt-BR: 4.465,93 -> 4465.93
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        logger.warning("Valor numerico invalido, ignorado: %r", valor)
        return None


class ColetorIMEA:
    """Cliente HTTP com repeticao automatica em caso de falha."""

    def __init__(
        self,
        timeout: int = 60,
        tentativas: int = 3,
        espera: int = 5,
        user_agent: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.tentativas = max(1, tentativas)
        self.espera = espera
        self.sessao = requests.Session()
        self.sessao.headers.update(
            {
                "User-Agent": user_agent
                or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }
        )

    # -- infraestrutura ----------------------------------------------------

    def _requisita(self, url: str, **kwargs: Any) -> requests.Response:
        ultimo_erro: Exception | None = None
        for tentativa in range(1, self.tentativas + 1):
            try:
                resposta = self.sessao.get(url, timeout=self.timeout, **kwargs)
                resposta.raise_for_status()
                return resposta
            except requests.RequestException as erro:
                ultimo_erro = erro
                logger.warning(
                    "Tentativa %d/%d falhou para %s: %s",
                    tentativa,
                    self.tentativas,
                    url,
                    erro,
                )
                if tentativa < self.tentativas:
                    time.sleep(self.espera)
        raise ErroColeta(f"Nao consegui acessar {url}: {ultimo_erro}") from ultimo_erro

    # -- coleta ------------------------------------------------------------

    def coleta_cadeia(self, url_pagina: str) -> list[BoxColetado]:
        """Devolve todos os boxes da pagina, com suas linhas preenchidas."""
        logger.info("Lendo a pagina %s", url_pagina)
        html = self._requisita(url_pagina).text
        definicao = extrai_definicao(html)
        logger.info(
            "Pagina interpretada: %d boxes declarados | endpoint %s",
            len(definicao.indicadores),
            definicao.api.url_completa,
        )

        cotacoes_api = self._busca_cotacoes(definicao.api.url_completa, url_pagina)
        cotacoes_legado = self._busca_legado(definicao, url_pagina)

        boxes: list[BoxColetado] = []
        for indicador in definicao.indicadores:
            if indicador.usa_antigo:
                linhas = self._filtra_legado(indicador, cotacoes_legado)
            else:
                linhas = self._filtra_atual(indicador, cotacoes_api)
            boxes.append(BoxColetado(indicador=indicador, cotacoes=linhas))

        return boxes

    def _busca_cotacoes(self, url_api: str, referer: str) -> list[dict[str, Any]]:
        logger.info("Consultando a API de cotacoes")
        resposta = self._requisita(
            url_api,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.imea.com.br",
                "Referer": referer,
            },
        )
        dados = resposta.json()
        if isinstance(dados, dict):
            dados = dados.get("Result") or dados.get("result") or dados.get("data") or []
        if not isinstance(dados, list):
            raise ErroColeta("A API retornou um formato inesperado de cotacoes.")
        logger.info("API devolveu %d cotacoes", len(dados))
        return dados

    def _busca_legado(self, definicao: Any, referer: str) -> list[dict[str, Any]]:
        """Endpoint antigo, usado por poucos indicadores de algumas cadeias."""
        precisa = any(ind.usa_antigo for ind in definicao.indicadores)
        if not precisa or not definicao.api_antiga:
            return []

        url = definicao.api_antiga
        if not url.startswith("http"):
            url = f"https://www.imea.com.br/imea-site/{url.lstrip('/')}"

        try:
            resposta = self._requisita(url, headers={"Referer": referer})
            corpo = resposta.json()
        except (ErroColeta, ValueError) as erro:
            logger.warning("Endpoint legado indisponivel (%s): %s", url, erro)
            return []

        if isinstance(corpo, dict) and corpo.get("data"):
            return list(corpo["data"])
        return list(corpo) if isinstance(corpo, list) else []

    # -- cruzamento --------------------------------------------------------

    @staticmethod
    def _filtra_atual(indicador: Indicador, cotacoes: list[dict[str, Any]]) -> list[Cotacao]:
        """Mesma regra do JavaScript: casa IndicadorFinalId e Safra."""
        selecionadas = [
            item
            for item in cotacoes
            if str(item.get("IndicadorFinalId") or "") == indicador.indicador_final_id
            and (item.get("Safra") or None) == (indicador.safra or None)
        ]
        return [
            Cotacao(
                localidade=str(item.get("Localidade") or "").strip(),
                valor=_converte_numero(item.get("Valor")),
                variacao=_converte_numero(item.get("Variacao")),
                data_referencia=_converte_data(item.get("DataPublicacao")),
            )
            for item in selecionadas
        ]

    @staticmethod
    def _filtra_legado(indicador: Indicador, cotacoes: list[dict[str, Any]]) -> list[Cotacao]:
        selecionadas = [
            item
            for item in cotacoes
            if str(item.get("id_subproduto") or "") == (indicador.id_antigo or "")
            and (
                not indicador.id_safra_antigo
                or str(item.get("id_safra") or "") == indicador.id_safra_antigo
            )
        ]
        selecionadas.sort(key=lambda item: item.get("ordenacao") or 0)
        return [
            Cotacao(
                localidade=str(item.get("descricao") or "").strip(),
                valor=_converte_numero(item.get("valor")),
                variacao=_converte_numero(item.get("variacao")),
                data_referencia=_converte_data(item.get("data_cotacao")),
            )
            for item in selecionadas
        ]
