#!/usr/bin/env python3
"""
Portal de Contratos · itens e nº de aditivos do Portal da Transparência (sistema KBF).

Uso:  python3 scripts/portal_import.py <resultcontratos.json | ""> data/contratos.json data/itens.json

Fonte: exportação do Portal da Transparência mantida por Sergio Carneiro
(github.com/sergiocarneiro-adm/contratostx, dados/resultcontratos.json), coletada com
navegador comum e uma pessoa acompanhando. A rotina baixa a versão mais recente a cada
execução; se o download falhar, reaplica a última leitura guardada em data/portal.json.

Regras:
  - itens do contrato: Portal da Transparência tem prioridade (dados cadastrados no sistema,
    com a quantidade contratada); depois o PDF do contrato no PNCP; depois a contratação no PNCP;
  - vale para vigentes e encerrados;
  - guarda, para conferência, o nº de aditivos, a situação e o valor que constam no portal.
"""
import sys, os, re, json, unicodedata, datetime as dt

PASTA_ITENS = "data/itens"
RESUMO = "data/portal.json"


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def chave(n):
    m = re.match(r"^\s*(\d)\s*-\s*0*(\d+)\s*-\s*(\d{4})", n or "")
    return f"{m[1]}-{int(m[2])}-{m[3]}" if m else None


def palavras(nome):
    s = "".join(c for c in unicodedata.normalize("NFD", (nome or "").upper()) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(LTDA|EIRELI|ME|EPP|S/?A|CIA|COMERCIO|SERVICOS?|DE|DA|DO|DOS|DAS|E)\b", " ", s)
    return set(re.findall(r"[A-Z0-9]{3,}", s))


def parecido(a, b):
    sa, sb = palavras(a), palavras(b)
    return bool(sa and sb) and len(sa & sb) / min(len(sa), len(sb)) >= 0.5


def data_iso(s):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def ler_portal(caminho, base):
    """Converte a exportação para {n: resumo + itens}, casando com os contratos da planilha."""
    bruto = json.load(open(caminho, encoding="utf-8"))
    lista = bruto.get("contratos", bruto if isinstance(bruto, list) else [])
    por_chave = {}
    for x in lista:
        k = chave(x.get("numero"))
        if k:
            por_chave.setdefault(k, []).append(x)
    out = {}
    for r in base["vigentes"] + base["encerrados"]:
        if not r.get("seq"):
            continue
        cands = por_chave.get(f"{r['un']}-{int(r['seq'])}-{r['ano']}")
        if not cands:
            continue
        x = next((c for c in cands if parecido(c.get("contratado"), r.get("cr"))), None) \
            or next((c for c in cands if c.get("itens")), cands[0])
        itens = []
        for i in x.get("itens") or []:
            per = num(i.get("periodicidade"))
            prod = re.sub(r"\s+", " ", i.get("descricao") or "").strip()
            if per and per > 1:
                prod += f" · periodicidade {per:g}"
            lote = (i.get("lote") or "").strip()
            itens.append({"prod": prod, "un": "", "qtd": num(i.get("quantidade")),
                          "unit": num(i.get("valor_unitario")), "total": num(i.get("valor_total")),
                          "lote": "" if lote.upper() in ("S/L", "SL", "-") else lote})
        out[r["n"]] = {
            "adt": int(num(x.get("aditivos")) or 0),
            "sit": (x.get("situacao") or "").strip(),
            "v": num(x.get("valor")),
            "ini": data_iso(x.get("inicio_vigencia")),
            "fim": data_iso(x.get("fim_vigencia")),
            "cr": x.get("contratado"),
            "chave": x.get("chave_portal"),
            "itens": itens,
        }
    return out


def main(fonte, src_base, dest_itx):
    base = json.load(open(src_base, encoding="utf-8"))
    itx = json.load(open(dest_itx, encoding="utf-8")) if os.path.exists(dest_itx) else {"contratos": {}}
    contratos = itx.setdefault("contratos", {})

    if fonte and os.path.exists(fonte):
        dados = ler_portal(fonte, base)
        resumo = {"lido": dt.datetime.now().isoformat(timespec="minutes"),
                  "fonte": "Portal da Transparência (exportação de github.com/sergiocarneiro-adm/contratostx)",
                  "contratos": {n: {k: v for k, v in d.items() if k != "itens"} | {"qi": len(d["itens"]),
                                "ti": round(sum(i["total"] or 0 for i in d["itens"]), 2)}
                                for n, d in dados.items()}}
        os.makedirs(PASTA_ITENS, exist_ok=True)
        for n, d in dados.items():
            if d["itens"]:
                json.dump(d["itens"], open(os.path.join(PASTA_ITENS, f"portal-{n}.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, separators=(",", ":"))
        json.dump(resumo, open(RESUMO, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print(f"Portal da Transparência: {len(dados)} contratos da planilha encontrados na exportação")
    elif os.path.exists(RESUMO):
        resumo = json.load(open(RESUMO, encoding="utf-8"))
        print("Exportação indisponível; reaplicando a última leitura de", resumo.get("lido"))
    else:
        print("Sem exportação do Portal da Transparência; nada a fazer.")
        return

    usados = 0
    for n, p in resumo["contratos"].items():
        c = contratos.get(n)
        if c is None:
            c = contratos[n] = {"fonte": "Portal da Transparência", "lido": resumo["lido"], "aditivos": []}
        c["portal"] = {"adt": p["adt"], "sit": p["sit"], "v": p["v"], "lido": resumo["lido"][:10]}
        arq = os.path.join(PASTA_ITENS, f"portal-{n}.json")
        if p["qi"] and os.path.exists(arq):
            # o portal tem prioridade: copia para o arquivo que o site lê
            with open(arq, encoding="utf-8") as fh, open(os.path.join(PASTA_ITENS, n + ".json"), "w", encoding="utf-8") as out:
                out.write(fh.read())
            c["fonte_itens"], c["qi"], c["ti"] = "Portal da Transparência", p["qi"], p["ti"]
            usados += 1
    json.dump(itx, open(dest_itx, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Itens do Portal da Transparência aplicados em {usados} contratos")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
