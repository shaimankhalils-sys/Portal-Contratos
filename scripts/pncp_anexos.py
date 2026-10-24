#!/usr/bin/env python3
"""
Portal de Contratos · itens que constam nos PDFs (contrato e termos aditivos) publicados no PNCP.

Uso:  python3 scripts/pncp_anexos.py data/itens.json

Roda depois de pncp_itens.py. Para cada contrato vigente com endereço no PNCP:
  - termos aditivos: baixa o PDF de cada termo e lê o "ANEXO I - ITENS DO ADITIVO";
    os itens acrescidos ficam no próprio aditivo (data/itens.json -> aditivos[].itens);
  - contrato: lê o "ANEXO I - ITENS DO CONTRATO" do PDF do contrato. Quando a soma confere
    com o valor do contrato, esses itens substituem os da contratação (útil no registro de
    preços, em que a contratação mostra a quantidade da ata e não a do contrato).

Os PDFs não são guardados no repositório: só os itens lidos e o endereço do PDF no PNCP.
Memória em data/pncp_anexos/<ano>-<seq>.json (um PDF já lido não é baixado de novo).
"""
import sys, os, re, io, json, time, unicodedata, datetime as dt
import urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anexo_itens import ler_anexo, ler_tabelas, recorta, filtra_tabelas  # noqa: E402

API = "https://pncp.gov.br/api/pncp/v1/orgaos"
CNPJ = "13650403000128"
PASTA = "data/pncp_anexos"
PASTA_ITENS = "data/itens"
LIMITE_MINUTOS = 40
MAX_BYTES = 25 * 1024 * 1024
RELER_SEM_PDF_DIAS = 7
VERSAO = 2                  # versão do leitor; ao mudar, as tabelas guardadas são relidas      # contrato/termo sem PDF publicado: procura de novo depois desse prazo

INICIO = time.time()
LOG = []


def log(msg):
    linha = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(linha, flush=True)
    LOG.append(linha)


def tempo_ok():
    return (time.time() - INICIO) / 60 < LIMITE_MINUTOS


def baixar(url, json_=True, tentativas=3):
    for i in range(tentativas):
        alvo = url
        try:
            for _ in range(6):
                req = urllib.request.Request(alvo, headers={
                    "Accept": "application/json" if json_ else "application/pdf,*/*",
                    "User-Agent": "portal-contratos-tx/1.0"})
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        corpo = r.read(MAX_BYTES + 1)
                        if not json_:
                            return corpo, r.headers.get("Content-Type", "")
                        return json.loads(corpo.decode("utf-8")) if corpo else []
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                        alvo = urllib.parse.urljoin(alvo, e.headers["Location"])
                        continue
                    raise
            raise RuntimeError("redirecionamentos demais")
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return ([] if json_ else (None, ""))
            if 400 <= e.code < 500 or i == tentativas - 1:
                raise
        except Exception:
            if i == tentativas - 1:
                raise
        time.sleep(3 * (i + 1))


def texto_pdf(dados, tabelas=None):
    """Texto do PDF; se 'tabelas' for uma lista, recebe também as tabelas com bordas (das páginas com itens)."""
    import pdfplumber
    partes = []
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        achou = False
        for pg in pdf.pages:
            t = pg.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
            partes.append(t)
            if tabelas is not None:
                achou = achou or bool(re.search(r"ITENS\s+D[OA]|ITEM\s+DESCRI|VLR\.?\s*TOTAL|VALOR\s+TOTAL", t, re.I))
                if achou:
                    try:
                        tabelas.extend(pg.extract_tables())
                    except Exception:
                        pass
    return "\n".join(partes)


def melhor_leitura(dados=None, anexo=None, tabs=None):
    """Compara a leitura pelas células da tabela e pelo texto; fica com a que confere com o total.
    Aceita o PDF (dados) ou o trecho já guardado (anexo + tabs)."""
    if dados is not None:
        tabs = []
        txt = texto_pdf(dados, tabs)
        tabs = filtra_tabelas(tabs)
        anexo = recorta(txt)
    else:
        txt = anexo or ""
    por_texto, total = ler_anexo(anexo or "")
    por_tabela = ler_tabelas(tabs or [])
    def nota(its):
        if not its:
            return -1
        soma = sum(x["total"] or 0 for x in its)
        ok_total = 2 if total and abs(soma - total) <= max(1, total * 0.01) else 0
        ok_q = sum(1 for x in its if x["qtd"] and x["unit"] and abs(x["qtd"] * x["unit"] - x["total"]) <= max(0.05, x["total"] * 0.005))
        return ok_total + ok_q / len(its)
    its = por_tabela if nota(por_tabela) >= nota(por_texto) and por_tabela else por_texto
    return txt, its, total, anexo, tabs


