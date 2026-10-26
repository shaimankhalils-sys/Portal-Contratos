#!/usr/bin/env python3
"""
Lê a tabela "ANEXO I - ITENS DO CONTRATO / DO ADITIVO" do texto de um PDF de contrato ou termo aditivo.

Formato típico (texto extraído do PDF):
    ANEXO I - ITENS DO CONTRATO Nº 2-128-2026
    ITEM DESCRIÇÃO UND MARCA QUANT VALOR UNT VLR TOTAL
    9900513872 – CALÇA DE BRIM COM BOLSOS
    (TAMANHOS DIVERSOS):Calça de brim sem
    01 zíper, cintura em elástico, bolsos traseiro e UND PROPRIA 750 R$ 54,20 R$ 40.650,00
    frontal. Com estampa da logomarca oficial
    VALOR TOTAL R$ 40.650,00

Cada item tem uma "linha de valores" que termina em  <qtd> R$ <unitário> R$ <total>.
A descrição fica em volta dessa linha (a célula é centralizada verticalmente no documento).
A leitura confere quantidade × unitário = total, o que também corrige números quebrados
pela extração de texto (ex.: "75 0" -> 750).
"""
import re

UNIDADES = {
    "UND", "UN", "UNI", "UNID", "UNIDADE", "UNIDADES", "U", "M²", "M2", "M³", "M3", "M", "MT", "MTS", "METRO", "METROS", "KM",
    "KG", "G", "GR", "MG", "TON", "T", "L", "LT", "LTS", "LITRO", "LITROS", "ML", "GL", "GALÃO", "GALAO",
    "CX", "CAIXA", "PCT", "PACOTE", "PC", "PÇ", "PÇA", "PCA", "PEÇA", "PECA", "FR", "FRASCO", "FRS", "AMP", "AMPOLA",
    "CP", "COMP", "CPR", "COMPRIMIDO", "CAPS", "CÁPSULA", "RESMA", "RM", "ROLO", "RL", "PAR", "PARES", "JG", "JOGO",
    "KIT", "KT", "SERV", "SERVIÇO", "SERVICO", "SV", "MES", "MÊS", "MESES", "H", "HR", "HORA", "HORAS", "DIA", "DIAS",
    "DIÁRIA", "DIARIA", "SC", "SACO", "BD", "BALDE", "DZ", "DÚZIA", "DUZIA", "FD", "FARDO", "CJ", "CONJ", "CONJUNTO",
    "TB", "TUBO", "BL", "BLOCO", "BISN", "BISNAGA", "ENV", "ENVELOPE", "POTE", "PT", "LATA", "LT.", "GARRAFA", "GF",
    "BOMBONA", "CARTELA", "CT", "ANO", "SEMANA", "EVENTO", "DIÁRIAS", "VB", "VERBA", "LOTE", "M²/MÊS", "UNID.", "UND.",
}

LINHA_VALOR = re.compile(r"^(?P<antes>.*?)\s*R\$\s*(?P<unit>\d[\d.]*(?:,\d{1,4})?)\s+R\$\s*(?P<total>\d[\d.]*(?:,\d{1,2})?)\s*$")
CODIGO = re.compile(r"^\s*(?:\d{1,3}\s+)?(?P<cod>\d{5,12})\s*(?:[-–—:]\s*|\s+(?=[A-ZÀ-Ú]{2}))")
FIM = re.compile(r"^\s*(VALOR\s+TOTAL|TOTAL\s+GERAL|TOTAL\s*:)", re.I)
INICIO = re.compile(r"ITENS\s+D[OA]\s+(CONTRATO|ADITIVO|TERMO)|^ITEM\s+(DESCRI|ESPECIF|PRODUTO)", re.I)
CABECALHO = re.compile(r"^ITEM\s+(DESCRI|ESPECIF|PRODUTO)|\bVLR\.?\s*UNIT|\bVALOR\s+UN", re.I)
RODAPE = re.compile(r"PREFEITURA MUNICIPAL|PREF\s*EITURA|ESTADO DA BAHIA|PROCESSO ADMINISTRATIVO", re.I)


