import requests
import re
import json
import time
import os
from urllib.parse import urlparse, unquote, urljoin
from flask import Flask, request, render_template_string, Response, redirect

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

BASE_URL = "https://mgeb.top"
API_MOVIE_URL = f"{BASE_URL}/api/movie"
EMBED_URL = f"{BASE_URL}/embed/{{}}"
SIGN_URL = "https://mgeb.top/includes/sign.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://mgeb.top/",
}

session = requests.Session()
session.headers.update(HEADERS)

cf_session = None
if HAS_CLOUDSCRAPER:
    cf_session = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )

CACHED_MOVIES = []
SCRAPE_IN_PROGRESS = False

app = Flask(__name__)

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MegaEmbed Proxy</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
        .container { max-width: 800px; margin: 0 auto; padding: 40px 20px; }
        h1 { font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 8px; }
        .subtitle { color: #888; margin-bottom: 30px; }
        .card { background: #1a1a2e; border-radius: 12px; padding: 30px; margin-bottom: 20px; border: 1px solid #2a2a3e; }
        label { display: block; font-size: 14px; font-weight: 600; color: #aaa; margin-bottom: 8px; }
        input, select { width: 100%; padding: 12px 16px; background: #12121e; border: 1px solid #2a2a3e; border-radius: 8px; color: #fff; font-size: 16px; margin-bottom: 16px; }
        input:focus { outline: none; border-color: #6c5ce7; }
        button { background: #6c5ce7; color: #fff; border: none; padding: 12px 24px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background .2s; }button:hover { background: #5a4bd1; }
        .link-box { background: #12121e; border: 1px solid #6c5ce7; border-radius: 8px; padding: 16px; margin: 12px 0; }
        .link-box a { color: #6c5ce7; word-break: break-all; }
        .link-label { font-size: 12px; color: #888; margin-top: 4px; }
        .status { background: #12121e; border: 1px solid #2a2a3e; border-radius: 8px; padding: 16px; margin: 16px 0; font-family: monospace; font-size: 13px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
        .nav-links { display: flex; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
        .nav-links a { color: #6c5ce7; text-decoration: none; padding: 8px 16px; border: 1px solid #6c5ce7; border-radius: 8px; font-size: 14px; }
        .nav-links a:hover { background: #6c5ce7; color: #fff; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .badge-green { background: rgba(0,214,143,.15); color: #00d68f; }
        @media (max-width: 600px) { .container { padding: 20px 12px; } .card { padding: 20px; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>MegaEmbed Proxy</h1>
        <p class="subtitle">Tokens gerados sob demanda via sign.php - sem GitHub Actions, sem PC ligado</p>

        <div class="card">
            <h3 style="margin-bottom:12px;">PLAYLIST PROXY (RECOMENDADO)</h3>
            <p style="color:#888;font-size:14px;margin-bottom:12px;">
                Cada link gera um token FRESCO na hora do acesso via <code>sign.php</code>.
                Nao precisa re-scrapear. O link da playlist nunca expira.
            </p>
            {% if proxy_url %}
            <div class="link-box">
                <a href="{{ proxy_url }}" target="_blank">{{ proxy_url }}</a>
                <div class="link-label">Playlist M3U - tokens sempre frescos</div>
            </div>
            {% endif %}
            <div class="nav-links">
                <a href="/playlist.m3u">Playlist M3U</a>
                <a href="/playlist.txt">Playlist TXT</a>
            </div>
        </div>

        {% if catbox_url %}
        <div class="card" style="border-color:#00d68f;">
            <h3 style="margin-bottom:12px;color:#00d68f;">Catbox (cache estatico)</h3>
            <div class="link-box" style="border-color:#00d68f;">
                <a href="{{ catbox_url }}" target="_blank">{{ catbox_url }}</a>
                <div class="link-label">Versao estatica com links fixos - expira em horas/dias</div>
            </div>
        </div>
        {% endif %}

        <div class="card">
            <form method="POST" action="/scrape" style="display:flex;gap:12px;flex-wrap:wrap;">
                <input type="number" name="qty" value="50" min="1" style="flex:1;min-width:100px;margin:0;">
                <input type="number" name="start" value="1" min="1" style="flex:1;min-width:100px;margin:0;">
                <button type="submit">Scrapear</button>
            </form>
            {% if status %}
            <div class="status">{{ status }}</div>
            {% endif %}
        </div>

        {% if movies %}
        <div class="card">
            <h3 style="margin-bottom:12px;">Filmes ({{ movies|length }})</h3>
            <div class="status" style="max-height:300px;">
                {% for m in movies %}
[{{ loop.index }}] {{ m.title }}
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="card" style="text-align:center;color:#666;font-size:13px;">
            MegaEmbed Proxy v3.0 - usa sign.php para tokens frescos sob demanda
        </div>
    </div>
</body>
</html>
"""

def fetch(url, use_cf=False, retries=3):
    s = cf_session if (use_cf and cf_session) else session
    for i in range(retries):
        try:
            r = s.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
        except:
            if i < retries - 1:
                time.sleep(2 ** i)
    return None

def clean_url(url):
    return url.replace("\\/", "/").replace("\\", "")

def extract_sources(html):
    sources = []
    title = "Desconhecido"
    poster = ""
    m = re.search(r'var title\s*=\s*"([^"]+)"', html)
    if m: title = m.group(1)
    m = re.search(r'var poster\s*=\s*"([^"]+)"', html)
    if m: poster = clean_url(m.group(1))
    m = re.search(r'var sources\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if m:
        raw = re.sub(r',\s*}', '}', m.group(1))
        raw = re.sub(r',\s*\]', ']', raw)
        try:
            for s in json.loads(raw):
                sources.append({"file": clean_url(s.get("file","")), "type": s.get("type","mp4"), "label": s.get("label","")})
        except: pass
    fb = re.search(r'var fallbackUrl\s*=\s*"([^"]+)"', html)
    fallback = clean_url(fb.group(1)) if fb else ""
    return title, poster, sources, fallback

def pick_best(sources, fallback=""):
    seen = set()
    unique = []
    for s in sources:
        f = s["file"]
        if f and f not in seen:
            seen.add(f)
            unique.append(s)
    prio = {"mp4": 0, "hls": 1, "m3u8": 1, "webm": 2, "iframe": 3}
    unique.sort(key=lambda x: prio.get(x["type"], 99))
    if unique: return unique[0]
    if fallback: return {"file": fallback, "type": "iframe", "label": "Fallback"}
    return None

def resolve_hls(file_url):
    try:
        r = session.get(file_url, headers=HEADERS, timeout=15)
        if r.status_code == 200 and b"#EXTM3U" in r.content:
            lines = r.text.strip().split("\n")
            best_url = None
            best_res = 0
            res_match = None
            for line in lines:
                line = line.strip()
                if line.startswith("#EXT-X-STREAM-INF"):
                    rm = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                    res_match = int(rm.group(1)) * int(rm.group(2)) if rm else None
                elif line and not line.startswith("#"):
                    if res_match and res_match > best_res:
                        best_res = res_match
                        best_url = line
                    elif best_url is None:
                        best_url = line
            if best_url:
                if not best_url.startswith("http"):
                    base = file_url[:file_url.rfind("/") + 1]
                    best_url = urljoin(base, best_url)
                return best_url
    except: pass
    return file_url

def sign_url(target_url):
    try:
        r = requests.get(SIGN_URL, params={"url": target_url}, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("encrypted"):
                return data["encrypted"]
    except: pass
    return None

def get_fresh_url(tmdb_id):
    html = fetch(EMBED_URL.format(tmdb_id))
    if not html:
        html = fetch(EMBED_URL.format(tmdb_id), use_cf=True)
    if not html:
        return None
    title, poster, sources, fallback = extract_sources(html)
    best = pick_best(sources, fallback)
    if not best:
        return None
    proxied_url = best["file"]
    resolved_url = resolve_hls(proxied_url)
    return {"title": title, "poster": poster, "file": resolved_url, "type": best["type"]}

@app.route("/")
def index():
    global CACHED_MOVIES
    base = request.host_url.rstrip("/")
    proxy_url = base + "/playlist.m3u" if CACHED_MOVIES else None
    catbox_url = None
    if os.path.exists("catbox_url.txt"):
        with open("catbox_url.txt") as f:
            catbox_url = f.read().strip()
    return render_template_string(PAGE_TEMPLATE,
        proxy_url=proxy_url, catbox_url=catbox_url,
        movies=CACHED_MOVIES, status=None)

@app.route("/scrape", methods=["POST"])
def scrape():
    global CACHED_MOVIES, SCRAPE_IN_PROGRESS
    if SCRAPE_IN_PROGRESS:
        return redirect("/")
    qty = int(request.form.get("qty", 50))
    start = int(request.form.get("start", 1)) - 1
    SCRAPE_IN_PROGRESS = True
    try:
        raw = fetch(API_MOVIE_URL)
        if not raw:
            return "Erro na API", 500
        ids = json.loads(raw)
        total = len(ids)
        movies = ids[start:start+qty]
        all_movies = []
        errors = 0
        for i, tmdb_id in enumerate(movies):
            html = fetch(EMBED_URL.format(tmdb_id))
            if not html:
                html = fetch(EMBED_URL.format(tmdb_id), use_cf=True)
            if not html:
                errors += 1
                continue
            title, poster, sources, fallback = extract_sources(html)
            best = pick_best(sources, fallback)
            if not best:
                errors += 1
                continue
            all_movies.append({"tmdb_id": str(tmdb_id), "title": title, "poster": poster, "source": best})
        CACHED_MOVIES = all_movies
        with open("playlist.json", "w", encoding="utf-8") as f:
            json.dump(all_movies, f, ensure_ascii=False, indent=2)
        # Upload estatico para Catbox
        if all_movies:
            m3u_lines = ["#EXTM3U"]
            for m in all_movies:
                m3u_lines.append(f'#EXTINF:-1 tvg-id="{m["tmdb_id"]}" tvg-name="{m["title"]}" tvg-logo="{m["poster"]}" group-title="MegaEmbed",{m["title"]}')
                m3u_lines.append(m["source"]["file"])
            m3u = "\n".join(m3u_lines)
            for name in ["playlist_static.txt", "playlist_static.m3u"]:
                with open(name, "w", encoding="utf-8") as f:
                    f.write(m3u)
            try:
                with open("playlist_static.txt", "rb") as f:
                    r = requests.post("https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": ("playlist.m3u", f, "text/plain")}, timeout=30)
                if r.status_code == 200 and r.text.startswith("http"):
                    with open("catbox_url.txt", "w") as f:
                        f.write(r.text.strip())
            except: pass
    finally:
        SCRAPE_IN_PROGRESS = False
    return redirect("/")

@app.route("/proxy/<tmdb_id>")
def proxy_play(tmdb_id):
    result = get_fresh_url(tmdb_id)
    if not result:
        return "Filme nao encontrado", 404
    return redirect(result["file"], code=302)

@app.route("/playlist.m3u")
def playlist_m3u():
    global CACHED_MOVIES
    if not CACHED_MOVIES and os.path.exists("playlist.json"):
        with open("playlist.json") as f:
            CACHED_MOVIES = json.load(f)
    if not CACHED_MOVIES:
        return "Nenhum filme cacheado. Acesse / para scrapear.", 404
    base = request.host_url.rstrip("/")
    lines = ["#EXTM3U"]
    for m in CACHED_MOVIES:
        lines.append(f'#EXTINF:-1 tvg-id="{m["tmdb_id"]}" tvg-name="{m["title"]}" tvg-logo="{m["poster"]}" group-title="MegaEmbed",{m["title"]}')
        lines.append(f"{base}/proxy/{m['tmdb_id']}")
    return Response("\n".join(lines), mimetype="application/x-mpegURL", headers={
        "Access-Control-Allow-Origin": "*",
        "Content-Disposition": "attachment; filename=playlist.m3u",
    })

@app.route("/playlist.txt")
def playlist_txt():
    global CACHED_MOVIES
    if not CACHED_MOVIES and os.path.exists("playlist.json"):
        with open("playlist.json") as f:
            CACHED_MOVIES = json.load(f)
    if not CACHED_MOVIES:
        return "Nenhum filme cacheado.", 404
    base = request.host_url.rstrip("/")
    lines = ["#EXTM3U"]
    for m in CACHED_MOVIES:
        lines.append(f'#EXTINF:-1 tvg-id="{m["tmdb_id"]}" tvg-name="{m["title"]}" tvg-logo="{m["poster"]}" group-title="MegaEmbed",{m["title"]}')
        lines.append(f"{base}/proxy/{m['tmdb_id']}")
    return Response("\n".join(lines), mimetype="text/plain", headers={
        "Access-Control-Allow-Origin": "*",
        "Content-Disposition": "attachment; filename=playlist.txt",
    })

@app.route("/health")
def health():
    return {"status": "ok", "movies": len(CACHED_MOVIES) if CACHED_MOVIES else 0}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
