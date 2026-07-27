"""Extrai a definicao dos boxes (indicadores) diretamente da pagina do IMEA.

A pagina do IMEA e uma aplicacao Vue 2. A lista de boxes exibidos fica
declarada no proprio HTML, dentro de ``new Vue({... data: { indicadores: [...] }})``.
Os valores vem depois de uma chamada axios para a API publica e sao cruzados
no navegador por ``IndicadorFinalId`` + ``Safra``.

Este modulo reproduz essa logica em Python, lendo a definicao dos boxes de
forma DINAMICA. Assim, se o IMEA acrescentar, remover ou renomear um box,
o bot acompanha sozinho, sem precisar de alteracao no codigo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


class ErroParsePagina(RuntimeError):
    """A estrutura da pagina mudou e nao foi possivel ler os indicadores."""


@dataclass
class Indicador:
    """Um box da pagina (ex.: 'BOI GORDO A VISTA')."""

    indicador_final_id: str
    nome: str
    unidade: str = ""
    localidade_rotulo: str = "Localidade"
    safra: str | None = None
    fonte: str | None = None
    nota: str | None = None
    exibe_decimal: bool = True
    usa_antigo: bool = False
    id_antigo: str | None = None
    id_safra_antigo: str | None = None
    ordem: int = 0

    @property
    def titulo(self) -> str:
        """Titulo como aparece na tela, incluindo a safra quando houver."""
        return f"{self.nome} - {self.safra}" if self.safra else self.nome


@dataclass
class ConfigApi:
    """Endpoint que a pagina usa para buscar as cotacoes."""

    base_url: str = "https://api1.imea.com.br/api"
    url: str = ""

    @property
    def url_completa(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.url.lstrip('/')}"


@dataclass
class DefinicaoPagina:
    """Resultado completo da leitura da pagina."""

    api: ConfigApi
    indicadores: list[Indicador] = field(default_factory=list)
    api_antiga: str | None = None


# --------------------------------------------------------------------------
# Conversao de objeto literal JavaScript para JSON
# --------------------------------------------------------------------------

def _extrai_bloco_balanceado(texto: str, inicio: int, abre: str, fecha: str) -> str:
    """Devolve o trecho delimitado por ``abre``/``fecha`` respeitando aninhamento.

    Ignora delimitadores que aparecam dentro de strings.
    """
    profundidade = 0
    aspas: str | None = None
    escapado = False

    for pos in range(inicio, len(texto)):
        char = texto[pos]

        if escapado:
            escapado = False
            continue
        if char == "\\":
            escapado = True
            continue

        if aspas:
            if char == aspas:
                aspas = None
            continue
        if char in "\"'":
            aspas = char
            continue

        if char == abre:
            profundidade += 1
        elif char == fecha:
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio : pos + 1]

    raise ErroParsePagina("Bloco JavaScript nao fechado corretamente na pagina.")


def _js_para_json(trecho: str) -> Any:
    """Converte um literal JavaScript simples em estrutura Python.

    Trata as diferencas em relacao ao JSON: chaves sem aspas, strings com
    aspas simples, virgula sobrando antes do fechamento e comentarios.
    """
    texto = trecho

    # Remove comentarios de linha, preservando o que estiver dentro de strings.
    texto = re.sub(r"(?<![:\w])//[^\n\r]*", "", texto)
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)

    resultado: list[str] = []
    aspas: str | None = None
    escapado = False
    pos = 0

    while pos < len(texto):
        char = texto[pos]

        if aspas:
            if escapado:
                escapado = False
                resultado.append(char)
            elif char == "\\":
                escapado = True
                resultado.append(char)
            elif char == aspas:
                aspas = None
                resultado.append('"')
            elif char == '"':
                # Aspas duplas dentro de string delimitada por aspas simples.
                resultado.append('\\"')
            else:
                resultado.append(char)
            pos += 1
            continue

        if char in "\"'":
            aspas = char
            resultado.append('"')
            pos += 1
            continue

        # Chave sem aspas: {Nome: ...} ou , Nome: ...
        match = re.match(r"([A-Za-z_$][\w$]*)\s*:", texto[pos:])
        if match and (not resultado or resultado[-1].strip()[-1:] in "{,"):
            resultado.append(f'"{match.group(1)}":')
            pos += match.end()
            continue

        resultado.append(char)
        pos += 1

    limpo = "".join(resultado)
    # Remove virgula sobrando antes de } ou ]
    limpo = re.sub(r",(\s*[}\]])", r"\1", limpo)

    try:
        return json.loads(limpo)
    except json.JSONDecodeError as erro:  # pragma: no cover - defensivo
        raise ErroParsePagina(f"Falha ao interpretar o bloco da pagina: {erro}") from erro


# --------------------------------------------------------------------------
# Leitura da definicao da pagina
# --------------------------------------------------------------------------

def _localiza_literal(html: str, chave: str, abre: str, fecha: str) -> str | None:
    """Encontra ``chave:`` e devolve o literal que vem logo depois."""
    padrao = r"\b" + re.escape(chave) + r"\s*:\s*(?=" + re.escape(abre) + r")"
    for match in re.finditer(padrao, html):
        try:
            return _extrai_bloco_balanceado(html, match.end(), abre, fecha)
        except ErroParsePagina:
            continue
    return None


def extrai_definicao(html: str) -> DefinicaoPagina:
    """Le o HTML da pagina e devolve os boxes e o endpoint da API."""
    bloco_indicadores = _localiza_literal(html, "indicadores", "[", "]")
    if not bloco_indicadores:
        raise ErroParsePagina(
            "Nao encontrei a lista 'indicadores' na pagina. "
            "O layout do site provavelmente mudou."
        )

    brutos = _js_para_json(bloco_indicadores)
    if not isinstance(brutos, list) or not brutos:
        raise ErroParsePagina("A lista de indicadores veio vazia ou invalida.")

    indicadores: list[Indicador] = []
    for ordem, item in enumerate(brutos, start=1):
        if not isinstance(item, dict):
            continue
        nome = (item.get("Nome") or "").strip()
        if not nome:
            continue
        indicadores.append(
            Indicador(
                indicador_final_id=str(item.get("IndicadorFinalId") or ""),
                nome=nome,
                unidade=(item.get("Unidade") or "").strip(),
                localidade_rotulo=(item.get("Localidade") or "Localidade").strip(),
                safra=item.get("Safra"),
                fonte=item.get("Fonte"),
                nota=item.get("Nota"),
                exibe_decimal=bool(item.get("ExibeDecimal", True)),
                usa_antigo=bool(item.get("UsaAntigo", False)),
                id_antigo=(str(item["IdAntigo"]) if item.get("IdAntigo") is not None else None),
                id_safra_antigo=(
                    str(item["IdSafraAntigo"]) if item.get("IdSafraAntigo") is not None else None
                ),
                ordem=ordem,
            )
        )

    if not indicadores:
        raise ErroParsePagina("Nenhum indicador valido foi encontrado na pagina.")

    return DefinicaoPagina(
        api=_extrai_config_api(html),
        indicadores=indicadores,
        api_antiga=_extrai_url_antiga(html),
    )


def _extrai_config_api(html: str) -> ConfigApi:
    """Descobre o endpoint de cotacoes declarado na pagina."""
    bloco = _localiza_literal(html, "config", "{", "}")
    if bloco:
        try:
            dados = _js_para_json(bloco)
        except ErroParsePagina:
            dados = None
        if isinstance(dados, dict) and dados.get("url"):
            return ConfigApi(
                base_url=str(dados.get("baseURL") or "https://api1.imea.com.br/api"),
                url=str(dados["url"]),
            )

    # Alternativa: monta a partir do id da cadeia presente no HTML.
    match = re.search(r"/v2/mobile/cadeias/(\d+)/cotacoes", html)
    if match:
        return ConfigApi(url=f"/v2/mobile/cadeias/{match.group(1)}/cotacoes")

    raise ErroParsePagina("Nao localizei o endpoint de cotacoes na pagina.")


def _extrai_url_antiga(html: str) -> str | None:
    """Endpoint legado usado por alguns indicadores de alguma cadeias."""
    bloco = _localiza_literal(html, "configAntigo", "{", "}")
    if not bloco:
        return None
    try:
        dados = _js_para_json(bloco)
    except ErroParsePagina:
        return None
    if isinstance(dados, dict) and dados.get("url"):
        return str(dados["url"])
    return None
