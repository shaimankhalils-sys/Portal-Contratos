#!/usr/bin/env python3
"""
Portal de Contratos · lê itens e aditivos no Portal da Transparência (KBF / Webrun).

Uso:  python3 scripts/kbf_itens.py data/contratos.json data/itens.json

Como funciona (com um navegador automático, igual a um visitante):
  1. abre o portal da transparência da Prefeitura (cria a sessão);
  2. abre a tela de Contratos, ajusta o período e lê a grade inteira:
     número do contrato -> código interno (CHAVE), qtd. de aditivos e situação;
  3. para cada contrato VIGENTE da planilha, abre as telas:
       "Itens do Contrato"  (formID 500000540)  -> produto, quantidade, preço unitário, total
       "Detalhes"           (formID 8825)       -> termos aditivos (nº, datas, valor, situação, objetivo)
  4. grava data/itens.json (índice + aditivos), data/itens/<nº>.json (itens de cada contrato)
     e data/kbf_log.txt (relatório da execução).

É incremental: só relê um contrato se ele for novo, se a quantidade de aditivos mudou
ou se a última leitura tem mais de 30 dias. Faz pausas entre as páginas.
"""
import sys, os, re, json, time, traceback, datetime as dt

from playwright.sync_api import sync_playwright

BASE = "https://portaldatransparencia.sistemasonline.net.br/webrun5/"
ENTRADA = BASE + "form.jsp?sys=PTP&action=openform&formID=20&dataConnection=PM_Teixeira_de_Freitas&numerotc=386"
LISTA = BASE + "form.jsp?sys=PTP&action=openform&formID=8522"
ITENS = BASE + "openform.do?sys=PTP&action=openform&formID=500000540&mode=-1&goto=-1&filter=CHAVE={chave}&scrolling=no"
DETALHES = BASE + "openform.do?sys=PTP&action=openform&formID=8825&mode=-1&goto=-1&filter=TRP_TRANSP_CONTRATO_VI.CHAVE={chave}@long&scrolling=yes"

# campos da grade de contratos (formID 8522)
F_NUM, F_CHAVE, F_VALOR, F_QTADT, F_SIT, F_FIM = "field1082885", "field1082884", "field1082891", "field1082894", "field1082889", "field1082900"
# campos da grade de itens (formID 500000540)
I_PROD, I_QTD, I_PER, I_LOTE, I_UNIT, I_TOTAL = "field1086925", "field1086920", "field1086923", "field1086921", "field1086922", "field1086924"
# campos da grade de aditivos (formID 8825)
A_NUM, A_CEL, A_PUB, A_INI, A_FIM, A_VAL, A_SIT, A_OBJ = ("field1086342", "field1086344", "field1086345", "field1086346",
                                                          "field1086347", "field1086348", "field1086349", "field1086343")

PASTA_ITENS = "data/itens"
PAUSA = 0.8          # segundos entre páginas
MAX_POR_EXECUCAO = 1500
RELER_APOS_DIAS = 30

LOG = []


def log(msg):
    linha = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(linha, flush=True)
    LOG.append(linha)


# ---------- leitura dos dados embutidos nas páginas ----------
DATA_RE = re.compile(r"data_(\d+)\s*=\s*\[(.*?)\];", re.S)
ROW_RE = re.compile(r"\{(.*?)\brow:\d+\}", re.S)
FIELD_RE = re.compile(r"'(field\d+)'\s*:\s*('(?:[^'\\]|\\.)*'|-?[\d.]+(?:[eE][-+]?\d+)?|null)")


