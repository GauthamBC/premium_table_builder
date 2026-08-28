import base64
import hmac
import html
import io
import os
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Branded Table Studio", page_icon="▦", layout="wide")

st.markdown("""
<style>
.stApp{background:linear-gradient(180deg,#f8f9fb,#f2f4f7);color:#15181c}
.block-container{max-width:1480px;padding-top:2rem;padding-bottom:4rem}
h1,h2,h3{letter-spacing:-.035em}
div[data-testid="stVerticalBlockBorderWrapper"]{background:rgba(255,255,255,.9);border-color:#e1e5e9!important;box-shadow:0 12px 30px rgba(15,23,42,.04)}
.stButton>button,.stDownloadButton>button{min-height:44px;border-radius:10px;font-weight:750}
.studio-head{padding:0 0 22px;margin-bottom:20px;border-bottom:1px solid #dfe3e8}
.studio-eye{font-size:12px;font-weight:850;letter-spacing:.12em;text-transform:uppercase;color:#6b7280;margin-bottom:8px}
.studio-title{font-size:clamp(36px,4.4vw,62px);line-height:.98;letter-spacing:-.05em;margin:0;color:#111418}
.studio-sub{max-width:760px;font-size:16px;line-height:1.55;color:#69717d;margin:12px 0 0}
.note{padding:12px 14px;border:1px solid #dfe7e1;border-left:4px solid #56C257;background:#fbfffc;color:#374151;font-size:13px}
</style>
""", unsafe_allow_html=True)


def secret(name):
    try:
        v = str(st.secrets.get(name, "") or "")
    except Exception:
        v = ""
    return (v or os.getenv(name, "") or "").strip()


def require_access():
    expected_pass = secret("APP_PASSWORD")
    expected_word = secret("APP_KEYWORD")
    if not expected_pass or not expected_word:
        st.error("Configure APP_PASSWORD and APP_KEYWORD in Streamlit secrets before using this app.")
        st.code('APP_PASSWORD = "your-private-password"\nAPP_KEYWORD = "your-private-keyword"', language="toml")
        st.stop()
    if st.session_state.get("auth_ok"):
        return
    st.markdown('<div class="studio-head"><div class="studio-eye">Private internal tool</div><h1 class="studio-title">Branded Table Studio</h1><p class="studio-sub">Unlock the studio to turn a CSV into a polished standalone interactive HTML table.</p></div>', unsafe_allow_html=True)
    with st.form("login"):
        p = st.text_input("Password", type="password")
        k = st.text_input("Keyword", type="password")
        go = st.form_submit_button("Unlock studio", use_container_width=True)
    if go:
        if hmac.compare_digest(p, expected_pass) and hmac.compare_digest(k.lower().strip(), expected_word.lower().strip()):
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Password or keyword is incorrect.")
    st.stop()


require_access()

BRANDS = {
    "Action Network": {"logo":"https://i.postimg.cc/x1nG117r/AN-final2-logo.png","accent":"#56C257","dark":"#2E8538","tint":"#F3FCF5","stripe":"#F6FFF9","rgb":(86,194,87)},
    "VegasInsider": {"logo":"https://i.postimg.cc/VkynWsGQ/VI-logo-Dark.png","accent":"#F2C23A","dark":"#B9851A","tint":"#FFF8E3","stripe":"#FFF7DC","rgb":(242,194,58)},
    "Canada Sports Betting": {"logo":"https://i.postimg.cc/25nqwgcw/csb-text-all-red.png","accent":"#DC2626","dark":"#991B1B","tint":"#FFF1F1","stripe":"#FEF2F2","rgb":(220,38,38)},
    "RotoGrinders": {"logo":"https://i.postimg.cc/PrcJnQtK/RG-logo-Fn.png","accent":"#2F7DF3","dark":"#0141A1","tint":"#F0F6FF","stripe":"#F5F8FF","rgb":(47,125,243)},
    "AceOdds": {"logo":"https://i.postimg.cc/RVhccmQc/aceodds-logo-original-1.png","accent":"#364464","dark":"#242E45","tint":"#F4F6FA","stripe":"#F7F8FA","rgb":(54,68,100)},
    "BOLAVIP": {"logo":"https://i.postimg.cc/KzqsN24t/bolavip-logo-black.png","accent":"#D81F30","dark":"#9F1622","tint":"#FFF1F2","stripe":"#FFF7F7","rgb":(216,31,48)},
}