def documentos(base):
    """Lista de arquivos de um contrato ou termo: [(titulo, url_pdf, tipo)]"""
    lista = baixar(f"{base}/arquivos") or []
    if isinstance(lista, dict):
        lista = lista.get("data") or [lista]
    out = []
    for a in lista:
        if not isinstance(a, dict) or a.get("statusAtivo") is False:
            continue
        url = a.get("url") or a.get("uri")
        if not url and a.get("sequencialDocumento"):
            url = f"{base}/arquivos/{a['sequencialDocumento']}"
        if url:
            out.append(((a.get("titulo") or "").strip(), url, a.get("tipoDocumentoNome") or a.get("tipoDocumentoDescricao") or ""))
    return out


def ler_documentos(base):
    """Abre os PDFs do contrato/termo e devolve o primeiro que tiver tabela de itens."""
    docs = documentos(base)
    if not docs:
        return {"st": "sem_pdf", "lido": hoje_iso()}
    tentativas = []
    for titulo, url, tipo in docs:
        if not tempo_ok():
            raise TimeoutError
        dados, ctype = baixar(url, json_=False)
        if not dados or len(dados) > MAX_BYTES or not dados[:5].startswith(b"%PDF"):
            tentativas.append(f"{titulo or url}: não é PDF ou muito grande")
            continue
        try:
            txt, itens, total, anexo, tabs = melhor_leitura(dados)
        except Exception as e:
            tentativas.append(f"{titulo}: erro ao ler PDF ({type(e).__name__})")
            continue
        if itens or anexo:  # guarda o trecho da tabela (sem o restante do documento) para reler sem baixar
            reg = {"st": "ok" if itens else "sem_itens", "lido": hoje_iso(), "v": VERSAO, "pdf": url, "titulo": titulo,
                   "itens": itens, "total_doc": total, "anexo": anexo[:60000], "tabs": tabs[:20]}
            if not itens:
                reg["obs"] = [f"{titulo}: tabela de itens não reconhecida | trecho: {re.sub(chr(10), ' ', anexo[:260])}"]
            return reg
        if len(txt.strip()) < 200:
            tentativas.append(f"{titulo}: PDF sem texto (digitalizado)")
        else:
            m = re.search(r"ITENS\s+D[OA]|ITEM\s+DESCRI", txt, re.I)
            trecho = re.sub(r"\s+", " ", txt[m.start():m.start() + 260]) if m else ""
            tentativas.append(f"{titulo}: tabela de itens não reconhecida" +
                              (f" | trecho: {trecho}" if m else " (sem anexo de itens)"))
    return {"st": "sem_itens", "lido": hoje_iso(), "v": VERSAO, "pdf": docs[0][1], "obs": tentativas[:3]}


def precisa_ler(reg):
    """None = nada a fazer; 'reler' = reprocessar o trecho guardado; 'baixar' = baixar o PDF."""
    if not reg:
        return "baixar"
    if reg.get("v", 1) < VERSAO:
        return "reler" if reg.get("anexo") else "baixar"
    if reg["st"] != "ok" and velho(reg, RELER_SEM_PDF_DIAS):
        return "baixar"
    return None


def reler(reg):
    _, itens, total, _, _ = melhor_leitura(anexo=reg.get("anexo"), tabs=reg.get("tabs"))
    reg.update({"st": "ok" if itens else "sem_itens", "v": VERSAO, "itens": itens, "total_doc": total})
    return reg


def hoje_iso():
    return dt.date.today().isoformat()


def velho(reg, dias):
    try:
        return (dt.date.today() - dt.date.fromisoformat(reg["lido"][:10])).days >= dias
    except Exception:
        return True


def simplifica(s):
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").upper()) if unicodedata.category(c) != "Mn")
    s = re.sub(r"^\s*\d{1,3}\s*-\s*", "", s)          # "12 - " (nº do item na contratação)
    s = re.sub(r"^\s*\d{7,12}\s*[-–—:]?\s*", "", s)   # código do produto
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def casa_item(it, base):
    """Item do aditivo -> item do contrato (por código ou descrição)."""
    if it.get("cod"):
        for b in base:
            if it["cod"] in (b.get("prod") or ""):
                return b
    alvo = simplifica(it.get("prod"))[:45]
    if len(alvo) < 8:
        return None
    for b in base:
        sb = simplifica(b.get("prod"))
        if sb[:45] == alvo or (len(alvo) >= 20 and alvo[:30] in sb):
            return b
    return None


