"""Testes do Bot IMEA. Nao dependem de internet.

Executar:  python -m unittest discover -s testes -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.banco import BancoIMEA  # noqa: E402
from src.coletor import ColetorIMEA, _converte_data, _converte_numero  # noqa: E402
from src.excel import nome_de_aba  # noqa: E402
from src.parser_pagina import ErroParsePagina, extrai_definicao  # noqa: E402

HTML_EXEMPLO = """
<html><body><div id="app"></div>
<script>
var app = new Vue({
    el: '#app',
    data: {
        loading: true,
        config: {
            url: '/v2/mobile/cadeias/2/cotacoes',
            baseURL: 'https://api1.imea.com.br/api'
        },
        configAntigo: {
            url: 'indicadores/buscarIndicadores?produtoId=10',
        },
        indicadores: [{
               IndicadorFinalId: '111',
               Localidade: 'Região',
               Nome: 'BOI GORDO À VISTA',
               Unidade: 'R$/@',
               Safra: null,
               Cotacoes: [],
               Data: '',
               ExibeDecimal: true,
               Nota:'* Boi comum, sem premiação China'
           },
           {
               IndicadorFinalId: '222',
               Localidade: 'Região',
               Nome: 'UTL. DA CAP. FRIGORÍFICA - TOTAL',
               Unidade: '%',
               Safra: '2025/26',
               Cotacoes: [],
               Data: '',
               ExibeDecimal: true,
               Fonte: 'INDEA'
           }]
    }
})
</script></body></html>
"""


class TesteParserPagina(unittest.TestCase):
    """A leitura dos boxes precisa ser dinamica e tolerante a JS."""

    def setUp(self) -> None:
        self.definicao = extrai_definicao(HTML_EXEMPLO)

    def test_encontra_todos_os_boxes(self):
        self.assertEqual(len(self.definicao.indicadores), 2)

    def test_le_atributos_do_box(self):
        primeiro = self.definicao.indicadores[0]
        self.assertEqual(primeiro.nome, "BOI GORDO À VISTA")
        self.assertEqual(primeiro.unidade, "R$/@")
        self.assertEqual(primeiro.indicador_final_id, "111")
        self.assertIsNone(primeiro.safra)
        self.assertIn("Boi comum", primeiro.nota or "")

    def test_titulo_inclui_safra(self):
        segundo = self.definicao.indicadores[1]
        self.assertEqual(segundo.titulo, "UTL. DA CAP. FRIGORÍFICA - TOTAL - 2025/26")
        self.assertEqual(segundo.fonte, "INDEA")

    def test_descobre_endpoint(self):
        self.assertEqual(
            self.definicao.api.url_completa,
            "https://api1.imea.com.br/api/v2/mobile/cadeias/2/cotacoes",
        )

    def test_pagina_invalida_gera_erro(self):
        with self.assertRaises(ErroParsePagina):
            extrai_definicao("<html><body>sem indicadores</body></html>")


class TesteConversoes(unittest.TestCase):
    """Numeros e datas precisam virar tipos reais para o Power BI."""

    def test_datas_em_varios_formatos(self):
        self.assertEqual(_converte_data("2026-07-27 00:00:00"), date(2026, 7, 27))
        self.assertEqual(_converte_data("2026-07-27"), date(2026, 7, 27))
        self.assertEqual(_converte_data("27/07/2026"), date(2026, 7, 27))
        self.assertIsNone(_converte_data(None))
        self.assertIsNone(_converte_data(""))

    def test_numeros_em_formato_ptbr(self):
        self.assertEqual(_converte_numero(315.5), 315.5)
        self.assertEqual(_converte_numero("4.465,93"), 4465.93)
        self.assertEqual(_converte_numero("0,45"), 0.45)
        self.assertEqual(_converte_numero("-2,11"), -2.11)
        self.assertIsNone(_converte_numero(None))
        self.assertIsNone(_converte_numero("-"))


class TesteCruzamento(unittest.TestCase):
    """O cruzamento deve seguir a mesma regra do site: id + safra."""

    def test_separa_cotacoes_por_indicador(self):
        indicadores = extrai_definicao(HTML_EXEMPLO).indicadores
        cotacoes = [
            {
                "IndicadorFinalId": "111",
                "Safra": None,
                "Localidade": "Sorriso",
                "Valor": 315.5,
                "Variacao": 0.41,
                "DataPublicacao": "2026-07-27 00:00:00",
            },
            {
                "IndicadorFinalId": "222",
                "Safra": "2025/26",
                "Localidade": "Mato Grosso",
                "Valor": 88.2,
                "Variacao": -1.0,
                "DataPublicacao": "2026-07-20 00:00:00",
            },
        ]

        do_primeiro = ColetorIMEA._filtra_atual(indicadores[0], cotacoes)
        self.assertEqual(len(do_primeiro), 1)
        self.assertEqual(do_primeiro[0].localidade, "Sorriso")
        self.assertEqual(do_primeiro[0].valor, 315.5)

        do_segundo = ColetorIMEA._filtra_atual(indicadores[1], cotacoes)
        self.assertEqual(len(do_segundo), 1)
        self.assertEqual(do_segundo[0].localidade, "Mato Grosso")


class TesteNomeDeAba(unittest.TestCase):
    """O Excel limita a 31 caracteres e proibe alguns simbolos."""

    def test_remove_acentos_e_respeita_limite(self):
        usados: set[str] = set()
        nome = nome_de_aba("UTL. DA CAP. FRIGORÍFICA - TOTAL", usados)
        self.assertLessEqual(len(nome), 31)
        self.assertNotIn("Í", nome)

    def test_remove_caracteres_proibidos(self):
        usados: set[str] = set()
        nome = nome_de_aba("SOJA [MT]: 2025/26", usados)
        for proibido in "[]:*?/\\":
            self.assertNotIn(proibido, nome)

    def test_evita_nomes_repetidos(self):
        usados: set[str] = set()
        primeiro = nome_de_aba("BOI GORDO", usados)
        segundo = nome_de_aba("BOI GORDO", usados)
        self.assertNotEqual(primeiro, segundo)


class TesteBanco(unittest.TestCase):
    """A gravacao precisa ser idempotente."""

    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.banco = BancoIMEA(Path(self.pasta.name) / "teste.sqlite")
        self.registro = {
            "cadeia": "boi",
            "indicador_id": "111",
            "indicador_nome": "BOI GORDO",
            "safra": "",
            "localidade": "Sorriso",
            "data_referencia": "2026-07-27",
            "valor": 315.5,
            "variacao": 0.41,
            "unidade": "R$/@",
            "fonte": None,
            "nota": None,
            "ordem_box": 1,
            "coletado_em": "2026-07-27T20:00:00",
        }

    def tearDown(self) -> None:
        self.pasta.cleanup()

    def test_nao_duplica_o_mesmo_dado(self):
        self.assertEqual(self.banco.grava_cotacoes([self.registro]), 1)
        self.assertEqual(self.banco.grava_cotacoes([self.registro]), 0)

    def test_guarda_a_ultima_data(self):
        self.banco.grava_cotacoes([self.registro])
        self.assertEqual(self.banco.ultima_data("boi", "111"), date(2026, 7, 27))

    def test_data_nova_e_aceita(self):
        self.banco.grava_cotacoes([self.registro])
        novo = dict(self.registro, data_referencia="2026-07-28", valor=320.0)
        self.assertEqual(self.banco.grava_cotacoes([novo]), 1)
        self.assertEqual(self.banco.ultima_data("boi", "111"), date(2026, 7, 28))

    def test_indicador_desconhecido_no_inicio(self):
        self.assertFalse(self.banco.indicador_conhecido("boi", "111"))
        self.banco.atualiza_controle("boi", "111", "", "BOI GORDO", date(2026, 7, 27))
        self.assertTrue(self.banco.indicador_conhecido("boi", "111"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
