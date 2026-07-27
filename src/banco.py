"""Persistencia em SQLite.

O banco e a fonte da verdade do historico. O Excel e sempre reconstruido a
partir dele, o que evita duplicidade caso o bot rode varias vezes no mesmo dia.

Regra de idempotencia: a chave unica
``(cadeia, indicador_id, safra, localidade, data_referencia)``
garante que o mesmo dado nunca entre duas vezes.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cotacoes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cadeia            TEXT    NOT NULL,
    indicador_id      TEXT    NOT NULL,
    indicador_nome    TEXT    NOT NULL,
    safra             TEXT    NOT NULL DEFAULT '',
    localidade        TEXT    NOT NULL,
    data_referencia   TEXT    NOT NULL,
    valor             REAL,
    variacao          REAL,
    unidade           TEXT,
    fonte             TEXT,
    nota              TEXT,
    ordem_box         INTEGER NOT NULL DEFAULT 0,
    coletado_em       TEXT    NOT NULL,
    UNIQUE (cadeia, indicador_id, safra, localidade, data_referencia)
);

CREATE INDEX IF NOT EXISTS ix_cotacoes_box
    ON cotacoes (cadeia, indicador_id, safra, data_referencia);

CREATE TABLE IF NOT EXISTS controle_indicador (
    cadeia            TEXT NOT NULL,
    indicador_id      TEXT NOT NULL,
    safra             TEXT NOT NULL DEFAULT '',
    indicador_nome    TEXT NOT NULL,
    ultima_data       TEXT,
    ultima_verificacao TEXT NOT NULL,
    PRIMARY KEY (cadeia, indicador_id, safra)
);

CREATE TABLE IF NOT EXISTS execucoes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciado_em     TEXT NOT NULL,
    finalizado_em   TEXT,
    cadeia          TEXT,
    boxes_novos     INTEGER DEFAULT 0,
    boxes_atualizados INTEGER DEFAULT 0,
    boxes_inalterados INTEGER DEFAULT 0,
    linhas_inseridas  INTEGER DEFAULT 0,
    status          TEXT,
    detalhe         TEXT
);
"""


class BancoIMEA:
    """Acesso ao banco local."""

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._prepara()

    @contextmanager
    def conexao(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _prepara(self) -> None:
        with self.conexao() as con:
            con.executescript(ESQUEMA)
        logger.debug("Banco pronto em %s", self.caminho)

    # -- consultas ---------------------------------------------------------

    def ultima_data(self, cadeia: str, indicador_id: str, safra: str = "") -> date | None:
        """Ultima data ja armazenada para um box."""
        with self.conexao() as con:
            linha = con.execute(
                """
                SELECT MAX(data_referencia) AS ultima
                  FROM cotacoes
                 WHERE cadeia = ? AND indicador_id = ? AND safra = ?
                """,
                (cadeia, indicador_id, safra),
            ).fetchone()
        if not linha or not linha["ultima"]:
            return None
        return datetime.strptime(linha["ultima"], "%Y-%m-%d").date()

    def indicador_conhecido(self, cadeia: str, indicador_id: str, safra: str = "") -> bool:
        with self.conexao() as con:
            linha = con.execute(
                """
                SELECT 1 FROM controle_indicador
                 WHERE cadeia = ? AND indicador_id = ? AND safra = ?
                """,
                (cadeia, indicador_id, safra),
            ).fetchone()
        return linha is not None

    # -- escrita -----------------------------------------------------------

    def grava_cotacoes(self, registros: list[dict]) -> int:
        """Insere ignorando duplicidades. Devolve quantas linhas entraram."""
        if not registros:
            return 0

        sql = """
            INSERT OR IGNORE INTO cotacoes (
                cadeia, indicador_id, indicador_nome, safra, localidade,
                data_referencia, valor, variacao, unidade, fonte, nota,
                ordem_box, coletado_em
            ) VALUES (
                :cadeia, :indicador_id, :indicador_nome, :safra, :localidade,
                :data_referencia, :valor, :variacao, :unidade, :fonte, :nota,
                :ordem_box, :coletado_em
            )
        """
        with self.conexao() as con:
            antes = con.execute("SELECT COUNT(*) AS n FROM cotacoes").fetchone()["n"]
            con.executemany(sql, registros)
            depois = con.execute("SELECT COUNT(*) AS n FROM cotacoes").fetchone()["n"]
        return depois - antes

    def atualiza_controle(
        self,
        cadeia: str,
        indicador_id: str,
        safra: str,
        indicador_nome: str,
        ultima_data: date | None,
    ) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        with self.conexao() as con:
            con.execute(
                """
                INSERT INTO controle_indicador (
                    cadeia, indicador_id, safra, indicador_nome,
                    ultima_data, ultima_verificacao
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (cadeia, indicador_id, safra) DO UPDATE SET
                    indicador_nome     = excluded.indicador_nome,
                    ultima_data        = COALESCE(excluded.ultima_data, controle_indicador.ultima_data),
                    ultima_verificacao = excluded.ultima_verificacao
                """,
                (
                    cadeia,
                    indicador_id,
                    safra,
                    indicador_nome,
                    ultima_data.isoformat() if ultima_data else None,
                    agora,
                ),
            )

    def registra_execucao(self, cadeia: str, resumo: dict) -> None:
        with self.conexao() as con:
            con.execute(
                """
                INSERT INTO execucoes (
                    iniciado_em, finalizado_em, cadeia, boxes_novos,
                    boxes_atualizados, boxes_inalterados, linhas_inseridas,
                    status, detalhe
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resumo.get("iniciado_em"),
                    datetime.now().isoformat(timespec="seconds"),
                    cadeia,
                    resumo.get("boxes_novos", 0),
                    resumo.get("boxes_atualizados", 0),
                    resumo.get("boxes_inalterados", 0),
                    resumo.get("linhas_inseridas", 0),
                    resumo.get("status", "ok"),
                    resumo.get("detalhe"),
                ),
            )

    # -- leitura para o Excel ---------------------------------------------

    def boxes_da_cadeia(self, cadeia: str) -> list[sqlite3.Row]:
        """Lista os boxes que possuem dados, na ordem em que aparecem no site."""
        with self.conexao() as con:
            return con.execute(
                """
                SELECT indicador_id,
                       safra,
                       MAX(indicador_nome) AS indicador_nome,
                       MIN(ordem_box)      AS ordem_box,
                       MAX(unidade)        AS unidade
                  FROM cotacoes
                 WHERE cadeia = ?
                 GROUP BY indicador_id, safra
                 ORDER BY ordem_box, indicador_nome
                """,
                (cadeia,),
            ).fetchall()

    def historico_do_box(
        self, cadeia: str, indicador_id: str, safra: str
    ) -> list[sqlite3.Row]:
        """Historico completo de um box, pronto para virar aba do Excel."""
        with self.conexao() as con:
            return con.execute(
                """
                SELECT data_referencia, localidade, valor, variacao,
                       unidade, indicador_nome, safra, fonte, coletado_em
                  FROM cotacoes
                 WHERE cadeia = ? AND indicador_id = ? AND safra = ?
                 ORDER BY data_referencia, localidade
                """,
                (cadeia, indicador_id, safra),
            ).fetchall()