def main(dest):
    idx = json.load(open(dest, encoding="utf-8"))
    contratos = idx.get("contratos", {})
    os.makedirs(PASTA, exist_ok=True)
    fila = [(n, c) for n, c in contratos.items() if c.get("pncp_seq")]
    log(f"Contratos vigentes com endereço no PNCP: {len(fila)}")
    lidos_pdf = com_itens_ad = com_itens_ct = erros = 0
    interrompido = False

    for n, c in fila:
        ano, seq = c["pncp_ano"], c["pncp_seq"]
        cam = os.path.join(PASTA, f"{ano}-{seq}.json")
        mem = json.load(open(cam, encoding="utf-8")) if os.path.exists(cam) else {"termos": {}}
        mudou = False
        base_ct = f"{API}/{CNPJ}/contratos/{ano}/{seq}"
        try:
            # contrato
            reg = mem.get("contrato")
            acao = precisa_ler(reg)
            if acao == "reler":
                mem["contrato"] = reler(reg); mudou = True
            elif acao and not interrompido:
                if not tempo_ok():
                    raise TimeoutError
                mem["contrato"] = ler_documentos(base_ct)
                lidos_pdf += 1
                mudou = True
            # termos aditivos (leituras antigas não têm o sequencial do termo: busca na lista de termos)
            if not interrompido and any(not a.get("seqt") for a in c.get("aditivos", [])):
                seqs = {(t.get("numeroTermoContrato") or ""): t.get("sequencialTermoContrato")
                        for t in (baixar(f"{base_ct}/termos") or []) if isinstance(t, dict)}
                for a in c.get("aditivos", []):
                    a["seqt"] = a.get("seqt") or seqs.get(a.get("n"))
            for a in c.get("aditivos", []):
                st = a.get("seqt")
                if not st:
                    continue
                reg = mem["termos"].get(str(st))
                acao = precisa_ler(reg)
                if acao == "reler":
                    mem["termos"][str(st)] = reler(reg); mudou = True
                elif acao and not interrompido:
                    if not tempo_ok():
                        raise TimeoutError
                    mem["termos"][str(st)] = ler_documentos(f"{base_ct}/termos/{st}")
                    lidos_pdf += 1
                    mudou = True
        except TimeoutError:
            if not interrompido:
                log("Limite de tempo atingido; o restante fica para a próxima execução.")
            interrompido = True
        except Exception as e:
            erros += 1
            if erros <= 10:
                log(f"  erro em {n} ({ano}/{seq}): {type(e).__name__}: {e}")
        if mudou:
            mem["contrato_n"] = n
            json.dump(mem, open(cam, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

        # ---- aplica ao índice ----
        ct = mem.get("contrato") or {}
        c["pdf"] = ct.get("pdf")
        itens_cam = os.path.join(PASTA_ITENS, n + ".json")
        itens_atuais = json.load(open(itens_cam, encoding="utf-8")) if os.path.exists(itens_cam) else []
        if ct.get("st") == "ok":
            pdf_itens = [{"prod": (f"{x['n']} - " if x.get("n") else "") + x["prod"], "un": x["un"], "qtd": x["qtd"],
                          "unit": x["unit"], "total": x["total"], "lote": "", "marca": x.get("marca", "")}
                         for x in ct["itens"]]
            soma = round(sum(x["total"] or 0 for x in pdf_itens), 2)
            alvo = ct.get("total_doc") or soma
            confere = alvo and abs(soma - alvo) <= max(1, alvo * 0.01)
            if confere:  # o PDF do contrato é a fonte mais fiel (quantidade contratada, marca)
                json.dump(pdf_itens, open(itens_cam, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                c["fonte_itens"], c["qi"], c["ti"] = "PDF do contrato", len(pdf_itens), soma
                itens_atuais = pdf_itens
                com_itens_ct += 1
        for a in c.get("aditivos", []):
            reg = mem["termos"].get(str(a.get("seqt"))) or {}
            a.pop("itens", None)
            a["pdf"] = reg.get("pdf")
            if reg.get("st") == "ok":
                its = []
                for x in reg["itens"]:
                    o = casa_item(x, itens_atuais)
                    its.append({"prod": x["prod"], "un": x["un"], "qtd": x["qtd"], "unit": x["unit"], "total": x["total"],
                                "q0": o.get("qtd") if o else None, "u0": o.get("unit") if o else None})
                a["itens"] = its
                a["ti"] = round(sum(x["total"] or 0 for x in its), 2)
                com_itens_ad += 1

    json.dump(idx, open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    sem = [(n, a["n"], a.get("tipo")) for n, c in contratos.items() for a in c.get("aditivos", [])
           if a.get("tipo") in ("acrescimo", "supressao") and not a.get("itens")]
    log(f"PDFs lidos agora: {lidos_pdf} | erros: {erros} | contratos com itens do PDF: {com_itens_ct} | "
        f"aditivos com itens: {com_itens_ad} | acréscimos/supressões ainda sem itens: {len(sem)}")
    # motivos (para ajustar a leitura)
    for n, c in list(contratos.items()):
        if not c.get("pncp_seq"):
            continue
        cam = os.path.join(PASTA, f"{c['pncp_ano']}-{c['pncp_seq']}.json")
        if not os.path.exists(cam):
            continue
        mem = json.load(open(cam, encoding="utf-8"))
        for a in c.get("aditivos", []):
            reg = mem["termos"].get(str(a.get("seqt"))) or {}
            if a.get("tipo") in ("acrescimo", "supressao") and reg.get("st") == "sem_itens":
                log(f"  {a['n']} ({n}): " + " || ".join(reg.get("obs") or []))


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    finally:
        with open("data/anexos_log.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