@st.cache_data(show_spinner=False)
def data_uri(url):
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "image/png").split(";")[0]
        return f"data:{ctype};base64,{base64.b64encode(r.content).decode('ascii')}"
    except Exception:
        return url


def read_csv(upload):
    raw = upload.getvalue()
    last = None
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc)
            df.columns = [re.sub(r"\s+", " ", str(c).strip()) or f"Column {i+1}" for i,c in enumerate(df.columns)]
            return df
        except Exception as e:
            last = e
    raise last


def numeric_series(s):
    def one(v):
        if pd.isna(v): return None
        x = re.sub(r"[$£€,%]", "", str(v).strip()).replace(",", "")
        x = re.sub(r"^\((.*)\)$", r"-\1", x)
        try: return float(x)
        except Exception: return None
    return s.map(one)


def detect_format(s, name):
    n = name.lower()
    sample = " ".join(s.dropna().astype(str).head(20).tolist())
    if n.strip() in {"rank", "ranking"}: return "Integer"
    if any(x in n for x in ["price","cost","fee","spend","revenue","value"]): return "Currency"
    if any(x in n for x in ["percent","percentage","rate","share","change","yoy","pct"]) or "%" in sample: return "Percent"
    if any(x in sample for x in ["$","£","€"]): return "Currency"
    nums = numeric_series(s)
    if len(s) and nums.notna().mean() >= .92:
        vals = nums.dropna().head(100)
        if len(vals) and all(abs(v-round(v)) < 1e-9 for v in vals): return "Integer"
        return "Number"
    return "Text"


def display_value(v, fmt, currency):
    if pd.isna(v): return "", ""
    raw = str(v).strip()
    if fmt == "Text": return raw, raw.lower()
    n = numeric_series(pd.Series([v])).iloc[0]
    if n is None or pd.isna(n): return raw, raw.lower()
    if fmt == "Integer": return f"{int(round(n)):,}", str(n)
    if fmt == "Currency": return f"{currency}{n:,.2f}", str(n)
    if fmt == "Percent": return f"{n:,.1f}%", str(n)
    if abs(n-round(n)) < 1e-9: return f"{int(round(n)):,}", str(n)
    return f"{n:,.2f}", str(n)


def filename(title):
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", title.strip()).strip("-") or "interactive-table"
    return s[:80] + ".html"