def _valor_js(v):
    if v == "null":
        return None
    if v.startswith("'"):
        return v[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    try:
        return float(v)
    except ValueError:
        return v


def grades(html):
    """Todas as grades 'data_N = [...]' da página, como listas de dicionários."""
    out = []
    for m in DATA_RE.finditer(html):
        linhas = []
        for row in ROW_RE.finditer(m.group(2)):
            linhas.append({k: _valor_js(v) for k, v in FIELD_RE.findall(row.group(1))})
        out.append(linhas)
    return out


def num_br(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    # texto vem no formato brasileiro: '1.500' = mil e quinhentos, '2,5' = dois e meio
    if "," in s or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def data_iso(v):
    try:
        return dt.datetime.strptime(str(v).strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def limpa(s):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def ler_itens(html):
    for g in grades(html):
        if g and I_PROD in g[0]:
            return [{
                "prod": limpa(r.get(I_PROD)),
                "qtd": num_br(r.get(I_QTD)),
                "per": num_br(r.get(I_PER)),
                "lote": limpa(r.get(I_LOTE)),
                "unit": num_br(r.get(I_UNIT)),
                "total": round(num_br(r.get(I_TOTAL)) or 0, 2),
            } for r in g]
    return []


def ler_aditivos(html):
    for g in grades(html):
        if g and A_NUM in g[0]:
            return [{
                "n": limpa(r.get(A_NUM)),
                "cel": data_iso(r.get(A_CEL)),
                "pub": data_iso(r.get(A_PUB)),
                "ini": data_iso(r.get(A_INI)),
                "fim": data_iso(r.get(A_FIM)),
                "v": num_br(r.get(A_VAL)),
                "sit": limpa(r.get(A_SIT)),
                "obj": limpa(r.get(A_OBJ))[:600],
            } for r in g]
    return []


# ---------- navegação ----------
def diagnostico(page, onde):
    """Registra no log o que o navegador está vendo (para investigar falhas)."""
    try:
        log(f"Diagnóstico ({onde}): título='{page.title()}' url={page.url.split('?')[0]}")
        for f in page.frames:
            u = f.url.split("?")[0]
            q = f.url.split("formID=")[1].split("&")[0] if "formID=" in f.url else ""
            log(f"  frame {u} formID={q}")
        txt = page.inner_text("body")[:400].replace("\n", " ")
        log(f"  texto: {txt}")
        page.screenshot(path="data/kbf_debug.png", full_page=True)
    except Exception as e:
        log(f"  (diagnóstico falhou: {e})")


def frame_da_lista(page):
    for _ in range(40):
        for f in page.frames:
            try:
                if f.query_selector("#WFRInput1082838"):
                    return f
            except Exception:
                pass
        time.sleep(0.5)
    diagnostico(page, "tela de contratos")
    raise RuntimeError("Tela de contratos não encontrada (o portal pode ter mudado).")


def listar_contratos(page, inicio):
    log(f"Abrindo a lista de contratos a partir de {inicio}...")
    page.goto(LISTA, wait_until="load", timeout=120_000)
    f = frame_da_lista(page)
    f.wait_for_function("() => window.isc && isc.Canvas._canvasList.some(c => c.ID === 'CONTRATOS')", timeout=120_000)
    campo = f.locator("#WFRInput1082838")
    campo.click(click_count=3)
    campo.type(inicio, delay=40)
    campo.press("Tab")
    # espera a grade recarregar com o novo período
    f.wait_for_function(
        """(ini) => { const g = isc.Canvas._canvasList.find(c => c.ID === 'CONTRATOS');
                     const d = document.getElementById('WFRInput1082838');
                     return d && d.value === ini && g && g.getTotalRows() > 50 && g.data.allMatchingRowsCached(); }""",
        arg=inicio, timeout=600_000, polling=2000)
    time.sleep(3)
    linhas = f.evaluate(f"""() => {{
        const g = isc.Canvas._canvasList.find(c => c.ID === 'CONTRATOS');
        const out = [];
        for (let i = 0; i < g.getTotalRows(); i++) {{
            const r = g.getRecord(i); if (!r) continue;
            out.push([String(r['{F_NUM}'] || ''), String(r['{F_CHAVE}'] || ''), r['{F_VALOR}'],
                      String(r['{F_QTADT}'] || '0'), String(r['{F_SIT}'] || ''), String(r['{F_FIM}'] || '')]);
        }}
        return out; }}""")
    log(f"Lista lida: {len(linhas)} contratos no portal.")
    return linhas


def main(src, dest):
    base = json.load(open(src, encoding="utf-8"))
    vigentes = {r["n"]: r for r in base["vigentes"]}
    antigo = json.load(open(dest, encoding="utf-8")) if os.path.exists(dest) else {}
    indice = antigo.get("indice", {})
    contratos = antigo.get("contratos", {})
    hoje = dt.date.today()

    completo = not indice or hoje.weekday() == 6 or os.environ.get("KBF_COMPLETO") == "1"
    inicio = "01/01/2021" if completo else (hoje - dt.timedelta(days=150)).strftime("%d/%m/%Y")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="pt-BR", user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
            "PortalContratos-TX"))
        page = ctx.new_page()
        log("Abrindo o portal da transparência...")
        page.goto(ENTRADA, wait_until="load", timeout=120_000)
        time.sleep(3)

        try:
            lista = listar_contratos(page, inicio)
        except Exception:
            diagnostico(page, "lista")
            raise
        for n, chave, valor, qtadt, sit, fim in lista:
            n = n.strip()
            if n and chave:
                indice[n] = {"chave": chave, "adt": int(float(qtadt or 0)), "v": num_br(valor),
                             "sit": sit, "fim": data_iso(fim)}

        # quais vigentes precisam ser lidos
        fila, sem_chave = [], []
        for n in vigentes:
            ix = indice.get(n)
            if not ix:
                sem_chave.append(n)
                continue
            atual = contratos.get(n)
            velho = not atual or not atual.get("lido") or \
                (hoje - dt.date.fromisoformat(atual["lido"][:10])).days >= RELER_APOS_DIAS
            if velho or atual.get("adt") != ix["adt"] or atual.get("chave") != ix["chave"]:
                fila.append(n)
        fila.sort(key=lambda n: (n in contratos, n))  # novos primeiro
        fila = fila[:MAX_POR_EXECUCAO]
        log(f"Vigentes: {len(vigentes)} | sem correspondência no portal: {len(sem_chave)} | a ler agora: {len(fila)}")

        req = ctx.request
        erros = 0
        for i, n in enumerate(fila, 1):
            ix = indice[n]
            try:
                h_it = req.get(ITENS.format(chave=ix["chave"]), timeout=60_000).body().decode("cp1252", "replace")
                time.sleep(PAUSA)
                h_ad = req.get(DETALHES.format(chave=ix["chave"]), timeout=60_000).body().decode("cp1252", "replace")
                time.sleep(PAUSA)
                if "setGridPageIni" not in h_it:
                    raise RuntimeError("página de itens veio sem dados (sessão expirada?)")
                itens = ler_itens(h_it)
                os.makedirs(PASTA_ITENS, exist_ok=True)
                with open(os.path.join(PASTA_ITENS, n + ".json"), "w", encoding="utf-8") as fh:
                    json.dump(itens, fh, ensure_ascii=False, separators=(",", ":"))
                contratos[n] = {"chave": ix["chave"], "adt": ix["adt"], "lido": dt.datetime.now().isoformat(timespec="minutes"),
                                "qi": len(itens), "ti": round(sum(x["total"] or 0 for x in itens), 2),
                                "aditivos": ler_aditivos(h_ad)}
            except Exception as e:
                erros += 1
                log(f"  erro em {n}: {e}")
                if erros >= 25:
                    log("Muitos erros seguidos; parando para não sobrecarregar o portal.")
                    break
                if "sessão" in str(e):
                    page.goto(ENTRADA, wait_until="load", timeout=120_000)
                    time.sleep(3)
            if i % 50 == 0:
                log(f"  {i}/{len(fila)} lidos")
        browser.close()

    com_itens = sum(1 for c in contratos.values() if c.get("qi"))
    log(f"Concluído. Contratos com itens: {com_itens} | erros: {erros}")
    json.dump({"atualizado_em": dt.datetime.now().isoformat(timespec="minutes"), "lista_completa": completo,
               "sem_correspondencia": sorted(sem_chave), "indice": indice, "contratos": contratos},
              open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    try:
        main(sys.argv[1], sys.argv[2])
    except Exception:
        log("FALHA:\n" + traceback.format_exc())
        raise
    finally:
        os.makedirs("data", exist_ok=True)
        with open("data/kbf_log.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(LOG) + "\n")
