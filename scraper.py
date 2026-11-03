#!/usr/bin/env python3
"""Lector de carteleras de Madrid -> out/data/sesiones.json + out/posters/*.jpg

Uso: python3 -I scraper.py OUT_DIR
Cada fuente va aislada: si una falla, las demás siguen y el fallo queda en "fuentes".
"""
import html, hashlib, io, json, os, re, sys, time, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(f"{OUT}/posters", exist_ok=True); os.makedirs(f"{OUT}/data", exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TODAY = date.today(); HORIZON = TODAY + timedelta(days=31)
MESES = {m: i+1 for i, m in enumerate(["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"])}
MESES_L = {m: i+1 for i, m in enumerate(["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"])}

def get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                return b if binary else b.decode("utf-8", "ignore")
        except Exception:
            if i == tries - 1: raise
            time.sleep(2)

def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def year_for(month):
    y = TODAY.year
    if month < TODAY.month - 2: y += 1
    return y

POSTERS = {}
def poster(url):
    """Descarga, reduce a 300px y guarda como JPEG; devuelve la ruta publicada."""
    if not url: return None
    if url in POSTERS: return POSTERS[url]
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    path = f"{OUT}/posters/{name}"
    try:
        if not os.path.exists(path):
            from PIL import Image
            im = Image.open(io.BytesIO(get(url, binary=True, tries=1))).convert("RGB")
            im.thumbnail((300, 450))
            im.save(path, "JPEG", quality=72, optimize=True)
        POSTERS[url] = f"posters/{name}"
    except Exception:
        POSTERS[url] = None
    return POSTERS[url]

def row(**k):
    k.setdefault("estado", "desconocido")
    k["id"] = hashlib.sha1(f"{k['cine']}|{k['fecha']}|{k['hora']}|{k['titulo']}".encode()).hexdigest()[:14]
    return k

def in_range(f):
    return TODAY.isoformat() <= f <= HORIZON.isoformat()

# ---------------------------------------------------------------- Cineteca
def cineteca():
    base = "https://www.cinetecamadrid.com"
    links = []
    for p in range(0, 25):
        h = get(f"{base}/programacion?to={TODAY.isoformat()}&page={p}")
        found = re.findall(r'<h2 class="title">\s*<a href="(/programacion/[^"]+)"', h)
        new = [l for l in found if l not in links]
        if not new: break
        links += new
    out = []
    with ThreadPoolExecutor(3) as ex:
        for rs in ex.map(lambda l: _safe(cineteca_film, l), links): out += rs
    return out

def cineteca_film(l):
        base = "https://www.cinetecamadrid.com"
        h = get(base + l)
        title = txt((re.search(r'<meta property="og:title" content="([^"]+)"', h) or [None, ""])[1])
        pm = re.search(r'field-name-field-poster">\s*<a href="([^"]+)"', h)
        img = pm.group(1) if pm else (re.search(r'<meta property="og:image" content="([^"]+)"', h) or [None, None])[1]
        ciclo = txt((re.search(r'field-name-field-program">\s*<a[^>]*>(.*?)</a>', h, re.S) or [None, ""])[1]) or None
        dur = re.search(r"\((\d+)'\)", h)
        shop = re.search(r'href="(https://tienda\.madrid-destino\.com/[^"]+)"', h)
        rows = []
        if shop:
            try:
                s = get(shop.group(1))
                for a in re.findall(r'<a href="([^"]+)"[^>]*class="c-mod-sidebar-event__card-option c-mod-sidebar-event__card-option--session"(.*?)</a>', s, re.S):
                    blk = a[1]
                    d = re.search(r'card-option-date">\s*(\d{1,2}) (\w{3}) (\d{4})', blk)
                    t = re.search(r'(\d{1,2}:\d{2})', txt(re.search(r'card-option-time">(.*?)</div>', blk, re.S).group(1)))
                    if not (d and t): continue
                    f = date(int(d.group(3)), MESES[d.group(2).lower()], int(d.group(1))).isoformat()
                    sala = txt((re.search(r'Sala:\s*<strong>(.*?)</strong>', blk) or [None, ""])[1])
                    pr = re.search(r'card-option-price">.*?<strong>([\d,]+)\s*€', blk, re.S)
                    tag = (re.search(r'o-tag--([a-z-]+)', blk) or [None, ""])[1]
                    est = "disponible" if "good" in tag else "pocas" if ("low" in tag or "few" in tag or "medium" in tag) else "agotado" if ("sold" in tag or "no-" in tag or "out" in tag) else "desconocido"
                    if re.search(r"agotad|completo", blk, re.I): est = "agotado"
                    precio = float(pr.group(1).replace(",", ".")) if pr else None
                    if precio == 0: est = "gratis" if est != "agotado" else est
                    rows.append(dict(fecha=f, hora=t.group(1).zfill(5), sala=("Sala " + sala) if sala else None, precio=precio,
                                     estado=est, enlace="https://tienda.madrid-destino.com" + a[0] if a[0].startswith("/") else a[0]))
            except Exception as e:
                print("  tienda fallo", l, type(e).__name__, str(e)[:100], file=sys.stderr)
        if not rows:  # sin tienda: pases de la ficha
            sec = re.search(r'sb-sessions__items">(.*?)</div>\s*</div>', h, re.S)
            month = None
            for tag, val in re.findall(r'<(h2|h4|li) class="sb-sessions__date-(?:month|day|hours-hour)">(.*?)</\1>', sec.group(1) if sec else "", re.S):
                v = txt(val).lower()
                if tag == "h2": month = MESES_L.get(v)
                elif tag == "h4": day = int(re.search(r"\d+", v).group())
                elif tag == "li" and month:
                    hh = re.search(r"\d{1,2}:\d{2}", v)
                    try: fx = date(year_for(month), month, day).isoformat()
                    except ValueError: continue
                    if hh: rows.append(dict(fecha=fx, hora=hh.group().zfill(5), precio=3.5, precioTexto="3,50 €", enlace=base + l))
        cart = poster(base + img if img and img.startswith("/") else img)
        return [row(cine="Cineteca Madrid", titulo=title, ciclo=ciclo, duracion=int(dur.group(1)) if dur else None, cartel=cart, **r) for r in rows]

def _safe(fn, *a):
    try: return fn(*a)
    except Exception as e:
        print("  fallo", a, type(e).__name__, str(e)[:100], file=sys.stderr); return []

# ---------------------------------------------------------------- Cine Doré (Filmoteca)
def dore():
    base = "https://entradasfilmoteca.sacatuentrada.es/es"
    out, seen = [], set()
    for p in range(1, 15):
        h = get(base + (f"?pagina={p}" if p > 1 else ""))
        blocks = re.split(r'(?=<div[^>]*data-fecha=)', h)[1:]
        fresh = 0
        for b in blocks:
            fm = re.search(r'data-fecha="(\d{4}-\d{2}-\d{2})"', b)
            if not fm or fm.group(1) < "2020": continue
            link = re.search(r'href="\s*(https://[^"\s]+/entradas/[^"\s]+)\s*"', b) or re.search(r'href="\s*(https://[^"\s]+/productos/descripcion/[^"\s]+)\s*"', b)
            if not link or link.group(1) in seen: continue
            seen.add(link.group(1)); fresh += 1
            title = txt(re.search(r'<h2 class="titulo font-bold">(.*?)</h2>', b, re.S).group(1))
            director = txt((re.search(r'<h3 class="subtitulo font-bold">(.*?)</h3>', b, re.S) or [None, ""])[1]) or None
            desc = txt((re.search(r'<div class="descripcion">(.*?)</div>\s*</div>', b, re.S) or [None, ""])[1])
            hm = re.search(r"a las (\d{1,2})[:.](\d{2})", desc)
            sm = re.search(r"\((Sala [^.)]+)\.?\s*([^)]*)\)", desc)
            anio = re.search(r",\s*(\d{4})\)\s*$", title)
            img = (re.search(r'data-src="([^"]+)"', b) or [None, None])[1]
            cat = txt((re.search(r'<p class="font-bold"[^>]*>(.*?)</p>', b, re.S) or [None, ""])[1])
            est = "agotado" if re.search(r"agotad", re.sub(r"Aunque las entradas aparezcan como agotadas[^<]*", "", b), re.I) else "desconocido"
            out.append(row(cine="Cine Doré · Filmoteca", titulo=title, director=director, anio=int(anio.group(1)) if anio else None,
                           fecha=fm.group(1), hora=f"{int(hm.group(1)):02d}:{hm.group(2)}" if hm else "", sala=sm.group(1).title() if sm else None,
                           ciclo=(cat or (sm.group(2) if sm else "")).capitalize() or None, precio=3.0, precioTexto="3 € · 2 € red.",
                           estado=est, enlace=link.group(1), cartel=poster(img) if img and "no_image" not in img else None))
        if not fresh: break
    return out

# ---------------------------------------------------------------- Círculo de Bellas Artes
def circulo():
    h = get("https://www.circulobellasartes.com/cine-estudio/")
    out, films = [], {}
    for dia, ses in re.findall(r"<div class='cba_cine_table_dia'>(.*?)</div><div class='cba_cine_sesiones_container'>(.*?)</div></div>", h, re.S):
        dm = re.search(r"(\d{1,2}) (\w{3})", txt(dia))
        if not dm: continue
        m = MESES[dm.group(2).lower()[:3]]
        f = date(year_for(m), m, int(dm.group(1))).isoformat()
        for hora, tit, tipo, info in re.findall(r"cba_cine_table_hora'>(.*?)</div><div class='cba_cine_table_titulo[^']*'>(.*?)</div><div class='cba_cine_table_tipo'>(.*?)</div><div class='cba_cine_table_info'>(.*?)</div>", ses + '</div>', re.S):
            a = re.search(r"<a href='([^']+)'>(.*?)</a>(.*)", tit, re.S)
            url, title, director = (a.group(1), txt(a.group(2)), txt(a.group(3))) if a else (None, txt(tit), None)
            tipo, info = txt(tipo), txt(info)
            red = "reducido" in info.lower()
            precio = 4.0 if red else (8.0 if "estreno" in tipo.lower() else 5.5)
            if url: films[url] = None
            out.append(dict(cine="Círculo de Bellas Artes", titulo=title, director=director or None, fecha=f, hora=txt(hora).zfill(5),
                            ciclo=" · ".join(x for x in [tipo, info] if x) or None, precio=precio,
                            precioTexto=("Desde 4 €" if red else ("8 € · 6 € joven" if precio == 8 else "5,50 €")),
                            enlace=url or "https://www.circulobellasartes.com/cine-estudio/", _u=url))
    def og(u):
        try:
            p = get(u); m = re.search(r'<meta property="og:image" content="([^"]+)"', p); return u, poster(m.group(1)) if m else None
        except Exception: return u, None
    with ThreadPoolExecutor(6) as ex:
        for u, c in ex.map(og, list(films)): films[u] = c
    res = []
    for r in out:
        u = r.pop("_u"); res.append(row(cartel=films.get(u), **r))
    return res

# ---------------------------------------------------------------- Golem Madrid
def golem():
    base = "https://www.golem.es"
    h0 = get(f"{base}/golem/golem-madrid")
    days = [("", TODAY.isoformat())] + [("/" + d, f"{d[:4]}-{d[4:6]}-{d[6:]}") for d in sorted(set(re.findall(r'/golem/golem-madrid/(\d{8})', h0)))]
    out = []
    for suffix, f in days:
        h = h0 if not suffix else get(f"{base}/golem/golem-madrid{suffix}")
        if not suffix:
            tm = re.search(r'class="tabDia".*?(\d{2})/(\d{2})/(\d{4})', h, re.S)
            if tm: f = f"{tm.group(3)}-{tm.group(2)}-{tm.group(1)}"
        parts = re.split(r'<a href="(/golem/pelicula/[^"]+)" target="_top" class="txtNegXXL m5">', h)[1:]
        for i in range(0, len(parts) - 1, 2):
            link, body = parts[i], parts[i + 1]
            title = txt(body.split("</a>")[0])
            img = (re.search(r'<img src="(/golem/carteles/[^"]+)"', body) or [None, None])[1]
            vose = "V.O.S.E" in title.upper()
            for buy, hora in re.findall(r'<a href="(/golem/urlcheck\.php[^"]+)"[^>]*class="horaXXXL">\s*(\d{1,2}:\d{2})', body):
                wd = date.fromisoformat(f).weekday()
                out.append(row(cine="Golem Madrid", titulo=re.sub(r"\s*\(V\.O\.S\.E\.?\)", "", title), version="VOSE" if vose else None,
                               fecha=f, hora=hora.zfill(5), precio=6.3 if wd == 0 else (9.5 if wd >= 4 else 8.4),
                               precioTexto="6,30 € (lunes)" if wd == 0 else ("9,50 €" if wd >= 4 else "8,40 €"),
                               enlace=base + html.unescape(buy), cartel=poster(base + img) if img else None))
    return out


# ---------------------------------------------------------------- eCartelera (salas comerciales e independientes de Madrid capital)
ECARTELERA = [
    ("Cines Embajadores", "https://www.ecartelera.com/cines/cines-embajadores/"),
    ("Embajadores Río", "https://www.ecartelera.com/cines/cine-embajadores-rio/"),
    ("Sala Equis", "https://www.ecartelera.com/cines/sala-equis/"),
    ("Artistic Metropol", "https://www.ecartelera.com/cines/artistic-metropol/"),
    ("Pequeño Cine Estudio", "https://www.ecartelera.com/cines/41,0,1.html"),
    ("Cines Paz", "https://www.ecartelera.com/cines/40,0,1.html"),
    ("Renoir Princesa", "https://www.ecartelera.com/cines/20,0,1.html"),
    ("Renoir Plaza de España", "https://www.ecartelera.com/cines/44,0,1.html"),
    ("Renoir Retiro", "https://www.ecartelera.com/cines/46,0,1.html"),
    ("Renoir Cuatro Caminos", "https://www.ecartelera.com/cines/43,0,1.html"),
    ("Verdi Madrid", "https://www.ecartelera.com/cines/51,0,1.html"),
    ("Verdi Alberto Aguilera", "https://www.ecartelera.com/cines/22,0,1.html"),
]

def ecartelera(name, url):
    h0 = get(url)
    if "(Madrid)" not in h0 or "Madrid (Madrid)" not in h0:
        raise ValueError("no es una sala de Madrid capital")
    pm = re.search(r"<b>Precios:</b>\s*([^<]+)", h0)
    ptxt = txt(pm.group(1)) if pm else None
    pn = re.search(r"(\d+(?:[.,]\d+)?)", ptxt or "")
    precio = float(pn.group(1).replace(",", ".")) if pn else None
    days = re.findall(r'<li[^>]*><a href="([^"]+)" title="Cartelera del [^"]*?(\d{1,2})"', h0)
    if not days:
        one = re.search(r'title="Cartelera del [^"]*?(\d{1,2})"', h0) or re.search(r'<ul class="days">.*?(\d{1,2})</', h0, re.S)
        days = [(url, one.group(1) if one else str(TODAY.day))] if '<div class="titem"' in h0 else []
    out = []
    for i, (u, d) in enumerate(days[:8]):
        h = h0 if i == 0 else get(u)
        d = int(d); m, y = TODAY.month, TODAY.year
        if d < TODAY.day: m += 1
        if m == 13: m, y = 1, y + 1
        f = date(y, m, d).isoformat()
        for blk in re.split(r'<div class="titem"', h)[1:]:
            t = re.search(r'<p class="tit"><a[^>]*>(.*?)</a>', blk, re.S)
            if not t: continue
            img = (re.search(r'<img[^>]*\ssrc="([^"]+)"', blk) or [None, None])[1]
            dr = txt((re.search(r'<p class="dir">Dir\.:(.*?)</p>', blk, re.S) or [None, ""])[1]) or None
            dur = re.search(r"<span>(\d+) min\.</span>", blk)
            for buy, hora, fmt in re.findall(r'<(?:a href="([^"]+)"|span)[^>]*data-session-time="(\d{1,2}:\d{2})" data-session-format="([^"]*)"', blk):
                buy = buy or url
                out.append(row(cine=name, titulo=txt(t.group(1)), director=dr, duracion=int(dur.group(1)) if dur else None,
                               version=fmt or None, fecha=f, hora=hora.zfill(5), precio=precio,
                               precioTexto=(f"{ptxt[:40]}" if ptxt else None), enlace=buy, cartel=poster(img)))
    return out

# ---------------------------------------------------------------- Museo Reina Sofía (cine y vídeo)
def reina_sofia():
    base = "https://www.museoreinasofia.es"
    out, seen = [], set()
    for p in range(0, 6):
        h = get(f"{base}/actividades" + (f"?page={p}" if p else ""))
        items = re.findall(r'<a target="_self" href="(/actividad/[^"]+)">(.*?)</a></div></li>', h, re.S)
        fresh = 0
        for link, blk in items:
            if link in seen: continue
            seen.add(link); fresh += 1
            if "Cine y vídeo" not in blk: continue
            title = txt((re.search(r'module--title--[^"]*">(.*?)</h2>', blk, re.S) or [None, ""])[1])
            sub = txt((re.search(r'module--subtitle--[^"]*">(.*?)</div>', blk, re.S) or [None, ""])[1]) or None
            dm = re.search(r"(\d{1,2}) de (\w+),? (\d{4})\s*-\s*(\d{1,2}:\d{2})", txt((re.search(r'module--dates--[^"]*">(.*?)</p>', blk, re.S) or [None, ""])[1]))
            if not dm or dm.group(2).lower() not in MESES_L: continue
            img = (re.search(r'<img[^>]*src="([^"]+)"', blk) or [None, None])[1]
            out.append(row(cine="Museo Reina Sofía", titulo=title, ciclo=sub, fecha=date(int(dm.group(3)), MESES_L[dm.group(2).lower()], int(dm.group(1))).isoformat(),
                           hora=dm.group(4).zfill(5), sala="Auditorio", precio=0.0, precioTexto="Gratis hasta completar aforo", estado="gratis",
                           enlace=base + link, cartel=poster(img)))
        if not fresh: break
    return out

# ---------------------------------------------------------------- Academia de Cine
def academia():
    h = get("https://www.academiadecine.com/")
    out = []
    for blk in re.split(r'<div class="listadoActividades-actividad"', h)[1:]:
        link = (re.search(r'<a href="([^"]+)"\s+class="listadoActividades-actividad-enlace"', blk) or [None, None])[1]
        title = txt((re.search(r'listadoActividades-actividad-nombre">(.*?)</', blk, re.S) or [None, ""])[1])
        sub = txt((re.search(r'listadoActividades-actividad-subtitulo">(.*?)</', blk, re.S) or [None, ""])[1]) or None
        fecha = txt((re.search(r'listadoActividades-actividad-fecha">(.*?)</', blk, re.S) or [None, ""])[1])
        img = (re.search(r'<img[^>]*src="([^"]+)"', blk) or [None, None])[1]
        if not link or not title or re.search(r"jornada|drink and draw|curso|taller", title + " " + (sub or ""), re.I): continue
        dm = re.search(r"(\d{1,2})/(\w{3})/(\d{4})", fecha)
        f = date(int(dm.group(3)), MESES[dm.group(2).lower()], int(dm.group(1))).isoformat() if dm else (TODAY.isoformat() if "Hoy" in fecha else None)
        if not f: continue
        hora = re.search(r"(\d{1,2}:\d{2})", fecha)
        libre = True
        try:
            d = txt(get(link))
            if not hora:
                i = d.find(title); hora = re.search(r"(\d{1,2}:\d{2})\s*h", d[i:]) or re.search(r"\b(1\d|2[0-3]):[0-5]\d\b", d[i:])
            libre = "Entrada libre" in d or "gratuita" in d.lower()
        except Exception: pass
        out.append(row(cine="Academia de Cine", titulo=title, ciclo=sub, fecha=f, hora=hora.group(1).zfill(5) if hora else "",
                       sala="Sala de proyecciones", precio=0.0 if libre else None, precioTexto="Gratis, con reserva" if libre else None,
                       estado="gratis" if libre else "desconocido", enlace=link, cartel=poster(img)))
    return out

# ---------------------------------------------------------------- Sala Berlanga (Fundación SGAE)
def berlanga():
    after = (TODAY - timedelta(days=75)).isoformat() + "T00:00:00"
    acts = json.loads(get(f"https://salaberlanga.com/wp-json/wp/v2/actividad?per_page=100&modified_after={after}&_fields=link,title"))
    out = []
    def one(a):
        rs = []
        h = get(a["link"]); t = txt(h)
        i = t.find("En cartelera"); j = t.find("Galería Multimedia")
        seg = t[i:j if j > i else i + 3000] if i >= 0 else ""
        ci = re.search(r'og:image" content="([^"]+)"', h)
        title = txt(a["title"]["rendered"])
        ciclo = None
        k = seg.find(title, 20)
        if k > 0: ciclo = seg[k + len(title):].strip().split("  ")[0][:80] or None
        for d, mes, hh in re.findall(r"(\d{1,2}) de (\w+)\s*-\s*(\d{1,2}:\d{2})h", seg):
            m = MESES_L.get(mes.lower())
            if not m: continue
            rs.append(row(cine="Sala Berlanga", titulo=title, fecha=date(year_for(m), m, int(d)).isoformat(), hora=hh.zfill(5),
                          precio=None, precioTexto="Ver web", enlace=a["link"], cartel=None, _img=ci.group(1) if ci else None))
        return rs
    with ThreadPoolExecutor(4) as ex:
        for rs in ex.map(lambda a: _safe(one, a), acts): out += rs
    for r in out:
        r["cartel"] = poster(r.pop("_img"))
    return out

# ---------------------------------------------------------------- Ayuntamiento de Madrid: Conde Duque, centros culturales y bibliotecas (datos abiertos)
def ayuntamiento():
    d = json.loads(get("https://datos.madrid.es/egob/catalogo/206974-0-agenda-eventos-culturales-100.json"))
    out = []
    for e in d.get("@graph", []):
        if "CineActividadesAudiovisuales" not in e.get("@type", ""): continue
        loc = (e.get("event-location") or "").strip()
        if not loc or "Cineteca" in loc: continue
        if (e.get("address", {}).get("area", {}) or {}).get("locality", "MADRID").upper() != "MADRID": continue
        s, en = (e.get("dtstart") or "")[:10], (e.get("dtend") or "")[:10]
        if not s: continue
        f = s
        ciclo = None
        if en and en != s:
            ciclo = f"Del {s[8:10]}/{s[5:7]} al {en[8:10]}/{en[5:7]}"
            if s < TODAY.isoformat() <= en: f = TODAY.isoformat()
        free = str(e.get("free")) == "1"
        pr = re.search(r"(\d+(?:[.,]\d+)?)", e.get("price") or "")
        precio = 0.0 if free else (float(pr.group(1).replace(",", ".")) if pr else None)
        out.append(row(cine=loc.replace("CondeDuque", "Conde Duque"), titulo=txt(e.get("title")), ciclo=ciclo, fecha=f, hora=(e.get("time") or "").zfill(5) if e.get("time") else "",
                       precio=precio, precioTexto="Gratis" if free else (txt(e.get("price"))[:40] or None), estado="gratis" if free else "desconocido",
                       enlace=(e.get("link") or "").replace("http://", "https://"), municipal=True))
    return out

SOURCES = [("Cineteca Madrid", cineteca), ("Cine Doré · Filmoteca", dore), ("Círculo de Bellas Artes", circulo), ("Golem Madrid", golem),
           ("Museo Reina Sofía", reina_sofia), ("Academia de Cine", academia), ("Sala Berlanga", berlanga),
           ("Conde Duque y centros culturales municipales", ayuntamiento)] + \
          [(n, (lambda n=n, u=u: ecartelera(n, u))) for n, u in ECARTELERA]


# ---------------------------------------------------------------- Portadas que faltan: búsqueda en Wikipedia
WIKI_UA = "CarteleraDeBolsillo/1.0 (https://neowis.github.io/cartelera/)"
CACHE_IN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "carteles_buscados.json")
NO_FILM = re.compile(r"\b(teatro|danza|curso|taller|cocina|cata|conferencia|charla|coloquio sobre|club de lectura|ficción sonora|creación audiovisual|jornada|concurso|cortos?\b|cortometrajes|festival|muestra|ciclo \d|semana)\b", re.I)

