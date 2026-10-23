#!/usr/bin/env python3
"""Gera um único HTML com dados e logo embutidos (para abrir sem servidor)."""
import sys, os, base64
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
html = rd("index.html")
data = rd("data", "contratos.json")
pn_path = os.path.join(root, "data", "pncp.json")
pncp = rd("data", "pncp.json") if os.path.exists(pn_path) else '{"contratos":{},"so_pncp":[]}'


def uri(name):
    path = os.path.join(root, "assets", name)
    if not os.path.exists(path):
        return None
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


html = html.replace('src="assets/logo.png"', f'src="{uri("logo.png")}"')
mn_path = os.path.join(root, "data", "minutas.json")
minutas = rd("data", "minutas.json") if os.path.exists(mn_path) else '{"docs":{}}'
inject = ("<script>window.__CTX_DATA__=" + data.replace("</", "<\\/") + ";"
          "window.__CTX_MIN__=" + minutas.replace("</", "<\\/") + ";"
          "window.__CTX_PNCP__=" + pncp.replace("</", "<\\/") + ";</script>\n")
out = html.replace("<script>\n(() => {", inject + "<script>\n(() => {", 1)
open(sys.argv[1], "w", encoding="utf-8").write(out)
print("ok", sys.argv[1], len(out))
