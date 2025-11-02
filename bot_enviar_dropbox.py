import os
import subprocess
import asyncio
import discord
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import dropbox
import requests

# Tokens via variáveis de ambiente (não comitar tokens no código)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Dropbox App info + Refresh token (definidos no ambiente)
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")

if not DISCORD_TOKEN:
    print("⚠️ DISCORD_TOKEN não definido. O bot Discord não será conectado.")

if not DROPBOX_APP_KEY or not DROPBOX_APP_SECRET or not DROPBOX_REFRESH_TOKEN:
    print(
        "⚠️ Variáveis do Dropbox ausentes. Endpoint de upload Dropbox falhará sem elas."
    )

IGNORAR_CATEGORIAS = [
    "╭╼ 🌐Uploader Mode",
    "╭╼ 👥Chat",
    "╭╼ 💎ADM chat",
    "╭╼ 📫Welcome",
    "⭒⇆◁ ❚❚ ▷↻ ⭒ 🔊 ▂▃▅▉ 100%⭒",
]

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

client = discord.Client(intents=intents)

app = FastAPI()
_collect_lock = asyncio.Lock()


def limpar_nome(nome):
    return nome.replace("/", "-").replace("\\", "-").replace(":", "-")


# 🔹 Função para gerar access token usando refresh token
def obter_access_token():
    if not all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN]):
        raise RuntimeError("Variáveis do Dropbox não definidas corretamente.")

    url = "https://api.dropbox.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET,
    }
    resp = requests.post(url, data=data)
    resp.raise_for_status()
    access_token = resp.json().get("access_token")
    if not access_token:
        raise RuntimeError("Falha ao obter access token do Dropbox")
    return access_token


async def coletar_links():
    if DISCORD_TOKEN is None:
        raise RuntimeError("DISCORD_TOKEN não definido")

    links_por_categoria = {}

    for guild in client.guilds:
        for canal in guild.text_channels:
            if canal.category is None or canal.category.name in IGNORAR_CATEGORIAS:
                continue

            try:
                links_salvos = set()
                async for mensagem in canal.history(limit=None, oldest_first=True):
                    for anexo in mensagem.attachments:
                        links_salvos.add(anexo.url)
                if links_salvos:
                    categoria_nome = canal.category.name
                    canal_nome = canal.name
                    if categoria_nome not in links_por_categoria:
                        links_por_categoria[categoria_nome] = []
                    links_por_categoria[categoria_nome].append(
                        (canal.position, canal_nome, sorted(links_salvos))
                    )
            except Exception as e:
                print(f"⚠️ Erro no canal {canal.name}: {e}")

    links_por_canal = []
    for guild in client.guilds:
        for categoria in guild.categories:
            if categoria.name in IGNORAR_CATEGORIAS:
                continue
            if categoria.name in links_por_categoria:
                canais = sorted(links_por_categoria[categoria.name], key=lambda x: x[0])
                for _, canal_nome, links in canais:
                    links_por_canal.append(f"# {categoria.name} / {canal_nome}\n")
                    for link in links:
                        links_por_canal.append(link + "\n")
                    links_por_canal.append("\n")

    with open("links_dos_arquivos.txt", "w", encoding="utf-8") as f:
        f.writelines(links_por_canal)

    print("✅ Coleta de links concluída!")

    gerar_html_audios("links_dos_arquivos.txt", "links_dos_arquivos.html")
    print("✅ HTML gerado: links_dos_arquivos.html")


