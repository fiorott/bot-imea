"""Orquestra a execucao diaria.

Regra central pedida no projeto: comparar a data de atualizacao de cada box
com a data ja registrada no banco. Se for a mesma, nada e gravado. Se for
mais nova, o dado entra e a planilha e regerada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .banco import BancoIMEA
from .coletor import BoxColetado, ColetorIMEA, ErroColeta
from .config import Cadeia, Config
from .excel import GeradorExcel

logger = logging.getLogger(__name__)


@dataclass
class ResultadoCadeia:
    """Resumo do que aconteceu com uma cadeia."""

    cadeia: str
    boxes_totais: int = 0
    boxes_atualizados: int = 0
    boxes_inalterados: int = 0
    boxes_novos: int = 0
    boxes_vazios: int = 0
    linhas_inseridas: int = 0
    excel: str | None = None
    erro: str | None = None
    detalhes: list[str] = field(default_factory=list)

    @property
    def houve_novidade(self) -> bool:
        return self.linhas_inseridas > 0


class RoboIMEA:
    """Executa a coleta, decide o que gravar e atualiza a planilha."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.banco = BancoIMEA(config.caminho_banco)
        self.coletor = ColetorIMEA(
            timeout=config.timeout,
            tentativas=config.tentativas,
            espera=config.espera,
            user_agent=config.user_agent or None,
        )

    def executa(self, cadeia: Cadeia, forcar: bool = False) -> ResultadoCadeia:
        inicio = datetime.now()
        resultado = ResultadoCadeia(cadeia=cadeia.nome)

        logger.info("=" * 70)
        logger.info("Cadeia %s | %s", cadeia.rotulo.upper(), cadeia.url)
        logger.info("=" * 70)

        try:
            boxes = self.coletor.coleta_cadeia(cadeia.url)
        except ErroColeta as erro:
            resultado.erro = str(erro)
            logger.error("Coleta interrompida: %s", erro)
            self._registra(cadeia.nome, resultado, inicio, "erro")
            return resultado

        resultado.boxes_totais = len(boxes)
        registros: list[dict] = []
        coletado_em = datetime.now().isoformat(timespec="seconds")

        for box in boxes:
            self._avalia_box(cadeia, box, resultado, registros, coletado_em, forcar)

        if registros:
            resultado.linhas_inseridas = self.banco.grava_cotacoes(registros)
            logger.info("Linhas novas gravadas no banco: %d", resultado.linhas_inseridas)
        else:
            logger.info("Nenhum dado novo para gravar.")

        # A planilha e sempre reconstruida a partir do banco: garante que o
        # arquivo exista mesmo quando nada mudou e evita linhas duplicadas.
        caminho_excel = self.config.caminho_excel(cadeia.nome)
        gerador = GeradorExcel(caminho_excel)
        abas = gerador.gera(self.banco, cadeia.nome)
        if abas:
            resultado.excel = str(caminho_excel)

        self._registra(cadeia.nome, resultado, inicio, "ok")
        self._loga_resumo(resultado)
        return resultado

    # -- decisao por box ---------------------------------------------------

    def _avalia_box(
        self,
        cadeia: Cadeia,
        box: BoxColetado,
        resultado: ResultadoCadeia,
        registros: list[dict],
        coletado_em: str,
        forcar: bool,
    ) -> None:
        indicador = box.indicador
        safra = indicador.safra or ""
        titulo = indicador.titulo

        if not self.banco.indicador_conhecido(cadeia.nome, indicador.indicador_final_id, safra):
            resultado.boxes_novos += 1
            logger.info("Box novo detectado: %s", titulo)

        if box.vazio:
            resultado.boxes_vazios += 1
            logger.warning("Box sem dados no site: %s", titulo)
            self.banco.atualiza_controle(
                cadeia.nome, indicador.indicador_final_id, safra, indicador.nome, None
            )
            return

        data_site = box.data_referencia
        data_banco = self.banco.ultima_data(cadeia.nome, indicador.indicador_final_id, safra)

        if data_banco and data_site and data_site <= data_banco and not forcar:
            resultado.boxes_inalterados += 1
            logger.info(
                "Sem novidade: %-40s data %s ja registrada",
                titulo[:40],
                data_site.strftime("%d/%m/%Y"),
            )
            self.banco.atualiza_controle(
                cadeia.nome, indicador.indicador_final_id, safra, indicador.nome, data_banco
            )
            return

        resultado.boxes_atualizados += 1
        logger.info(
            "Atualizado:  %-40s %s -> %s (%d linhas)",
            titulo[:40],
            data_banco.strftime("%d/%m/%Y") if data_banco else "sem historico",
            data_site.strftime("%d/%m/%Y") if data_site else "sem data",
            len(box.cotacoes),
        )

        for cotacao in box.cotacoes:
            if not cotacao.data_referencia:
                continue
            registros.append(
                {
                    "cadeia": cadeia.nome,
                    "indicador_id": indicador.indicador_final_id,
                    "indicador_nome": indicador.nome,
                    "safra": safra,
                    "localidade": cotacao.localidade,
                    "data_referencia": cotacao.data_referencia.isoformat(),
                    "valor": cotacao.valor,
                    "variacao": cotacao.variacao,
                    "unidade": indicador.unidade,
                    "fonte": indicador.fonte,
                    "nota": indicador.nota,
                    "ordem_box": indicador.ordem,
                    "coletado_em": coletado_em,
                }
            )

        self.banco.atualiza_controle(
            cadeia.nome, indicador.indicador_final_id, safra, indicador.nome, data_site
        )

    # -- apoio -------------------------------------------------------------

    def _registra(
        self, cadeia: str, resultado: ResultadoCadeia, inicio: datetime, status: str
    ) -> None:
        self.banco.registra_execucao(
            cadeia,
            {
                "iniciado_em": inicio.isoformat(timespec="seconds"),
                "boxes_novos": resultado.boxes_novos,
                "boxes_atualizados": resultado.boxes_atualizados,
                "boxes_inalterados": resultado.boxes_inalterados,
                "linhas_inseridas": resultado.linhas_inseridas,
                "status": status,
                "detalhe": resultado.erro,
            },
        )

    @staticmethod
    def _loga_resumo(resultado: ResultadoCadeia) -> None:
        logger.info("-" * 70)
        logger.info("RESUMO da cadeia %s", resultado.cadeia.upper())
        logger.info("  Boxes encontrados no site : %d", resultado.boxes_totais)
        logger.info("  Boxes com data nova       : %d", resultado.boxes_atualizados)
        logger.info("  Boxes sem alteracao       : %d", resultado.boxes_inalterados)
        logger.info("  Boxes vistos pela 1a vez  : %d", resultado.boxes_novos)
        if resultado.boxes_vazios:
            logger.info("  Boxes sem dados no site   : %d", resultado.boxes_vazios)
        logger.info("  Linhas gravadas no banco  : %d", resultado.linhas_inseridas)
        logger.info("  Planilha                  : %s", resultado.excel or "nao gerada")
        logger.info("-" * 70)
