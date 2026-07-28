# Bot IMEA — Indicadores para Power BI

Robô em Python que varre diariamente a página de indicadores do
[IMEA](https://www.imea.com.br/imea-site/indicador-boi), identifica **todos** os
boxes de dados, verifica se a data de atualização mudou e, em caso positivo,
grava os dados novos e regenera uma planilha Excel pronta para o Power BI.

---

## O que ele faz

| Etapa | Descrição |
|---|---|
| 1. Descoberta | Lê a página e identifica **dinamicamente** todos os boxes. Nenhuma lista fixa no código: se o IMEA acrescentar um indicador, ele é capturado sozinho. |
| 2. Coleta | Usa a API pública do IMEA (`api1.imea.com.br`), a mesma que o site consome. Sem navegador, sem Selenium — a execução leva poucos segundos. |
| 3. Comparação | Compara a data de atualização de cada box com a última registrada no banco local. |
| 4. Gravação | Só grava o que tem data nova. Rodar duas vezes no mesmo dia **não duplica** nada. |
| 5. Planilha | Regenera o Excel: uma aba por box, com o histórico empilhado. |

### Um detalhe importante

A página mostra apenas as primeiras linhas de cada box (o resto fica atrás da
barra de rolagem). O bot captura **todas** as linhas. No indicador Boi, por
exemplo, "BOI GORDO À VISTA" traz os **150 municípios**, e não os 4 visíveis na
tela.

---

## Instalação

```bash
git clone https://github.com/fiorott/bot-imea.git
cd bot-imea
pip install -r requirements.txt
python main.py
```

Requisito: Python 3.10 ou superior. Nao e preciso cadastro, chave de API nem
configuracao inicial: o IMEA publica esses dados abertamente.

Se voce so quer a planilha, sem rodar nada, baixe direto o arquivo
`dados/imea_boi.xlsx` pelo botao **Download raw file** no GitHub.

---

## Uso

```bash
python main.py                    # coleta as cadeias ativas no config.yaml
python main.py --cadeia boi       # coleta apenas o boi
python main.py --listar           # mostra os boxes do site sem gravar nada
python main.py --forcar           # regrava mesmo sem mudança de data
python main.py --verboso          # log detalhado
```

No Windows, `run_bot.bat` faz o mesmo com duplo clique.

---

## Formato da planilha (pensado para o Power BI)

Um arquivo por cadeia (`imea_boi.xlsx`), com **uma aba por box** mais uma aba
`_Indice` relacionando o nome do indicador com o nome da aba.

Colunas de cada aba:

| Coluna | Tipo | Observação |
|---|---|---|
| `Data` | Data | Data de referência do indicador. **Primeira coluna**, como pedido |
| `Localidade` | Texto | Município ou região |
| `Valor` | Decimal | Número de verdade, não texto |
| `Variacao_pct` | Decimal | Variação percentual |
| `Unidade` | Texto | `R$/@`, `R$/Cabeça`, `Dias`, `%`… |
| `Indicador` | Texto | Nome do box |
| `Safra` | Texto | Quando aplicável |
| `Fonte` | Texto | Quando informada (ex.: INDEA) |
| `Data_Coleta` | Data/hora | Quando o robô capturou |

Cuidados que evitam retrabalho no Power BI:

- **Datas e números são tipados**, não texto — nada de `Alterar tipo` no Power Query.
- **Dados empilhados**: cada nova data entra abaixo, formando série histórica.
- **Sem células mescladas nem títulos decorativos** acima do cabeçalho.
- Cada aba é uma **Tabela nomeada** do Excel, então o intervalo se expande sozinho.

### Conectando o Power BI

1. **Obter dados → Excel** e selecione `dados/imea_boi.xlsx`.
2. Marque as abas desejadas (elas aparecem como tabelas).
3. **Carregar**. Não é necessário nenhum tratamento.
4. Para atualizar, basta **Atualizar** — o robô mantém o arquivo em dia.

> Dica: se apontar a saída para uma pasta do SharePoint sincronizada, o Power BI
> Service consegue atualizar sozinho, sem gateway.

---

## Execução automática

### Windows — Agendador de Tarefas (não exige administrador)

```bat
agendar.bat            :: agenda para as 08:00
agendar.bat 07:30      :: agenda para o horário informado
```

A tarefa roda com o seu usuário quando você está conectado, por isso **não
precisa de privilégio de administrador**. Comandos úteis:

```bat
schtasks /Run    /TN "BotIMEA_Indicadores"          :: executar agora
schtasks /Query  /TN "BotIMEA_Indicadores" /V /FO LIST
schtasks /Delete /TN "BotIMEA_Indicadores" /F
```

### GitHub Actions (nuvem, redundância)

O arquivo [`.github/workflows/coleta-diaria.yml`](.github/workflows/coleta-diaria.yml)
roda todo dia às 08:00 (horário de Brasília) e faz commit dos dados novos.

Custo: repositório público é gratuito e ilimitado; repositório privado tem
2.000 minutos/mês gratuitos, e este robô consome cerca de 60 minutos/mês.

---

## Salvando no SharePoint

A forma mais simples e segura, **sem precisar de senha no código**: aponte a
saída para a pasta do SharePoint já sincronizada pelo OneDrive. Em
`config.yaml`:

```yaml
saida:
  pasta: "C:/Users/seu.usuario/Empresa/Indicadores IMEA"
```

O cliente do OneDrive sincroniza sozinho. Nunca coloque usuário e senha em
arquivo de configuração: em ambientes com MFA isso não funciona e ainda expõe
a credencial.

---

## Coletando outras cadeias

O IMEA publica outras cadeias com a mesma estrutura. Para ativar, basta editar
`config.yaml` — **nenhuma alteração de código é necessária**:

```yaml
cadeias:
  - nome: soja
    ativo: true      # <- muda para true
```

Cadeias já mapeadas: boi, soja, milho, algodão, suíno e leite.

---

## Estrutura do projeto

```
bot_imea/
├── main.py                 # interface de linha de comando
├── config.yaml             # configuração (cadeias, pasta de saída)
├── run_bot.bat             # execução no Windows
├── agendar.bat             # cria a tarefa diária
├── src/
│   ├── parser_pagina.py    # descobre os boxes dinamicamente
│   ├── coletor.py          # chama a API e cruza os dados
│   ├── banco.py            # SQLite idempotente
│   ├── excel.py            # gera a planilha do Power BI
│   ├── robo.py             # orquestra e compara datas
│   ├── config.py           # leitura da configuração
│   └── log.py              # log em arquivo rotativo
├── testes/test_bot.py      # 15 testes, sem depender de internet
├── dados/                  # Excel + banco (gerados)
└── logs/                   # histórico de execução
```

---

## Testes

```bash
python -m unittest discover -s testes -v
```

---

## Como funciona por dentro

A página do IMEA é uma aplicação Vue 2. A lista de boxes está declarada no
próprio HTML, e os valores chegam por uma chamada da API, sendo cruzados no
navegador por `IndicadorFinalId` + `Safra`. O bot reproduz exatamente essa
lógica em Python:

```
página HTML  ──► lista de boxes (dinâmica)
                          │
API de cotações ──► 740 registros ──► cruzamento ──► 20 boxes preenchidos
```

Por ler a definição da própria página, o robô acompanha mudanças no site sem
precisar de manutenção. Se a estrutura mudar a ponto de impedir a leitura, ele
falha de forma explícita (`ErroParsePagina`) em vez de gravar dado errado.

---

## Solução de problemas

| Situação | O que fazer |
|---|---|
| `Nao encontrei a lista 'indicadores'` | O layout do site mudou. Rode com `--verboso` e verifique o log. |
| Planilha sem novidade | Normal: o IMEA não atualizou aquele box hoje. Confira "Boxes sem alteracao" no log. |
| Excel aberto durante a execução | Feche o arquivo: o Windows bloqueia a gravação. |
| Quero recarregar tudo | Apague `dados/imea.sqlite` e rode novamente. |

Os logs ficam em `logs/bot_imea.log`, com rotação automática.