def generate_html(df, cfg):
    brand = BRANDS[cfg["brand"]]
    logo = data_uri(brand["logo"])
    cols = cfg["columns"]
    labels, fmts, aligns = cfg["labels"], cfg["formats"], cfg["aligns"]
    rank_col = next((c for c in cols if c.lower().strip() in {"rank","ranking"}), None)
    table_min_width = max(720, min(1600, len(cols) * 130))

    heat_stats = {}
    for c in cfg["heat"]:
        nums = numeric_series(df[c]).dropna()
        if len(nums): heat_stats[c] = (float(nums.min()), float(nums.max()))

    th = []
    for i,c in enumerate(cols):
        typ = "number" if fmts[c] != "Text" else "text"
        th.append(f'<th data-col="{i}" data-type="{typ}" class="{"sortable" if cfg["sortable"] else ""}"><span>{html.escape(labels[c])}</span>{"<i></i>" if cfg["sortable"] else ""}</th>')

    rows = []
    for pos,(_,r) in enumerate(df[cols].iterrows()):
        top = False
        if cfg["top3"]:
            if rank_col:
                try:
                    rv = numeric_series(pd.Series([r[rank_col]])).iloc[0]
                    top = rv is not None and not pd.isna(rv) and rv <= 3
                except Exception: pass
            else:
                top = pos < 3
        tds, search = [], []
        for c in cols:
            disp, sortv = display_value(r[c], fmts[c], cfg["currency"])
            search.append(disp)
            style = ""
            if c in heat_stats:
                lo,hi = heat_stats[c]
                nv = numeric_series(pd.Series([r[c]])).iloc[0]
                if nv is not None and not pd.isna(nv):
                    ratio = .55 if hi == lo else max(0,min(1,(float(nv)-lo)/(hi-lo)))
                    a = .05 + ratio*.17
                    rr,gg,bb = brand["rgb"]
                    style = f"background:rgba({rr},{gg},{bb},{a:.3f});"
            tds.append(f'<td data-label="{html.escape(labels[c])}" data-sort="{html.escape(sortv)}" class="a-{aligns[c].lower()}" style="{style}">{html.escape(disp)}</td>')
        blob = html.escape(" ".join(search).lower())
        rows.append(f'<tr class="data-row{" top" if top else ""}" data-search="{blob}">{"".join(tds)}</tr>')

    header_logo = f'<img src="{html.escape(logo)}" alt="{html.escape(cfg["brand"])} logo">' if cfg["header_logo"] else ""
    footer_logo = f'<img src="{html.escape(logo)}" alt="{html.escape(cfg["brand"])} logo">' if cfg["footer_logo"] else ""

    meta = []
    for lab,key in [("Source","source"),("Methodology","method"),("Credit","credit"),("Updated","updated")]:
        if cfg[key].strip(): meta.append(f'<div><strong>{lab}</strong><span>{html.escape(cfg[key].strip())}</span></div>')
    footer = ""
    if footer_logo or meta or cfg["footnote"].strip():
        footnote_html = f'<p class="footnote">{html.escape(cfg["footnote"].strip())}</p>' if cfg["footnote"].strip() else ""
    footer = f'<footer><div class="footer-main"><div class="footer-meta">{"".join(meta)}</div><div class="footer-logo">{footer_logo}</div></div>{footnote_html}</footer>'

    controls = []
    if cfg["search"]:
        controls.append('<label class="search"><span class="sr">Search table</span><input id="q" type="search" placeholder="Search table"></label>')
    if cfg["row_count"]: controls.append('<div id="count" class="count"></div>')
    if cfg["pager"]:
        opts = ''.join(f'<option value="{n}" {"selected" if n == cfg["page_size"] else ""}>{n}</option>' for n in [10,15,20,30,50]) + '<option value="0">All</option>'
        controls.append(f'<div class="pager"><label>Rows <select id="size">{opts}</select></label><button id="prev" type="button">←</button><span id="status"></span><button id="next" type="button">→</button></div>')
    controls_html = f'<div class="controls">{"".join(controls)}</div>' if controls else ""

    mobile_css = """
    @media(max-width:720px){table{min-width:0}thead{display:none}.scroll{border:0;overflow:visible}tbody{display:grid;gap:10px}tbody tr.data-row{display:block!important;border:1px solid var(--line);background:#fff}tbody td{display:grid;grid-template-columns:minmax(100px,38%) minmax(0,1fr);gap:12px;width:100%;border-right:0;padding:10px 12px;text-align:right!important}tbody td:before{content:attr(data-label);color:#69717c;text-align:left;font-size:10px;font-weight:850;letter-spacing:.07em;text-transform:uppercase}}
    """ if cfg["mobile_cards"] else ""

    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(cfg["title"] or "Interactive table")}</title>