def gerar_html_audios(input_txt, output_txt):
    html_output = [
        '<!doctype html>\n<html lang="pt-br">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>Links de Áudios</title>\n"
        "<style>\n"
        "body{font-family:Arial,Helvetica,sans-serif;padding:16px}\n"
        "button{margin:0;padding:8px 12px;border-radius:20px;border:2px solid #333;background:#f5f5f5}\n"
        ".album-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}\n"
        ".album-block{margin-bottom:14px}\n"
        ".album-content{padding-left:8px;border-left:2px solid #ddd}\n"
        ".track{margin:8px 0}\n"
        "</style>\n"
        # incluir JSZip e FileSaver via CDN
        '<script src="https://cdn.jsdelivr.net/npm/jszip@3.10.0/dist/jszip.min.js"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/file-saver@2.0.5/dist/FileSaver.min.js"></script>\n'
        "<script>\n"
        "function toggleAlbum(id) {\n"
        "  const div = document.getElementById(id);\n"
        "  div.style.display = (div.style.display === 'none' || div.style.display==='') ? 'block' : 'none';\n"
        "}\n\n"
        "function filterAlbums() {\n"
        "  const q = document.getElementById('search').value.toLowerCase().trim();\n"
        "  document.querySelectorAll('.album-block').forEach(b => {\n"
        "    const name = (b.dataset.album || '').toLowerCase();\n"
        "    b.style.display = (!q || name.includes(q)) ? 'block' : 'none';\n"
        "  });\n"
        "}\n\n"
        "async function downloadAlbum(id, btn) {\n"
        "  const div = document.getElementById(id);\n"
        "  const tracks = Array.from(div.querySelectorAll('audio source')).map(s=>s.src);\n"
        "  if(tracks.length===0){alert('Nenhuma faixa encontrada neste álbum.');return}\n"
        "  if(!confirm('Baixar ' + tracks.length + ' arquivos como ZIP?')) return;\n"
        "  btn.disabled = true; const originalText = btn.textContent; btn.textContent = 'Preparando...';\n"
        "  const zip = new JSZip();\n"
        "  for(let i=0;i<tracks.length;i++){\n"
        "    const url = tracks[i];\n"
        "    try{\n"
        "      btn.textContent = `Baixando ${i+1}/${tracks.length}...`;\n"
        "      const resp = await fetch(url);\n"
        "      if(!resp.ok) throw new Error('Falha ao baixar: '+resp.status);\n"
        "      const blob = await resp.blob();\n"
        "      let name = url.split('/').pop().split('?')[0] || `track_${i+1}`;\n"
        "      zip.file(name, blob);\n"
        "    }catch(err){\n"
        "      console.error('Erro fetch', url, err);\n"
        "      alert('Erro ao baixar alguns arquivos. Verifique CORS ou tente baixar manualmente.');\n"
        "    }\n"
        "  }\n"
        "  btn.textContent = 'Criando ZIP...';\n"
        "  try{\n"
        "    const content = await zip.generateAsync({type:'blob'});\n"
        "    saveAs(content, id + '.zip');\n"
        "  }catch(err){\n"
        "    console.error('Erro ao gerar ZIP', err); alert('Erro ao gerar ZIP: '+err);\n"
        "  }\n"
        "  btn.disabled = false; btn.textContent = originalText;\n"
        "}\n</script>\n</head>\n<body>\n"
        "<h1>Álbuns e Faixas</h1>\n"
        '<input id="search" type="search" placeholder="Buscar álbum..." oninput="filterAlbums()" style="width:100%;padding:8px;margin-bottom:12px">\n\n'
    ]
    artista_album = None
    album_id = 1

    with open(input_txt, "r", encoding="utf-8") as file:
        linhas = [linha.strip() for linha in file if linha.strip()]

    faixa_num = 1
    for linha in linhas:
        if linha.startswith("#"):
            if artista_album is not None:
                # fecha album-content e bloco
                html_output.append("  </div>\n</div>\n\n")
            artista_album = linha[1:].strip()
            div_id = f"album{album_id}"
            safe_album = artista_album.replace('"', "'")
            html_output.append(
                f'<div class="album-block" data-album="{safe_album}">\n'
                f'  <div class="album-row">\n'
                f"    <button onclick=\"toggleAlbum(\\'{div_id}\\')\">Mostrar/Ocultar {safe_album}</button>\n"
                f"    <button onclick=\"downloadAlbum(\\'{div_id}\\', this)\">Baixar álbum</button>\n"
                f"  </div>\n"
                f'  <div id="{div_id}" class="album-content" style="display:none;padding-left:8px;border-left:2px solid #ddd;margin-bottom:12px">\n'
                f"    <h2>{safe_album}</h2>\n"
            )
            album_id += 1
            faixa_num = 1
        else:
            link = linha
            if "/" in link:
                nome_com_extensao = link.split("/")[-1]
                if "." in nome_com_extensao:
                    nome_arquivo = nome_com_extensao.rsplit(".", 1)[0]
                    ext = nome_com_extensao.rsplit(".", 1)[1]
                else:
                    nome_arquivo = nome_com_extensao
                    ext = ""
            else:
                nome_arquivo = f"Faixa {faixa_num}"
                ext = ""

            safe_title = nome_arquivo.replace('"', "'")
            bloco_html = (
                f'<div class="track" data-title="{safe_title}">\n'
                f"  <p>{nome_arquivo}</p>\n"
                f'  <audio controls preload="none">\n'
                f'    <source src="{link}" type="audio/{ext if ext else "mpeg"}">\n'
                f"  </audio>\n"
                f"</div>\n"
            )
            html_output.append(bloco_html)
            faixa_num += 1

    if artista_album is not None:
        html_output.append("  </div>\n</div>\n")

    html_output.append("\n</body>\n</html>\n")

    with open(output_txt, "w", encoding="utf-8") as file:
        file.writelines(html_output)


@client.event
async def on_ready():
    print(f"✅ Bot conectado como {client.user}")


