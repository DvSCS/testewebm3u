# DEPLOY - MegaEmbed Proxy (Render.com)

## Como funciona

O `web_scraper.py` cria um servidor proxy que:
1. Gera uma playlist com URLs do tipo `/proxy/{TMDB_ID}`
2. Quando alguem acessa `/proxy/{TMDB_ID}`, ele:
   - Scrapeia o embed page do mgeb.top (token fresco)
   - Opcionalmente re-signa via `sign.php` para estender a validade
   - Redireciona (302) para o video com token valido

**Nao precisa de GitHub Actions, nem de PC ligado. Token gerado sob demanda.**

## Deploy no Render.com (gratis)

1. Crie conta em https://render.com
2. Clique "New +" > "Web Service"
3. Conecte seu repositorio ou faça upload manual
4. Configure:
   - **Name**: megembed-proxy
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn web_scraper:app`
   - **Plan**: Free
5. Deploy

## Manter acordado (opcional)

O Render free dorme apos 15 min de inatividade.
Use https://uptimerobot.com para pingar a cada 5 min:
```
https://seuapp.onrender.com/health
```

## Playlist final

Apos deploy, sua playlist sera:
```
https://seuapp.onrender.com/playlist.m3u
```

Cada link na playlist aponta para `/proxy/{TMDB_ID}`
que gera um token FRESCO na hora do acesso.

## Alternativa: Catbox manual

Rode `python scraper_auto.py` com `--sign` para re-signar URLs
antes do upload: `python scraper_auto.py --qty 100 --sign`
