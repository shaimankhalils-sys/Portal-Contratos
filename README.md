# Portal de Contratos · Teixeira de Freitas

Sistema interno de consulta e controle dos contratos da Prefeitura Municipal de Teixeira de Freitas.

## Como funciona

```
Planilha no Google Drive ──► rotina automática (GitHub Actions) ──► data/contratos.json ──► site
                                        │
                                        └── consulta o PNCP (CNPJ 13.650.403/0001-28) ──► data/pncp.json
```

- A equipe continua atualizando a planilha **CONTROLE DE VIGÊNCIA DE CONTRATOS GERAL** normalmente.
- Três vezes ao dia (6h, 12h e 18h) a rotina baixa a planilha, padroniza os dados e confere com o PNCP.
- O site só lê os arquivos da pasta `data/`. As minutas continuam no Nextcloud e exigem login.

## Estrutura

| Arquivo | O que é |
|---|---|
| `index.html` | O site (página única) |
| `assets/logo.png` | Logo da Prefeitura (fundo branco) |
| `data/contratos.json` | Contratos lidos da planilha (gerado automaticamente) |
| `data/pncp.json` | Resultado da conferência com o PNCP (gerado automaticamente) |
| `data/minutas.json` | Índice das minutas no Drive institucional (nome, ID e data de cada PDF) |
| `scripts/build_data.py` | Lê a planilha e gera `contratos.json` |
| `scripts/pncp_sync.py` | Consulta o PNCP e gera `pncp.json` |
| `scripts/pncp_itens.py` | Itens (da contratação de origem) e termos aditivos de cada contrato → `data/itens.json`, `data/itens/` |
| `scripts/pncp_anexos.py` | Lê o "ANEXO I – ITENS" dos PDFs do contrato e de cada termo aditivo no PNCP (itens acrescidos/suprimidos). Os PDFs não ficam no repositório; só os itens lidos (`data/pncp_anexos/`). Relatório em `data/anexos_log.txt` |
| `scripts/anexo_itens.py` | Leitor da tabela de itens (usado por `pncp_anexos.py`) |
| `.github/workflows/atualizar-dados.yml` | A rotina automática |

## Minutas no Google Drive

As minutas ficam na pasta **MINUTAS DE CONTRATOS** do Drive institucional (pode ter subpastas por mês/ano).
O nome do arquivo começa pelo número:

- `2-435-2024.pdf` → contrato 2-435-2024
- `1TA-2-435-2024.pdf` → 1º termo aditivo do contrato 2-435-2024

O índice (`data/minutas.json`) é atualizado todo dia às 7h pelo script `scripts/apps-script/minutas.gs`,
que roda dentro da conta institucional (script.google.com). Os PDFs não saem do Drive: o site guarda só o
link, que abre apenas para quem está logado com a conta da Prefeitura.

Instalação do script (uma vez):

1. Em script.google.com, logado com a conta institucional: **Novo projeto**, cole o conteúdo de `minutas.gs`.
2. No GitHub: *Settings (do seu perfil) → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token*. Repository access: **Only select repositories → Portal-Contratos**.
   Permissions → Repository permissions → **Contents: Read and write**. Copie o token.
3. No projeto do Apps Script: **Configurações do projeto → Propriedades do script → GITHUB_TOKEN** = token.
4. Execute `atualizarMinutas` uma vez (autorize o acesso ao Drive) e depois `instalarGatilhoDiario`.

## Configuração (uma vez só)

1. Compartilhar a planilha no Drive como **"Qualquer pessoa com o link — Leitor"**.
2. No repositório: *Settings → Secrets and variables → Actions → Variables* → criar `PLANILHA_ID`
   com o ID da planilha (o trecho entre `/d/` e `/edit` no link).
3. *Settings → Pages* → Source: *Deploy from a branch* → `main` / raiz.
4. *Actions → Atualizar dados → Run workflow* para a primeira atualização.

## Testar no computador

```bash
python3 scripts/build_data.py planilha.xlsx data/contratos.json
python3 -m http.server 8000     # abrir http://localhost:8000
```