<style>
:root{{--accent:{brand["accent"]};--dark:{brand["dark"]};--tint:{brand["tint"]};--stripe:{brand["stripe"]};--line:#e1e5e9;--ink:#171a1e;--muted:#68707c}}
*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#f5f6f7;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Arial,sans-serif;-webkit-font-smoothing:antialiased}}.wrap{{width:min(1180px,100%);margin:auto;background:#fff;border:1px solid var(--line);overflow:hidden}}
header{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:center;padding:26px 28px 24px;background:var(--tint);border-bottom:1px solid color-mix(in srgb,var(--accent) 22%,transparent)}}header img{{max-width:190px;max-height:48px;width:auto}}.kicker{{margin:0 0 8px;color:var(--dark);font-size:11px;font-weight:850;letter-spacing:.12em;text-transform:uppercase}}h1{{margin:0;max-width:900px;font-size:clamp(25px,4vw,42px);line-height:1.02;letter-spacing:-.045em}}.sub{{max-width:820px;margin:10px 0 0;color:#59616d;font-size:clamp(14px,1.7vw,17px);line-height:1.5}}
.body{{padding:18px 20px 20px}}.controls{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}}.search{{flex:1 1 240px;max-width:340px}}input,select,.pager button{{min-height:40px;border:1px solid #d8dde3;border-radius:9px;background:#fff;color:#24282e;font:650 13px/1 system-ui,sans-serif}}input{{width:100%;padding:0 12px}}input:focus,select:focus,.pager button:focus-visible{{outline:3px solid color-mix(in srgb,var(--accent) 16%,transparent);border-color:var(--accent)}}.count{{color:var(--muted);font-size:12.5px;font-weight:700}}.pager{{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;font-weight:700}}.pager label{{display:flex;align-items:center;gap:6px}}.pager select{{padding:0 25px 0 9px}}.pager button{{width:40px;padding:0;cursor:pointer}}.pager button:disabled{{opacity:.35;cursor:default}}
.scroll{{width:100%;overflow-x:auto;border:1px solid var(--line);scrollbar-gutter:stable}}table{{width:100%;min-width:{table_min_width}px;border-collapse:separate;border-spacing:0}}th{{{'position:sticky;top:0;z-index:3;' if cfg['sticky'] else ''}padding:13px 14px;background:#12161b;color:#fff;border-right:1px solid rgba(255,255,255,.08);font-size:12px;line-height:1.25;font-weight:800;text-align:left}}th:last-child{{border-right:0}}th.sortable{{cursor:pointer;user-select:none}}th.sortable i{{display:inline-block;width:7px;height:7px;margin-left:7px;border-right:1.5px solid #9da4ae;border-bottom:1.5px solid #9da4ae;transform:rotate(45deg) translateY(-2px)}}th.asc i{{transform:rotate(225deg)}}td{{padding:13px 14px;border-right:1px solid #edf0f2;border-bottom:1px solid #e9ecef;color:#30353c;font-size:13.5px;line-height:1.4;font-weight:560;background:#fff}}td:last-child{{border-right:0}}{'tbody tr:nth-child(even):not(.top) td{background:var(--stripe)}' if cfg['zebra'] else ''}.top td:first-child{{box-shadow:inset 4px 0 0 var(--accent)}}@media(hover:hover) and (pointer:fine){{tbody tr:hover td{{background:color-mix(in srgb,var(--accent) 8%,#fff)}}}}.a-left{{text-align:left}}.a-center{{text-align:center}}.a-right{{text-align:right;font-variant-numeric:tabular-nums}}#empty{{display:none;padding:34px 20px;text-align:center;color:var(--muted)}}
footer{{padding:19px 24px;background:var(--tint);border-top:1px solid color-mix(in srgb,var(--accent) 18%,transparent)}}.footer-main{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end}}.footer-meta{{display:grid;gap:7px}}.footer-meta div{{display:grid;grid-template-columns:88px minmax(0,1fr);gap:10px;color:#606873;font-size:11.5px;line-height:1.45}}.footer-meta strong{{color:#31363d;font-size:10px;letter-spacing:.08em;text-transform:uppercase}}.footer-logo img{{max-width:180px;max-height:38px;width:auto}}.footnote{{margin:14px 0 0;padding-top:12px;border-top:1px solid rgba(0,0,0,.07);color:#747c86;font-size:10.5px;line-height:1.5}}.sr{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}}
@media(max-width:720px){{body{{padding:8px}}header{{grid-template-columns:1fr;padding:18px 16px 16px}}header img{{max-width:145px;max-height:36px}}.body{{padding:10px}}.controls{{gap:8px;margin-bottom:10px}}.search{{max-width:none;flex-basis:100%}}.count{{order:2}}.pager{{order:3;margin-left:auto;width:auto;justify-content:flex-end}}.scroll{{-webkit-overflow-scrolling:touch}}th,td{{white-space:nowrap}}.footer-main{{flex-direction:column;align-items:flex-start}}.footer-meta div{{grid-template-columns:72px minmax(0,1fr)}}}}
{mobile_css}
</style></head><body><section class="wrap" id="root"><header><div><p class="kicker">{html.escape(cfg["kicker"])}</p><h1>{html.escape(cfg["title"] or "Interactive table")}</h1>{f'<p class="sub">{html.escape(cfg["subtitle"])}</p>' if cfg["subtitle"].strip() else ''}</div>{header_logo}</header><div class="body">{controls_html}<div class="scroll"><table id="table"><thead><tr>{''.join(th)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div><div id="empty">No rows match your search.</div></div>{footer}</section>
<script>(function(){{const t=document.getElementById('table'),tb=t.tBodies[0],q=document.getElementById('q'),size=document.getElementById('size'),prev=document.getElementById('prev'),next=document.getElementById('next'),status=document.getElementById('status'),count=document.getElementById('count'),empty=document.getElementById('empty');let rows=[...tb.querySelectorAll('tr.data-row')],page=1,ps=size?(parseInt(size.value)||0):0,sc=null,dir=1;function filtered(){{let x=q?q.value.trim().toLowerCase():'';return x?rows.filter(r=>(r.dataset.search||'').includes(x)):rows.slice()}}function sv(c,type){{let x=(c?.dataset.sort||c?.textContent||'').trim();if(type==='number'){{let n=parseFloat(x.replace(/,/g,''));return Number.isFinite(n)?n:-Infinity}}return x.toLowerCase()}}function render(){{let a=filtered();if(sc!==null){{let th=t.tHead.rows[0].cells[sc],type=th.dataset.type||'text';a.sort((r1,r2)=>{{let x=sv(r1.cells[sc],type),y=sv(r2.cells[sc],type);return (typeof x==='number'&&typeof y==='number'?(x-y):String(x).localeCompare(String(y),undefined,{{numeric:true}}))*dir}})}}rows.forEach(r=>r.style.display='none');let total=a.length,pages=ps?Math.max(1,Math.ceil(total/ps)):1;page=Math.min(Math.max(1,page),pages);let show=ps?a.slice((page-1)*ps,page*ps):a;show.forEach(r=>{{r.style.display='';tb.appendChild(r)}});if(count)count.textContent=total===rows.length?`${{total.toLocaleString()}} rows`:`${{total.toLocaleString()}} of ${{rows.length.toLocaleString()}} rows`;if(status)status.textContent=`${{page}} / ${{pages}}`;if(prev)prev.disabled=page<=1;if(next)next.disabled=page>=pages;if(empty)empty.style.display=total?'none':'block'}}if(q)q.addEventListener('input',()=>{{page=1;render()}});if(size)size.addEventListener('change',()=>{{ps=parseInt(size.value)||0;page=1;render()}});if(prev)prev.addEventListener('click',()=>{{page--;render()}});if(next)next.addEventListener('click',()=>{{page++;render()}});{'t.querySelectorAll("th.sortable").forEach((th,i)=>{th.tabIndex=0;function go(){if(sc===i)dir*=-1;else{sc=i;dir=1}t.querySelectorAll("th").forEach(x=>x.classList.remove("asc"));if(dir===1)th.classList.add("asc");page=1;render()}th.addEventListener("click",go);th.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();go()}})});' if cfg['sortable'] else ''}render()}})();</script></body></html>'''


head_l, head_r = st.columns([.88,.12], vertical_alignment="bottom")
with head_l:
    st.markdown('<div class="studio-head"><div class="studio-eye">CSV to interactive HTML</div><h1 class="studio-title">Branded Table Studio</h1><p class="studio-sub">Build a clean, responsive, publication-ready interactive table. The exported deliverable is standalone HTML, with no GitHub publishing step and no generated iframe snippet.</p></div>', unsafe_allow_html=True)
with head_r:
    if st.button("Log out", use_container_width=True):
        st.session_state.pop("auth_ok", None); st.rerun()

upload = st.file_uploader("Upload CSV", type=["csv"])
if upload is None:
    st.markdown('<div class="note"><strong>Start with a CSV.</strong> The studio will detect columns, suggest formats and open the live preview.</div>', unsafe_allow_html=True)
    st.stop()

try:
    df = read_csv(upload)
except Exception as e:
    st.error(f"Could not read this CSV: {e}"); st.stop()
if df.empty:
    st.warning("The CSV has no rows."); st.stop()

left,right = st.columns([.39,.61], gap="large")
with left:
    with st.container(border=True):
        st.markdown("### 1. Brand and header")
        brand = st.selectbox("Brand", list(BRANDS))
        st.image(BRANDS[brand]["logo"], width=180)
        title = st.text_input("Title", "Interactive ranking")
        subtitle = st.text_area("Subtitle", "Explore the data, sort any column and search the full ranking.", height=80)
        kicker = st.text_input("Kicker", "Data study")
        header_logo = st.toggle("Show logo in header", True)
    with st.container(border=True):
        st.markdown("### 2. Columns")
        columns = st.multiselect("Columns to include", list(df.columns), default=list(df.columns))
        if not columns:
            st.warning("Select at least one column."); st.stop()
        labels, formats, aligns = {},{},{}
        for c in columns:
            auto = detect_format(df[c], c)
            with st.expander(str(c)):
                labels[c] = st.text_input("Display label", str(c), key=f"lab_{c}")
                options = ["Text","Integer","Number","Currency","Percent"]
                formats[c] = st.selectbox("Format", options, index=options.index(auto), key=f"fmt_{c}")
                default = "Left" if formats[c] == "Text" else "Right"
                aligns[c] = st.selectbox("Alignment", ["Left","Center","Right"], index=["Left","Center","Right"].index(default), key=f"al_{c}")
        currency = st.selectbox("Currency symbol", ["$","£","€","C$","A$"])
    with st.container(border=True):
        st.markdown("### 3. Interaction and layout")
        a,b = st.columns(2)
        with a:
            sortable = st.toggle("Sorting", True); search = st.toggle("Search", len(df)>10); pager = st.toggle("Pagination", len(df)>10); zebra = st.toggle("Zebra rows", True)
        with b:
            sticky = st.toggle("Sticky header", True); row_count = st.toggle("Row count", True); top3 = st.toggle("Highlight top 3", True); mobile_cards = st.toggle("Card layout on phones", False, help="Leave this off to keep the normal table on narrow screens with horizontal scrolling. Turn it on only when you deliberately want each row to become a stacked card.")
        page_size = st.selectbox("Default rows per page", [10,15,20,30,50], index=1)
        heat = st.multiselect("Heatmap columns", [c for c in columns if formats[c] != "Text"], default=[])
    with st.container(border=True):
        st.markdown("### 4. Footer")
        footer_logo = st.toggle("Show logo in footer", True)
        source = st.text_input("Source", "")
        method = st.text_area("Methodology", "", height=84)
        credit = st.text_input("Credit", "")
        updated = st.text_input("Updated", date.today().strftime("%d %B %Y"))
        footnote = st.text_area("Footer note", "", height=70)

cfg = dict(brand=brand,title=title,subtitle=subtitle,kicker=kicker,columns=columns,labels=labels,formats=formats,aligns=aligns,currency=currency,search=search,pager=pager,page_size=page_size,row_count=row_count,sortable=sortable,zebra=zebra,top3=top3,sticky=sticky,mobile_cards=mobile_cards,heat=heat,header_logo=header_logo,footer_logo=footer_logo,source=source,method=method,credit=credit,updated=updated,footnote=footnote)
code = generate_html(df,cfg)

with right:
    st.markdown("### Live preview")
    st.caption(f"{len(df):,} rows · {len(columns)} columns · {brand}. The preview uses a Streamlit component only for display. The downloaded file itself is normal standalone HTML.")
    components.html(code, height=760, scrolling=True)
    st.markdown("### Export")
    x,y = st.columns(2)
    with x:
        st.download_button("Download interactive HTML", code.encode("utf-8"), file_name=filename(title), mime="text/html", use_container_width=True, type="primary")
    with y:
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8-sig"), file_name=re.sub(r"\.html$", ".csv", filename(title)), mime="text/csv", use_container_width=True)
    with st.expander("View generated HTML code"):
        st.code(code, language="html")