@app.post("/collect")
async def trigger_collect():
    if DISCORD_TOKEN is None:
        raise HTTPException(
            status_code=500, detail="DISCORD_TOKEN não definido no ambiente"
        )

    if not client.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Bot Discord não está conectado ainda. Aguarde inicialização.",
        )

    if _collect_lock.locked():
        return JSONResponse(
            {"status": "busy", "detail": "Coleta já em execução"}, status_code=202
        )

    async with _collect_lock:
        try:
            await coletar_links()
        except Exception as e:
            print(f"Erro na coleta: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok", "message": "Coleta finalizada, arquivos gerados"}


@app.post("/upload_dropbox")
async def upload_dropbox(
    path_local: str = "links_dos_arquivos.html",
    caminho_dropbox: str = "/links_dos_arquivos.html",
):
    if not all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN]):
        raise HTTPException(
            status_code=500, detail="Configuração do Dropbox incompleta"
        )

    if not os.path.exists(path_local):
        raise HTTPException(
            status_code=404, detail=f"Arquivo local não encontrado: {path_local}"
        )

    try:
        access_token = obter_access_token()
        dbx = dropbox.Dropbox(access_token)
        with open(path_local, "rb") as f:
            dbx.files_upload(
                f.read(), caminho_dropbox, mode=dropbox.files.WriteMode.overwrite
            )
    except Exception as e:
        print(f"Erro no upload Dropbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # tenta obter link compartilhado (se existir)
    try:
        links = dbx.sharing_list_shared_links(path=caminho_dropbox).links
        if links:
            link = links[0].url
            # prefira raw para embedding direto
            return {"status": "ok", "url": link.replace("?dl=0", "?raw=1")}
        else:
            return {
                "status": "ok",
                "message": "Upload concluído, link não encontrado automaticamente (crie no Dropbox se necessário).",
            }
    except Exception:
        return {
            "status": "ok",
            "message": "Upload concluído, não foi possível listar links (permissões).",
        }


@app.api_route("/collect_and_upload", methods=["GET", "POST"])
async def collect_and_upload():
    # combina coletar_links + upload_dropbox
    if DISCORD_TOKEN is None:
        raise HTTPException(
            status_code=500, detail="DISCORD_TOKEN não definido no ambiente"
        )

    if _collect_lock.locked():
        return JSONResponse(
            {"status": "busy", "detail": "Coleta já em execução"}, status_code=202
        )

    async with _collect_lock:
        try:
            await coletar_links()
        except Exception as e:
            print(f"Erro na coleta: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # após gerar HTML, faz upload
    return await upload_dropbox()


@app.get("/links")
async def get_links():
    path = "links_dos_arquivos.html"
    if os.path.exists(path):
        return FileResponse(
            path, media_type="text/html", filename="links_dos_arquivos.html"
        )
    raise HTTPException(
        status_code=404,
        detail="Arquivo HTML não encontrado. Execute /collect primeiro.",
    )


@app.get("/status")
async def status():
    return {"connected": client.is_ready(), "collect_busy": _collect_lock.locked()}


# Inicializa o bot do Discord em background quando a FastAPI sobe
@app.on_event("startup")
async def startup_event():
    if DISCORD_TOKEN is None:
        print("⚠️ Token ausente: o bot Discord não será conectado.")
        return
    loop = asyncio.get_event_loop()
    loop.create_task(client.start(DISCORD_TOKEN))
    print("🔌 Iniciando conexão do bot Discord em background...")


@app.on_event("shutdown")
async def shutdown_event():
    if client.is_ready():
        await client.close()
    print("⏹️ Aplicação finalizando, bot desconectado se estava conectado.")


# Roda o bot para gerar o arquivo txt
subprocess.run(["python", "bot_list_links.py"], check=True)

# Faz upload pro Dropbox usando refresh token
arquivo_local = "links_dos_arquivos.html"
caminho_dropbox = "/links_dos_arquivos.html"

try:
    access_token = obter_access_token()
    dbx = dropbox.Dropbox(access_token)
    with open(arquivo_local, "rb") as f:
        dbx.files_upload(
            f.read(), caminho_dropbox, mode=dropbox.files.WriteMode.overwrite
        )
    print("✅ Upload concluído para o Dropbox!")

    # Tenta pegar link existente
    links = dbx.sharing_list_shared_links(path=caminho_dropbox).links
    if links:
        link = links[0].url
        print("🔗 Link existente:", link.replace("?dl=0", "?raw=1"))
    else:
        print("ℹ️ Nenhum link encontrado — crie um manualmente no Dropbox.")
except Exception as e:
    print("⚠️ Erro no upload Dropbox:", e)
    print("   Verifique se as variáveis de ambiente estão corretas ou se há permissão.")