def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"^(el|la|los|las|the|le|les|il|a)\s+", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()

def clean_title(t):
    """Devuelve (título, título alternativo, año) o None si no parece una película concreta."""
    raw = t.strip()
    year = None
    m = re.search(r"\(([^()]*?)\b((?:18|19|20)\d{2})\)\s*\.?$", raw)
    alt = None
    if m:
        year = int(m.group(2)); alt = m.group(1).strip(" ,;") or None
        raw = raw[:m.start()].strip()
    q = re.search(r"[‘'`´\"“]([^'’`´\"”]{2,80})[’'`´\"”]", raw)
    if q and (":" in raw or re.search(r"cine|biblioteca|quedada|matinal", raw, re.I)):
        inner = q.group(1).strip()
        y2 = re.search(r"\(((?:18|19|20)\d{2})\b[^)]*\)", raw)
        if y2 and not year: year = int(y2.group(1))
        raw = inner
    elif re.search(r"^(cine|cinefórum|cineclub|cine-club|cine club|documental)\b", raw, re.I):
        raw = re.sub(r"^[^:]*:\s*", "", raw) if ":" in raw else ""
    raw = re.sub(r"\s*\(V\.?O\.?S\.?E?\.?\)|\s*\(VOSE\)", "", raw, flags=re.I).strip(" .'\"")
    if not raw or len(raw) < 2 or NO_FILM.search(t): return None
    return raw, alt, year

