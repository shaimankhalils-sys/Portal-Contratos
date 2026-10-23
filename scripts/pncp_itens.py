#!/usr/bin/env python3
"""
Portal de Contratos · itens e termos aditivos de cada contrato, lidos do PNCP.

Uso:  python3 scripts/pncp_itens.py data/contratos.json data/pncp.json data/itens.json

Para cada contrato VIGENTE que foi encontrado no PNCP (data/pncp.json):
  - itens: abre a contratação de origem (licitação/dispensa) e pega os itens que o
    fornecedor do contrato venceu, com quantidade, unidade, preço unitário e total homologados;
  - aditivos: lê os termos do contrato (reajuste, acréscimo/supressão, prazo, valor acrescido).

Gera:
  data/itens.json            índice: por contrato, nº de itens, soma, aditivos, se é registro de preço
  data/itens/<nº>.json       os itens de cada contrato (carregados pelo site só ao abrir a ficha)
  data/pncp_compras/*.json   memória das contratações já lidas (evita reler o que não muda)
"""
import sys, os, re, json, time, datetime as dt
import urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor

API = "https://pncp.gov.br/api/pncp/v1/orgaos"
PASTA_ITENS = "data/itens"
PASTA_COMPRAS = "data/pncp_compras"
RELER_COMPRA_DIAS = 30      # contratações já lidas são relidas depois desse prazo
RELER_TERMOS_DIAS = 3       # termos aditivos mudam mais; relê com mais frequência
LIMITE_MINUTOS = 50         # para com segurança e continua na próxima execução
TRABALHADORES = 4           # requisições simultâneas ao PNCP (moderado)

INICIO = time.time()
LOG = []


def log(msg):
    linha = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(linha, flush=True)
    LOG.append(linha)


def tempo_ok():
    return (time.time() - INICIO) / 60 < LIMITE_MINUTOS


REDIR_VISTO = set()


def get(url, tentativas=4):
    """GET com JSON, seguindo redirecionamentos (o PNCP responde 301 em alguns endereços)."""
    for i in range(tentativas):
        alvo = url
        try:
            for _ in range(6):  # segue até 5 redirecionamentos
                req = urllib.request.Request(alvo, headers={"Accept": "application/json", "User-Agent": "portal-contratos-tx/1.0"})
                try:
                    with urllib.request.urlopen(req, timeout=40) as r:
                        if r.status == 204:
                            return []
                        corpo = r.read()
                        return json.loads(corpo.decode("utf-8")) if corpo else []
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                        novo = urllib.parse.urljoin(alvo, e.headers["Location"])
                        chave = re.sub(r"\d+", "N", urllib.parse.urlparse(alvo).path) + " -> " + re.sub(r"\d+", "N", urllib.parse.urlparse(novo).path)
                        if chave not in REDIR_VISTO and len(REDIR_VISTO) < 5:
                            REDIR_VISTO.add(chave)
                            log(f"  redirecionamento: {chave}")
                        alvo = novo
                        continue
                    raise
            raise RuntimeError("redirecionamentos demais")
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return []
            if 400 <= e.code < 500 or i == tentativas - 1:
                raise  # erro do pedido: não adianta repetir
        except Exception:
            if i == tentativas - 1:
                raise
        time.sleep(2 * (i + 1))


def partes_compra(ctrl):
    """'13650403000128-1-000385/2025' -> ('13650403000128', '2025', '385')"""
    m = re.match(r"^(\d{14})-\d+-0*(\d+)/(\d{4})$", ctrl or "")
    return (m.group(1), m.group(3), m.group(2)) if m else None


