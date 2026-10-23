#!/usr/bin/env python3
"""
Contratos - TX · cruza a planilha com os contratos publicados no PNCP.

Uso:  python3 scripts/pncp_sync.py data/contratos.json data/pncp.json

Consulta a API pública do PNCP (sem login) por CNPJ do órgão e grava, para
cada contrato da planilha, se ele foi encontrado no PNCP:
    ok          publicado e com valor compatível
    divergente  publicado, mas valor ou fim de vigência diferente
    ausente     não encontrado no PNCP
Também lista os contratos que estão no PNCP mas não estão na planilha.

Roda na rotina automática do GitHub (Actions); não é chamado pelo navegador.
"""
import sys, json, re, time, unicodedata, datetime as dt
import urllib.request, urllib.parse, urllib.error

CNPJ = "13650403000128"
API = "https://pncp.gov.br/api/consulta/v1/contratos"
ANO_INICIAL = 2021
TAM_PAGINA = 500


def get(params, tentativas=4):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "contratos-tx/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                if r.status == 204:
                    return {"data": [], "totalPaginas": 0}
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 204:
                return {"data": [], "totalPaginas": 0}
            if i == tentativas - 1:
                raise
        except Exception as e:
            print(f"  tentativa {i + 1} falhou: {e}", flush=True)
            if i == tentativas - 1:
                raise
        time.sleep(3 * (i + 1))


def baixar_pncp():
    hoje = dt.date.today()
    todos = []
    print("Consultando o PNCP (CNPJ " + CNPJ + ")...", flush=True)
    for ano in range(ANO_INICIAL, hoje.year + 1):
        ini = dt.date(ano, 1, 1)
        fim = min(dt.date(ano, 12, 31), hoje)
        pagina = 1
        while True:
            resp = get({
                "dataInicial": ini.strftime("%Y%m%d"),
                "dataFinal": fim.strftime("%Y%m%d"),
                "cnpjOrgao": CNPJ,
                "pagina": pagina,
                "tamanhoPagina": TAM_PAGINA,
            })
            itens = resp.get("data") or []
            todos += itens
            total = resp.get("totalPaginas") or 0
            print(f"PNCP {ano}: página {pagina}/{total} ({len(itens)} itens)")
            if pagina >= total or not itens:
                break
            pagina += 1
    return todos


def chave_numero(txt):
    """Extrai (sequencial, ano) de formatos como '2-1023-2025', '1023/2025', '2-1023/2025'."""
    nums = re.findall(r"\d+", txt or "")
    anos = [n for n in nums if len(n) == 4 and 2000 <= int(n) <= 2100]
    if not anos:
        return None
    ano = anos[-1]
    resto = nums[:len(nums) - 1 - nums[::-1].index(ano)]  # números antes do ano
    if not resto:
        return None
    # '2-1023-2025': o primeiro número (1 dígito) é a unidade, o segundo é o sequencial
    seq = resto[1] if len(resto) >= 2 and len(resto[0]) == 1 else resto[-1]
    return int(seq), int(ano)


def simplifica(nome):
    s = "".join(c for c in unicodedata.normalize("NFD", (nome or "").upper())
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(LTDA|EIRELI|ME|EPP|S/?A|S/?S|SS|CIA|COMERCIO|SERVICOS?|DE|DA|DO|DOS|DAS|E)\b", " ", s)
    return set(w for w in re.findall(r"[A-Z0-9]{3,}", s))


def parecido(a, b):
    sa, sb = simplifica(a), simplifica(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= 0.5


def main(src, dest):
    base = json.load(open(src, encoding="utf-8"))
    pncp = baixar_pncp()

    por_chave = {}
    for c in pncp:
        k = chave_numero(c.get("numeroContratoEmpenho"))
        if k:
            por_chave.setdefault(k, []).append(c)

    usados, resultado = set(), {}
    for r in base["vigentes"] + base["encerrados"]:
        if not r.get("seq"):
            continue
        cands = por_chave.get((r["seq"], r["ano"]), [])
        if r.get("doc"):
            fortes = [c for c in cands if re.sub(r"\D", "", c.get("niFornecedor") or "") == r["doc"]]
        else:
            fortes = [c for c in cands if parecido(c.get("nomeRazaoSocialFornecedor"), r["cr"])]
        escolhido = (fortes or cands or [None])[0]
        if not escolhido:
            resultado[r["n"]] = {"st": "ausente"}
            continue
        usados.add(escolhido.get("numeroControlePNCP"))
        v_pncp = escolhido.get("valorGlobal") or escolhido.get("valorInicial")
        fim_pncp = (escolhido.get("dataVigenciaFim") or "")[:10] or None
        obs = []
        if r.get("v") and v_pncp and abs(float(v_pncp) - r["v"]) > max(1.0, 0.01 * r["v"]):
            obs.append("valor diferente")
        if not fortes:
            obs.append("credor não confere")
        resultado[r["n"]] = {
            "st": "divergente" if obs else "ok",
            "obs": ", ".join(obs),
            "ctrl": escolhido.get("numeroControlePNCP"),
            "num": escolhido.get("numeroContratoEmpenho"),
            "v": v_pncp,
            "fim": fim_pncp,
            "forn": escolhido.get("nomeRazaoSocialFornecedor"),
            "url": f"https://pncp.gov.br/app/contratos/{CNPJ}/{escolhido.get('anoContrato')}/{escolhido.get('sequencialContrato')}",
        }

    so_pncp = [{
        "num": c.get("numeroContratoEmpenho"),
        "forn": c.get("nomeRazaoSocialFornecedor"),
        "obj": c.get("objetoContrato"),
        "v": c.get("valorGlobal") or c.get("valorInicial"),
        "ass": (c.get("dataAssinatura") or "")[:10],
        "url": f"https://pncp.gov.br/app/contratos/{CNPJ}/{c.get('anoContrato')}/{c.get('sequencialContrato')}",
    } for c in pncp if c.get("numeroControlePNCP") not in usados]

    out = {
        "verificado_em": dt.datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "cnpj": CNPJ,
        "total_pncp": len(pncp),
        "contratos": resultado,
        "so_pncp": so_pncp,
    }
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    st = {}
    for v in resultado.values():
        st[v["st"]] = st.get(v["st"], 0) + 1
    print("PNCP:", len(pncp), "contratos |", st, "| só no PNCP:", len(so_pncp))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