def _wiki_get(lang, params):
    qs = urllib.parse.urlencode({"action": "query", "format": "json", "redirects": 1, **params})
    req = urllib.request.Request(f"https://{lang}.wikipedia.org/w/api.php?{qs}", headers={"User-Agent": WIKI_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("query", {}).get("pages", {})

def wiki_poster(title, alt, year):
    """Busca el artículo por título exacto (sin buscador) y devuelve su imagen principal si es una película."""
    cands = [title] + ([alt] if alt and _norm(alt) != _norm(title) else [])
    for lang in ("es", "en"):
        titles = []
        for c in cands:
            c = c[:1].upper() + c[1:]
            if lang == "es":
                titles += ([f"{c} (película de {year})"] if year else []) + [f"{c} (película)", c]
            else:
                titles += ([f"{c} ({year} film)"] if year else []) + [f"{c} (film)", c]
        try:
            pages = _wiki_get(lang, {"titles": "|".join(titles[:50]), "prop": "pageimages|description|categories",
                                     "piprop": "thumbnail", "pithumbsize": 500, "pilicense": "any", "cllimit": 50})
        except Exception:
            continue
        order = {t: k for k, t in enumerate(titles)}
        best = None
        for pg in pages.values():
            if "missing" in pg: continue
            desc = (pg.get("description") or "").lower()
            cats = " ".join(c.get("title", "") for c in pg.get("categories", [])).lower()
            ptitle = pg.get("title", "")
            text = f"{desc} {ptitle.lower()} {cats}"
            if "desambiguación" in text or "disambiguation" in text: continue
            if not re.search(r"\bfilm|película|pelicula|cortometraje|documental|animated|anime", text): continue
            if year and not any(str(year + d) in text for d in (-1, 0, 1)): continue
            th = (pg.get("thumbnail") or {}).get("source")
            if not th: continue
            rank = min([order.get(t, 99) for t in order if _norm(t.split(" (")[0]) == _norm(ptitle.split(" (")[0])] or [99])
            if best is None or rank < best[0]: best = (rank, th)
        if best: return best[1]
        time.sleep(0.2)
    return None

def tmdb_poster(title, alt, year):
    """TMDB (themoviedb.org): películas y cortos, incluidos clásicos. Necesita la variable de entorno TMDB_TOKEN."""
    token = os.environ.get("TMDB_TOKEN", "").strip()
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not token and not key: return None
    for c in [title] + ([alt] if alt else []):
        for lang in ("es-ES", "en-US"):
            q = {"query": c, "language": lang, "include_adult": "false"}
            if year: q["year"] = year
            if not token: q["api_key"] = key
            hdr = {"Accept": "application/json"}
            if token: hdr["Authorization"] = "Bearer " + token
            req = urllib.request.Request("https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode(q), headers=hdr)
            try:
                with urllib.request.urlopen(req, timeout=20) as r: res = json.load(r).get("results", [])
            except Exception:
                continue
            same = [m for m in res if m.get("poster_path") and _norm(c) in (_norm(m.get("title", "")), _norm(m.get("original_title", "")))]
            if year:
                same = [m for m in same if (m.get("release_date") or "")[:4].isdigit() and abs(int(m["release_date"][:4]) - year) <= 1]
            if not year and len(same) > 1:
                same.sort(key=lambda m: -(m.get("popularity") or 0))
                if (same[1].get("popularity") or 0) * 3 > (same[0].get("popularity") or 0): same = []
            if same:
                return "https://image.tmdb.org/t/p/w342" + same[0]["poster_path"]
            time.sleep(0.1)
    return None

def ecartelera_poster(title, alt, year):
    """Busca en eCartelera y acepta solo una película con el mismo título (y año, si se conoce)."""
    for c in [title] + ([alt] if alt else []):
        try:
            h = get("https://www.ecartelera.com/buscar/?q=" + urllib.parse.quote(c), tries=1)
        except Exception:
            continue
        found = re.findall(r'<a class="sr-thing" href="(https://www\.ecartelera\.com/peliculas/[^"]+)">.*?<img src="([^"]+)".*?sr-thing__title">(.*?)</span>\s*<span class="sr-thing__meta">(.*?)</span>', h, re.S)
        same = [f for f in found if _norm(txt(f[2])) == _norm(c)]
        if not year and len(same) != 1: continue
        for href, img, t, meta in same:
            y = re.search(r"(18|19|20)\d{2}", meta)
            if year and (not y or abs(int(y.group()) - year) > 1): continue
            big = img.replace("-th.jpg", ".jpg")
            try:
                get(big, binary=True, tries=1); return big
            except Exception:
                return img
        time.sleep(0.4)
    return None

def fill_missing_posters(rows):
    try: cache = json.load(open(CACHE_IN, encoding="utf8"))
    except Exception: cache = {}
    week_ago = (TODAY - timedelta(days=7)).isoformat()
    found = 0
    for r in rows:
        if r.get("cartel"): continue
        ct = clean_title(r["titulo"])
        if not ct: continue
        key = _norm(ct[0]) + (f"|{ct[2]}" if ct[2] else "")
        hit = cache.get(key)
        has_tmdb = bool(os.environ.get("TMDB_TOKEN", "").strip() or os.environ.get("TMDB_API_KEY", "").strip())
        if hit is None or (not hit.get("url") and (hit.get("t", "") < week_ago or (has_tmdb and not hit.get("tmdb")))):
            url, src = tmdb_poster(*ct), "TMDB"
            if not url: url, src = ecartelera_poster(*ct), "eCartelera"
            if not url:
                try: url, src = wiki_poster(*ct), "Wikipedia"
                except Exception: url = None
            hit = cache[key] = {"url": url or "", "fuente": src if url else "", "t": TODAY.isoformat(), "titulo": ct[0], "tmdb": has_tmdb}
        if hit.get("url"):
            r["cartel"] = poster(hit["url"])
            if r["cartel"]: r["cartelFuente"] = hit.get("fuente") or "web"; found += 1
    with open(f"{OUT}/data/carteles_buscados.json", "w", encoding="utf8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=0)
    print(f"Portadas buscadas y encontradas: {found}", file=sys.stderr)

def main():
    all_rows, fuentes = [], []
    for name, fn in SOURCES:
        t0 = time.time()
        try:
            rs = [r for r in fn() if r.get("fecha") and in_range(r["fecha"]) and r.get("titulo")]
            all_rows += rs; fuentes.append({"cine": name, "ok": True, "n": len(rs)})
        except Exception as e:
            fuentes.append({"cine": name, "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"})
        print(f"{name}: {fuentes[-1]} ({time.time()-t0:.0f}s)", file=sys.stderr)
    try: fill_missing_posters(all_rows)
    except Exception as e: print("Búsqueda de portadas falló:", e, file=sys.stderr)
    uniq = {r["id"]: {k: v for k, v in r.items() if v not in (None, "")} for r in all_rows}
    now = datetime.now(timezone.utc)
    data = {"actualizado": now.isoformat(timespec="seconds"), "proxima": (now + timedelta(hours=3)).isoformat(timespec="seconds"),
            "fuentes": fuentes, "sesiones": sorted(uniq.values(), key=lambda r: (r["fecha"], r.get("hora", ""), r["cine"]))}
    with open(f"{OUT}/data/sesiones.json", "w", encoding="utf8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    used = {r.get("cartel") for r in uniq.values()}
    for fn in os.listdir(f"{OUT}/posters"):
        if f"posters/{fn}" not in used: os.remove(f"{OUT}/posters/{fn}")
    print(json.dumps({"sesiones": len(uniq), "carteles": len(used - {None}), "fuentes": fuentes}, ensure_ascii=False))

if __name__ == "__main__":
    main()