def ler_compra(ctrl):
    """Itens e resultados (vencedores) de uma contratação, com cache em disco."""
    caminho = os.path.join(PASTA_COMPRAS, re.sub(r"[^\w-]", "_", ctrl) + ".json")
    if os.path.exists(caminho):
        c = json.load(open(caminho, encoding="utf-8"))
        if (dt.date.today() - dt.date.fromisoformat(c["lido"][:10])).days < RELER_COMPRA_DIAS:
            return c
    cnpj, ano, seq = partes_compra(ctrl)
    base = f"{API}/{cnpj}/compras/{ano}/{seq}"
    info = get(base) or {}
    itens, pagina = [], 1
    while True:
        lote = get(f"{base}/itens?pagina={pagina}&tamanhoPagina=100") or []
        itens += lote
        if len(lote) < 100:
            break
        pagina += 1

    def resultados(it):
        if it.get("temResultado") is False:
            return it, []
        return it, get(f"{base}/itens/{it['numeroItem']}/resultados") or []

    with ThreadPoolExecutor(TRABALHADORES) as ex:
        pares = list(ex.map(resultados, itens))
    c = {
        "lido": dt.datetime.now().isoformat(timespec="minutes"),
        "srp": bool(info.get("srp")),
        "modalidade": info.get("modalidadeNome"),
        "numero": info.get("numeroCompra"),
        "itens": [{
            "n": it.get("numeroItem"),
            "desc": (it.get("descricao") or "").strip(),
            "un": it.get("unidadeMedida"),
            "tipo": it.get("materialOuServicoNome"),
            "venc": [{
                "ni": re.sub(r"\D", "", r.get("niFornecedor") or ""),
                "q": r.get("quantidadeHomologada"),
                "u": r.get("valorUnitarioHomologado"),
                "t": r.get("valorTotalHomologado"),
            } for r in res if r.get("situacaoCompraItemResultadoId") != 2],  # 2 = resultado cancelado
        } for it, res in pares],
    }
    os.makedirs(PASTA_COMPRAS, exist_ok=True)
    json.dump(c, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return c


def tipo_termo(t):
    obj = t.get("objetoTermoContrato") or ""
    v = t.get("valorAcrescido") or 0
    if re.search(r"reequil|equil[íi]brio econ", obj, re.I):
        return "reequilibrio"
    if re.search(r"repactu", obj, re.I):
        return "repactuacao"
    if t.get("qualificacaoReajuste"):
        return "reajuste"
    if t.get("qualificacaoAcrescimoSupressao"):
        return "supressao" if v < 0 else "acrescimo"
    if t.get("qualificacaoVigencia"):
        return "prazo"
    return "outro"


def ler_termos(cnpj, ano, seq):
    termos = get(f"{API}/{cnpj}/contratos/{ano}/{seq}/termos") or []
    out = []
    for t in termos:
        out.append({
            "n": t.get("numeroTermoContrato") or f"{t.get('sequencialTermoContrato')}º termo",
            "cel": (t.get("dataAssinatura") or "")[:10] or None,
            "ini": (t.get("dataVigenciaInicio") or "")[:10] or None,
            "fim": (t.get("dataVigenciaFim") or "")[:10] or None,
            "v": t.get("valorAcrescido") or 0,
            "vg": t.get("valorGlobal"),
            "dias": t.get("prazoAditadoDias") or 0,
            "tipo": tipo_termo(t),
            "flags": [k for k, f in (("reajuste", "qualificacaoReajuste"), ("acréscimo/supressão", "qualificacaoAcrescimoSupressao"),
                                     ("vigência", "qualificacaoVigencia"), ("fornecedor", "qualificacaoFornecedor")) if t.get(f)],
            "obj": (t.get("objetoTermoContrato") or "").strip()[:600],
            "sit": "",
            "fonte": "PNCP",
        })
    return sorted(out, key=lambda a: a["cel"] or "")


def main(src_contratos, src_pncp, dest):
    base = json.load(open(src_contratos, encoding="utf-8"))
    pncp = json.load(open(src_pncp, encoding="utf-8"))
    antigo = json.load(open(dest, encoding="utf-8")) if os.path.exists(dest) else {}
    contratos = {n: c for n, c in antigo.get("contratos", {}).items() if c.get("fonte") == "PNCP"}
    hoje = dt.date.today()

    fila = []
    for r in base["vigentes"]:
        p = pncp.get("contratos", {}).get(r["n"])
        if not p or p.get("st") not in ("ok", "divergente") or not p.get("seq"):
            continue
        atual = contratos.get(r["n"])
        if atual and (hoje - dt.date.fromisoformat(atual["lido"][:10])).days < RELER_TERMOS_DIAS \
                and atual.get("compra") == p.get("compra"):
            continue
        fila.append((r, p))
    fila.sort(key=lambda x: x[0]["n"] in contratos)  # novos primeiro
    log(f"Contratos vigentes no PNCP a ler agora: {len(fila)}")

    cnpj_orgao = pncp.get("cnpj", "13650403000128")
    lidos = sem_compra = erros = 0
    for i, (r, p) in enumerate(fila, 1):
        if not tempo_ok():
            log("Limite de tempo atingido; o restante fica para a próxima execução.")
            break
        try:
            itens, srp, compra_num = [], False, None
            if partes_compra(p.get("compra")):
                c = ler_compra(p["compra"])
                srp, compra_num = c["srp"], c.get("numero")
                for it in c["itens"]:
                    for v in it["venc"]:
                        if p.get("ni") and v["ni"] == p["ni"]:
                            itens.append({"prod": f"{it['n']} - {it['desc']}", "un": it["un"], "qtd": v["q"],
                                          "unit": v["u"], "total": round(v["t"] or 0, 2), "lote": ""})
            else:
                sem_compra += 1
            aditivos = ler_termos(cnpj_orgao, p["ano"], p["seq"])
            os.makedirs(PASTA_ITENS, exist_ok=True)
            json.dump(itens, open(os.path.join(PASTA_ITENS, r["n"] + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
            contratos[r["n"]] = {
                "fonte": "PNCP", "compra": p.get("compra"), "compra_num": compra_num, "srp": srp,
                "lido": dt.datetime.now().isoformat(timespec="minutes"),
                "qi": len(itens), "ti": round(sum(x["total"] or 0 for x in itens), 2),
                "adt": len(aditivos), "aditivos": aditivos,
            }
            lidos += 1
        except Exception as e:
            erros += 1
            if erros <= 15:
                import traceback
                log(f"  erro em {r['n']} (compra {p.get('compra')}): {type(e).__name__}: {e}")
                if erros <= 2:
                    log(traceback.format_exc())
        if i >= 15 and lidos == 0:
            log("Os 15 primeiros contratos falharam; parando para investigar.")
            break
        if i % 25 == 0:
            log(f"  {i}/{len(fila)} contratos")

    # remove contratos que deixaram de ser vigentes
    vig = {r["n"] for r in base["vigentes"]}
    contratos = {n: c for n, c in contratos.items() if n in vig}
    json.dump({"atualizado_em": dt.datetime.now().isoformat(timespec="minutes"), "fonte": "PNCP",
               "contratos": contratos},
              open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    com = sum(1 for c in contratos.values() if c["qi"])
    log(f"Lidos agora: {lidos} | erros: {erros} | sem contratação vinculada: {sem_compra} | "
        f"contratos com itens: {com} de {len(contratos)} | termos aditivos: {sum(c['adt'] for c in contratos.values())}")


if __name__ == "__main__":
    try:
        main(sys.argv[1], sys.argv[2], sys.argv[3])
    finally:
        with open("data/itens_log.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