def num(s):
    s = re.sub(r"\s+", "", s or "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def normaliza(linha):
    """Junta dígitos separados por espaço dentro de valores em R$ ('R$ 10 . 135 , 40' -> 'R$ 10.135,40')."""
    def junta(m):
        return "R$ " + re.sub(r"\s+", "", m.group(1))
    linha = re.sub(r"R\$\s*(\d[\d.,\s]*?\d)(?=\s+R\$|\s*$|\s+\()", junta, linha)
    return re.sub(r"\s+", " ", linha).strip()


def _separa_quantidade(tokens, unit, total):
    """Encontra a quantidade (e a unidade/marca) no fim dos tokens, conferindo qtd × unit ≈ total."""
    nums = []
    for i in range(len(tokens) - 1, max(-1, len(tokens) - 5), -1):
        if re.fullmatch(r"\d[\d.]*(,\d+)?", tokens[i]):
            nums.append(i)
        else:
            break
    candidatos = []
    if nums:
        ultimo = nums[0]
        candidatos.append((ultimo, tokens[ultimo]))
        if len(nums) >= 2:  # número quebrado: "75 0" -> "750"
            candidatos.append((nums[1], tokens[nums[1]] + tokens[ultimo]))
        if len(nums) >= 3:
            candidatos.append((nums[2], tokens[nums[2]] + tokens[nums[1]] + tokens[ultimo]))
    for ini, txt in candidatos:
        q = num(txt)
        if q and total and abs(q * unit - total) <= max(0.05, total * 0.005):
            return ini, q
    if candidatos:  # sem conferência possível: usa o último número
        return candidatos[0][0], num(candidatos[0][1])
    return len(tokens), (total / unit if unit else None)


def confere(x):
    q, u, t = x.get("qtd"), x.get("unit"), x.get("total")
    return bool(q and u and t and abs(q * u - t) <= max(0.06, t * 0.006))


def valida(itens):
    """Mantém só itens em que quantidade × unitário = total. Se a maioria não confere, a tabela
    não é de itens (ex.: planilha de medição de obra) e a leitura é descartada."""
    bons = [x for x in itens if confere(x)]
    return bons if itens and len(bons) >= 0.6 * len(itens) else []


def recorta(texto):
    """Trecho do texto com a tabela de itens (do título/cabeçalho até o VALOR TOTAL), ou ''."""
    linhas = [normaliza(l) for l in texto.splitlines()]
    linhas = [l for l in linhas if l]
    for ini, l in enumerate(linhas):
        if not INICIO.search(l):
            continue
        prox = linhas[ini:ini + 12]
        if not any(CABECALHO.search(x) or LINHA_VALOR.match(x) for x in prox):
            continue
        fim = next((j for j in range(ini + 1, len(linhas)) if FIM.match(linhas[j])), min(len(linhas), ini + 400) - 1)
        return "\n".join(linhas[ini:fim + 1])
    return ""


def ler_anexo(texto):
    """Devolve (itens, valor_total_declarado). Lista vazia se não houver tabela reconhecível."""
    linhas = [l for l in recorta(texto).splitlines() if l]
    if not linhas:
        return [], None
    ini = 0
    corpo, total_doc = [], None
    for l in linhas[ini + 1:]:
        if FIM.match(l):
            m = re.search(r"R\$\s*(\d[\d.]*,\d{2})", l)
            total_doc = num(m.group(1)) if m else None
            break
        if CABECALHO.search(l) or RODAPE.search(l) or re.fullmatch(r"-+\s*p\d+|\d+\s*/\s*\d+", l):
            continue
        corpo.append(l)

    # localiza as linhas de valores
    idx = [i for i, l in enumerate(corpo) if LINHA_VALOR.match(l) and "R$" not in LINHA_VALOR.match(l).group("antes")]
    if not idx:
        return [], total_doc
    tem_codigo = any(CODIGO.match(l) for l in corpo)
    itens, usado = [], set()
    for k, i in enumerate(idx):
        m = LINHA_VALOR.match(corpo[i])
        unit, total = num(m.group("unit")), num(m.group("total"))
        tokens = m.group("antes").split()
        pos_q, qtd = _separa_quantidade(tokens, unit, total)
        antes_q = tokens[:pos_q]
        # unidade: token conhecido mais à direita; o que estiver entre unidade e quantidade é a marca
        pos_u = next((j for j in range(len(antes_q) - 1, -1, -1) if antes_q[j].upper().rstrip(".") in UNIDADES
                      or antes_q[j].upper() in UNIDADES), None)
        if pos_u is None and antes_q:
            pos_u = len(antes_q) - 1
        un = antes_q[pos_u] if pos_u is not None else ""
        marca = " ".join(antes_q[pos_u + 1:]) if pos_u is not None else ""
        desc_linha = antes_q[:pos_u] if pos_u is not None else antes_q
        numero = None
        if desc_linha and re.fullmatch(r"\d{1,3}", desc_linha[0]):
            numero = int(desc_linha[0])
            desc_linha = desc_linha[1:]

        # descrição: linhas antes (desde o item anterior) + trecho da própria linha + linhas depois
        anterior = idx[k - 1] if k else -1
        proximo = idx[k + 1] if k + 1 < len(idx) else len(corpo)
        antes = [j for j in range(anterior + 1, i) if j not in usado]
        depois = list(range(i + 1, proximo))
        if tem_codigo:
            # o código do produto marca o início de cada item
            inicio_prox = next((j for j in depois if CODIGO.match(corpo[j])), None)
            depois = [j for j in depois if inicio_prox is None or j < inicio_prox]
            if k + 1 == len(idx):
                depois = list(range(i + 1, proximo))
        else:
            # célula centralizada: depois da linha de valores há ~tantas linhas quanto antes
            if k + 1 < len(idx):
                depois = depois[:len(antes)]
        usado.update(antes + depois + [i])
        partes = [corpo[j] for j in antes] + [" ".join(desc_linha)] + [corpo[j] for j in depois]
        desc = re.sub(r"\s+", " ", " ".join(p for p in partes if p)).strip(" -–")
        if marca:
            desc = re.sub(rf"\s*\b{re.escape(marca)}\b\s*$", "", desc)
        cod = CODIGO.match(desc)
        itens.append({
            "n": numero or (k + 1),
            "cod": cod.group("cod") if cod else "",
            "prod": desc[:700],
            "un": un.upper().rstrip("."),
            "marca": marca,
            "qtd": qtd,
            "unit": unit,
            "total": total,
        })
    return valida(itens), total_doc


def _col(cab, *padroes):
    for i, c in enumerate(cab):
        for p in padroes:
            if re.search(p, c):
                return i
    return None


def ler_tabelas(tabelas):
    """Lê a tabela de itens a partir das células (pdfplumber extract_tables), quando o PDF tem bordas.
    tabelas: lista de tabelas (cada uma, lista de linhas; cada linha, lista de células)."""
    itens, mapa = [], None
    for tab in tabelas:
        for linha in tab:
            cel = [re.sub(r"\s+", " ", c or "").strip() for c in linha]
            cab = [c.upper() for c in cel]
            if _col(cab, r"DESCRI|ESPECIFICA|PRODUTO") is not None and _col(cab, r"TOTAL") is not None:
                mapa = {
                    "n": _col(cab, r"^ITEM|^IT\.?$|^Nº|^LOTE"),
                    "desc": _col(cab, r"DESCRI|ESPECIFICA|PRODUTO"),
                    "un": _col(cab, r"^UN|^UND|^UNID|MEDIDA"),
                    "marca": _col(cab, r"MARCA|FABRICANTE"),
                    "qtd": _col(cab, r"QUANT|QTD|QTDE"),
                    "unit": _col(cab, r"UNIT|UNT|V\.?\s*UN|VALOR UN|VLR\.? UN|PRE[ÇC]O UN"),
                    "total": max(i for i, c in enumerate(cab) if "TOTAL" in c),
                    "ncol": len(cel),
                }
                continue
            if not mapa or len(cel) != mapa["ncol"]:
                continue
            g = lambda k: cel[mapa[k]] if mapa.get(k) is not None and mapa[k] < len(cel) else ""
            total, unit = num(re.sub(r"[R$\s]", "", g("total"))), num(re.sub(r"[R$\s]", "", g("unit")))
            if not total or not g("desc"):
                continue
            qtd = num(g("qtd").replace(" ", ""))
            if (not qtd) and unit:
                qtd = round(total / unit, 3)
            desc = g("desc")
            cod = CODIGO.match(desc)
            n = re.sub(r"\D", "", g("n"))
            itens.append({"n": int(n) if n and len(n) <= 4 else len(itens) + 1, "cod": cod.group("cod") if cod else "",
                          "prod": desc[:700], "un": g("un").upper().rstrip("."), "marca": g("marca"),
                          "qtd": qtd, "unit": unit, "total": total})
    return valida(itens)


def filtra_tabelas(tabelas):
    """Guarda só as linhas que interessam (cabeçalho de itens e linhas com valores), para reler depois sem baixar o PDF."""
    out = []
    for tab in tabelas:
        linhas = []
        for linha in tab:
            cel = [re.sub(r"\s+", " ", c or "").strip() for c in linha]
            txt = " ".join(cel).upper()
            if ("DESCRI" in txt or "ESPECIFICA" in txt or "PRODUTO" in txt) and "TOTAL" in txt or re.search(r"\d,\d{2}", txt):
                linhas.append(cel)
        if linhas:
            out.append(linhas)
    return out


if __name__ == "__main__":
    import sys
    t = open(sys.argv[1], encoding="utf-8").read()
    its, tot = ler_anexo(t)
    for x in its:
        print(x)
    print("total declarado:", tot, "| soma:", round(sum(x["total"] or 0 for x in its), 2))
