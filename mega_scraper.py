import requests
import re
import json
import sys
import time
import os
from urllib.parse import urlparse, unquote, urljoin, quote

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://mgeb.top/",
    "Origin": "https://mgeb.top",
}

session = requests.Session()
session.headers.update(HEADERS)

cf_session = None
if HAS_CLOUDSCRAPER:
    cf_session = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'mobile': False,
        }
    )


def clean_url(url):
    url = url.replace("\\/", "/")
    url = url.replace("\\", "")
    return url


def fetch_with_bypass(url, use_cf=False, max_retries=3):
    s = cf_session if (use_cf and cf_session) else session
    for attempt in range(max_retries):
        try:
            resp = s.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None


def fetch_tmdb_ids():
    print("[*] Buscando lista de filmes da API...")
    raw = fetch_with_bypass(API_MOVIE_URL)
    if not raw:
        print("[!] Erro ao acessar API de filmes")
        return []
    ids = json.loads(raw)
    print(f"[+] Total de filmes disponiveis: {len(ids)}")
    return ids


def extract_video_sources(html):
    sources = []

    title_match = re.search(r'var title\s*=\s*"([^"]+)"', html)
    title = title_match.group(1) if title_match else "Desconhecido"

    poster_match = re.search(r'var poster\s*=\s*"([^"]+)"', html)
    poster = poster_match.group(1) if poster_match else ""
    poster = clean_url(poster)

    sources_match = re.search(r'var sources\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if sources_match:
        raw_json = sources_match.group(1)
        raw_json = re.sub(r',\s*}', '}', raw_json)
        raw_json = re.sub(r',\s*\]', ']', raw_json)
        try:
            parsed = json.loads(raw_json)
            for s in parsed:
                file_url = clean_url(s.get("file", ""))
                sources.append({
                    "file": file_url,
                    "type": s.get("type", "mp4"),
                    "label": s.get("label", "Source"),
                })
        except json.JSONDecodeError:
            pass

    fallback_match = re.search(r'var fallbackUrl\s*=\s*"([^"]+)"', html)
    fallback_url = clean_url(fallback_match.group(1)) if fallback_match else ""

    return title, poster, sources, fallback_url


def pick_best_source(sources, fallback_url=""):
    seen_files = set()
    unique_sources = []
    for s in sources:
        f = s["file"]
        if f and f not in seen_files:
            seen_files.add(f)
            unique_sources.append(s)

    priority = {"mp4": 0, "hls": 1, "m3u8": 1, "webm": 2, "iframe": 3}
    sorted_s = sorted(unique_sources, key=lambda x: priority.get(x["type"], 99))

    if sorted_s:
        return sorted_s[0]
    if fallback_url:
        return {"file": fallback_url, "type": "iframe", "label": "Fallback"}
    return None


def fetch_movie_embed(tmdb_id, use_cf=False):
    url = EMBED_URL.format(tmdb_id)
    html = fetch_with_bypass(url, use_cf=use_cf)
    if not html:
        return None
    return extract_video_sources(html)


def decode_url_if_encoded(file_url):
    cleaned = unquote(file_url)
    return cleaned


def try_resolve_source(source):
    file_url = decode_url_if_encoded(source["file"])
    resolved = {"file": file_url, "type": source["type"], "label": source["label"]}

    if source["type"] in ("hls", "m3u8"):
        try:
            resp = session.get(file_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and b"#EXTM3U" in resp.content:
                lines = resp.text.strip().split("\n")
                best_url = None
                best_res = 0
                res_match = None
                for line in lines:
                    line = line.strip()
                    if line.startswith("#EXT-X-STREAM-INF"):
                        rm = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                        if rm:
                            res_match = int(rm.group(1)) * int(rm.group(2))
                        else:
                            res_match = None
                    elif line and not line.startswith("#"):
                        if res_match and res_match > best_res:
                            best_res = res_match
                            best_url = line
                            res_match = None
                        elif best_url is None:
                            best_url = line
                if best_url:
                    if best_url.startswith("http"):
                        resolved["file"] = best_url
                    else:
                        base = file_url[:file_url.rfind("/") + 1]
                        resolved["file"] = urljoin(base, best_url)
                    resolved["type"] = "m3u8"
        except Exception:
            pass

    return resolved


def sign_url(target_url):
    """Re-signa uma URL via sign.php do mgeb.top para token fresco"""
    try:
        r = requests.get(SIGN_URL, params={"url": target_url},
            headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("encrypted"):
                return data["encrypted"]
    except: pass
    return None

def generate_m3u(selected_movies):
    lines = ['#EXTM3U']
    for movie in selected_movies:
        tvg_id = movie.get("tmdb_id", "")
        tvg_name = movie.get("title", "Unknown")
        tvg_logo = movie.get("poster", "")
        source = movie.get("source", {})
        file_url = source.get("file", "")
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" group-title="MegaEmbed",{tvg_name}')
        lines.append(file_url)
    return "\n".join(lines)


def save_m3u(content, filename="megembed_playlist.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    m3u_name = filename.replace(".txt", ".m3u")
    if m3u_name != filename:
        with open(m3u_name, "w", encoding="utf-8") as f:
            f.write(content)
    return os.path.abspath(filename)


def save_json(movies, filename="megembed_movies.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
    return os.path.abspath(filename)


def upload_to_catbox(txt_path):
    print("[*] Enviando para Catbox.moe (servidor online)...")
    try:
        m3u_path = txt_path.replace(".txt", ".m3u")
        upload_path = m3u_path if os.path.exists(m3u_path) else txt_path
        filesize = os.path.getsize(upload_path)
        print(f"[*] Arquivo: {os.path.basename(upload_path)} ({filesize} bytes)")

        with open(upload_path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (os.path.basename(upload_path), f, "text/plain")},
                timeout=60
            )
        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            print(f"\n{'='*60}")
            print(f"  LINK PERMANENTE 24/7 (Catbox)")
            print(f"{'='*60}")
            print(f"\n[+] LINK M3U DIRETO:")
            print(f"    {url}")
            print(f"\n[*] Caracteristicas:")
            print(f"    - Funciona 24/7 sem seu PC ligado")
            print(f"    - Acessivel de qualquer lugar do mundo")
            print(f"    - Pode usar em TV, celular, PC")
            print(f"    - Nao precisa de login pra assistir")
            print(f"\n[*] IMPORTANTE: os links de video DENTRO da")
            print(f"    playlist expiram em algumas horas/dias.")
            print(f"    Para manter funcionando, rode o script")
            print(f"    novamente e gere uma nova playlist.")
            return url
        else:
            print(f"[!] Catbox erro HTTP {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.Timeout:
        print("[!] Timeout no Catbox")
    except requests.exceptions.ConnectionError as e:
        print(f"[!] Erro de conexao: {e}")
    except Exception as e:
        print(f"[!] Erro: {e}")
    print("[#] Salvo localmente como backup.")
    return None


def upload_to_github(content, filename, token, repo, branch="main"):
    api_url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    data = {
        "message": f"Atualizar {filename} - MegaEmbed Scraper",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        data["sha"] = sha

    r = requests.put(api_url, headers=headers, json=data)
    if r.status_code in (200, 201):
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{filename}"
        return raw_url
    else:
        raise Exception(f"GitHub upload failed: {r.status_code} {r.text}")


def try_refresh_urls(all_movies):
    """Tenta re-signar URLs via sign.php para estender tokens"""
    print("\n[*] Re-signando URLs via sign.php para tokens frescos...")
    refreshed = 0
    for m in all_movies:
        src = m.get("source", {})
        url = src.get("file", "")
        if url:
            from urllib.parse import urlparse, parse_qs
            signed = sign_url(url)
            if signed:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                ext = qs.get("ext", ["m3u8"])[0]
                file_path = qs.get("file", ["/master.m3u8"])[0]
                cdn_base = f"{parsed.scheme}://{parsed.netloc}/includes/hls.php"
                src["file"] = f"{cdn_base}?url={quote(signed)}&ext={ext}&file={file_path}"
                refreshed += 1
    print(f"[+] {refreshed} URLs re-signadas com tokens frescos")
    return all_movies

def upload_menu(m3u_content, txt_path, all_movies=None):
    print("\n" + "=" * 60)
    print("  HOSPEDAR PLAYLIST NA NUVEM (24/7)")
    print("  Links permanentes disponiveis mundialmente")
    print("=" * 60)
    print("\nEscolha onde hospedar:")
    print("  1 - Catbox.moe (sem login - recomendo!)")
    print("  2 - Re-signar URLs via sign.php + Catbox (recomendo!)")
    print("  3 - So local (pular)")
    choice = input("\n>> Escolha: ").strip()

    if choice in ("1", "2"):
        if choice == "2" and all_movies:
            all_movies = try_refresh_urls(all_movies)
            m3u_content_new = generate_m3u(all_movies)
            save_m3u(m3u_content_new, "megembed_playlist.txt")
            return upload_to_catbox("megembed_playlist.txt")
        return upload_to_catbox(txt_path)
    else:
        print("[#] Salvo apenas localmente.")
        return None


def main():
    print("=" * 60)
    print("  MEGEMBED SCRAPER - Extrator de Links Diretos")
    print("  Gera links de filmes do MegaEmbed (.txt pronto pra M3U)")
    print("=" * 60)

    ids = fetch_tmdb_ids()
    if not ids:
        print("[!] Nenhum filme encontrado. Saindo.")
        return
    total = len(ids)

    while True:
        try:
            qty = int(input(f"\n[*] Quantos filmes voce quer processar? (max {total}): "))
            if qty <= 0:
                print("[!] Digite um numero maior que 0")
                continue
            if qty > total:
                print(f"[!] Maximo disponivel: {total}. Usando {total}.")
                qty = total
            break
        except ValueError:
            print("[!] Digite um numero valido")

    start_from = 0
    while True:
        try:
            start_input = input(f"[*] Comecar a partir de qual posicao? (1-{total}, Enter=1): ").strip()
            if not start_input:
                break
            start_from = int(start_input) - 1
            if 0 <= start_from < total:
                break
            print(f"[!] Digite entre 1 e {total}")
        except ValueError:
            print("[!] Digite um numero valido")

    movies_to_scrape = ids[start_from:start_from + qty]
    print(f"\n[*] Processando {len(movies_to_scrape)} filmes (posicao {start_from+1} a {start_from+len(movies_to_scrape)})...\n")

    all_movies = []
    processed = 0
    errors = 0

    for tmdb_id in movies_to_scrape:
        processed += 1
        pct = (processed / len(movies_to_scrape)) * 100
        sys.stdout.write(f"\r[*] [{processed}/{len(movies_to_scrape)}] ({pct:.1f}%) TMDB: {tmdb_id}")
        sys.stdout.flush()

        result = fetch_movie_embed(tmdb_id)
        if not result:
            result = fetch_movie_embed(tmdb_id, use_cf=True)

        if result:
            title, poster, sources, fallback_url = result
            if sources or fallback_url:
                best = pick_best_source(sources, fallback_url)
                if best:
                    resolved = try_resolve_source(best)
                    all_movies.append({
                        "tmdb_id": str(tmdb_id),
                        "title": title,
                        "poster": poster,
                        "source": resolved,
                    })
                    continue

        errors += 1

    print(f"\n\n[+] Processados: {processed} | OK: {len(all_movies)} | Erros: {errors}")

    if not all_movies:
        print("[!] Nenhum video encontrado.")
        return

    print(f"[+] Filmes com links encontrados: {len(all_movies)}")

    print("\n" + "=" * 60)
    print("  SELECIONE OS FILMES PARA A PLAYLIST M3U")
    print("=" * 60)
    print("\nDigite os numeros separados por virgula (ex: 1,3,5)")
    print("Ou 'all' para selecionar todos")
    print("Ou 'json' para salvar como JSON")
    print("Ou 'q' para sair\n")

    for i, m in enumerate(all_movies):
        src_type = m["source"]["type"]
        src_label = m["source"]["label"]
        print(f"  [{i+1}] {m['title']}")
        print(f"       TMDB: {m['tmdb_id']} | Tipo: {src_type} | {src_label}")

    print()
    choice = input(">> Selecione: ").strip().lower()

    selected = []
    if choice == "all":
        selected = all_movies
    elif choice == "json":
        json_path = save_json(all_movies)
        print(f"[+] JSON salvo em: {json_path}")
        return
    elif choice == "q":
        print("[#] Saindo.")
        return
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
            for idx in indices:
                if 0 <= idx < len(all_movies):
                    selected.append(all_movies[idx])
        except ValueError:
            print("[!] Entrada invalida")
            return

    if not selected:
        print("[!] Nenhum filme selecionado")
        return

    print(f"\n[*] Gerando playlist M3U com {len(selected)} filmes...")
    m3u_content = generate_m3u(selected)
    filepath = save_m3u(m3u_content, "megembed_playlist.txt")
    print(f"[+] Playlist salva em: {filepath}")
    print(f"[+] Total de {len(selected)} filmes na playlist")

    upload_menu(m3u_content, filepath, all_movies)

    print("\n" + "=" * 60)
    print("  PRONTO! Link copiado acima.")
    print("  Use no seu player IPTV - funciona 24/7")
    print("=" * 60)
    input("\nPressione Enter para sair...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[#] Cancelado pelo usuario.")
        input("\nPressione Enter para sair...")
    except Exception as e:
        print(f"\n[!] Erro inesperado: {e}")
        input("\nPressione Enter para sair...")
