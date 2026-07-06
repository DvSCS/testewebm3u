#!/usr/bin/env python3
import requests, re, json, sys, time, os
from urllib.parse import unquote, urljoin, quote

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

def log(msg):
    print(msg, flush=True)

def clean_url(url):
    return url.replace("\\/", "/").replace("\\", "")

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

def get_tmdb_ids():
    log("[*] Buscando lista de filmes...")
    raw = fetch(API_MOVIE_URL)
    if not raw:
        log("[!] Erro na API")
        sys.exit(1)
    ids = json.loads(raw)
    log(f"[+] {len(ids)} filmes disponiveis")
    return ids

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

def get_best(sources, fallback=""):
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

def resolve_source(source):
    file_url = unquote(source["file"])
    resolved = {"file": file_url, "type": source["type"], "label": source["label"]}
    if source["type"] in ("hls", "m3u8"):
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
                    resolved["file"] = best_url
        except: pass
    return resolved

def sign_url(target_url):
    try:
        r = requests.get(SIGN_URL, params={"url": target_url}, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("encrypted"):
                return data["encrypted"]
    except: pass
    return None

def generate_m3u(movies):
    lines = ["#EXTM3U"]
    for m in movies:
        src = m["source"]
        lines.append(f'#EXTINF:-1 tvg-id="{m["tmdb_id"]}" tvg-name="{m["title"]}" tvg-logo="{m["poster"]}" group-title="MegaEmbed",{m["title"]}')
        lines.append(src["file"])
    return "\n".join(lines)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MegaEmbed Scraper")
    parser.add_argument("--qty", type=int, default=int(os.environ.get("SCRAPE_QTY", "100")))
    parser.add_argument("--start", type=int, default=int(os.environ.get("SCRAPE_START", "1")))
    parser.add_argument("--sign", action="store_true", help="Re-sign URLs via sign.php para tokens frescos")
    args = parser.parse_args()

    log("=" * 50)
    log("  MegaEmbed Auto Scraper")
    log("=" * 50)

    ids = get_tmdb_ids()
    total = len(ids)
    start = max(0, args.start - 1)
    qty = min(args.qty, total - start)
    if qty <= 0:
        log("[!] Nada para processar")
        sys.exit(1)

    movies_to_scrape = ids[start:start + qty]
    log(f"[*] Processando {len(movies_to_scrape)} filmes...")

    all_movies = []
    errors = 0
    start_time = time.time()

    for idx, tmdb_id in enumerate(movies_to_scrape):
        log(f"[{idx+1}/{len(movies_to_scrape)}] TMDB:{tmdb_id}")
        html = fetch(EMBED_URL.format(tmdb_id))
        if not html:
            html = fetch(EMBED_URL.format(tmdb_id), use_cf=True)
        if not html:
            errors += 1
            continue
        title, poster, sources, fallback = extract_sources(html)
        if not sources and not fallback:
            errors += 1
            continue
        best = get_best(sources, fallback)
        if not best:
            errors += 1
            continue
        resolved = resolve_source(best)
        if args.sign and resolved["file"]:
            signed = sign_url(resolved["file"])
            if signed:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(resolved["file"])
                qs = parse_qs(parsed.query)
                ext = qs.get("ext", ["m3u8"])[0]
                file_path = qs.get("file", ["/master.m3u8"])[0]
                cdn_base = f"{parsed.scheme}://{parsed.netloc}/includes/hls.php"
                resolved["file"] = f"{cdn_base}?url={quote(signed)}&ext={ext}&file={file_path}"
        all_movies.append({
            "tmdb_id": str(tmdb_id), "title": title, "poster": poster, "source": resolved,
        })

    log(f"\n[+] OK: {len(all_movies)} | Erros: {errors} | Tempo: {time.time()-start_time:.0f}s")
    if not all_movies:
        log("[!] Nenhum filme encontrado")
        sys.exit(1)

    m3u_content = generate_m3u(all_movies)
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)
    with open("playlist.txt", "w", encoding="utf-8") as f:
        f.write(m3u_content)
    with open("playlist.json", "w", encoding="utf-8") as f:
        json.dump(all_movies, f, ensure_ascii=False, indent=2)
    log(f"[+] Playlist salva: playlist.m3u ({len(all_movies)} filmes)")

    # Upload Catbox
    log("[*] Enviando para Catbox.moe...")
    try:
        with open("playlist.m3u", "rb") as f:
            r = requests.post("https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": ("playlist.m3u", f, "text/plain")}, timeout=30)
        if r.status_code == 200 and r.text.startswith("http"):
            catbox_url = r.text.strip()
            with open("catbox_url.txt", "w") as f:
                f.write(catbox_url)
            import datetime
            with open("generated_at.txt", "w") as f:
                f.write(datetime.datetime.now().isoformat())
            log(f"[+] CATBOX: {catbox_url}")
        else:
            log(f"[!] Erro Catbox: {r.status_code} {r.text[:100]}")
    except Exception as e:
        log(f"[!] Erro Catbox: {e}")

    log(f"\n[+] FINALIZADO! {len(all_movies)} filmes na playlist")

if __name__ == "__main__":
    main()
