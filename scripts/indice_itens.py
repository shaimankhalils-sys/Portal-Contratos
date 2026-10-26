#!/usr/bin/env python3
"""
Portal de Contratos · índice de busca por itens.

Uso:  python3 scripts/indice_itens.py data/itens.json data/busca_itens.json

Junta, num arquivo só e compacto, a descrição de todos os itens de cada contrato
(itens do contrato + itens dos termos aditivos), para que a pesquisa do site encontre
um contrato pelo item (ex.: "cloro líquido" dentro de "materiais de limpeza") sem
precisar abrir contrato por contrato.

Formato: {"atualizado_em": ..., "c": {"2-128-2026": ["descrição", "1TA: descrição", ...]}}
"""
import sys, os, re, json, datetime as dt

LIMITE = 220  # caracteres por item (o começo da descrição é o que identifica o produto)


def limpa(s):
    s = re.sub(r"\(cid:\d+\)", " ", s or "")  # resíduo da leitura de alguns PDFs
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\d{1,4}\s*-\s*(?=\d{6,})", "", s)  # "12 - 9900511750 - ..." -> "9900511750 - ..."
    return s[:LIMITE]


def main(src, dest):
    idx = json.load(open(src, encoding="utf-8"))
    out = {}
    for n, c in idx.get("contratos", {}).items():
        lista, vistos = [], set()
        cam = os.path.join("data", "itens", n + ".json")
        if os.path.exists(cam):
            for x in json.load(open(cam, encoding="utf-8")):
                d = limpa(x.get("prod"))
                if d and d.lower() not in vistos:
                    vistos.add(d.lower()); lista.append(d)
        for a in c.get("aditivos", []):
            for x in a.get("itens") or []:
                d = limpa(x.get("prod"))
                if d and d.lower() not in vistos:
                    vistos.add(d.lower()); lista.append(f"{a.get('n')}: {d}")
        if lista:
            out[n] = lista
    json.dump({"atualizado_em": dt.datetime.now().isoformat(timespec="minutes"), "c": out},
              open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Índice de itens: {len(out)} contratos, {sum(len(v) for v in out.values())} itens, "
          f"{os.path.getsize(dest) / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
