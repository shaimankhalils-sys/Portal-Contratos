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
| `.github/workflows/atualizar-dados.yml` | A rotina automática |

## Minutas no Google Drive

As minutas ficam na pasta **MINUTAS DE CONTRATOS** do Drive institucional, em subpastas por mês.
Cada PDF deve ter o número do contrato no início do nome:

- `2-670-2026.pdf` → contrato
- `2-670-2026 - 1º Termo Aditivo.pdf` → aditivo do mesmo contrato

O site só guarda o link; o arquivo abre apenas para quem está logado com a conta da Prefeitura.


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
