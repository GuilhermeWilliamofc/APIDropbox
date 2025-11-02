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
    print("⚠️ Variáveis do Dropbox ausentes. Endpoint de upload Dropbox falhará sem elas.")

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
        "client_secret": DROPBOX_APP_SECRET
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
        "<script>\n"
        "function toggleAlbum(id) {\n"
        "  const div = document.getElementById(id);\n"
        "  div.style.display = div.style.display === 'none' ? 'block' : 'none';\n"
        "}\n"
        "</script>\n\n"
    ]
    artista_album = None
    album_id = 1

    with open(input_txt, "r", encoding="utf-8") as file:
        linhas = [linha.strip() for linha in file if linha.strip()]

    faixa_num = 1
    for linha in linhas:
        if linha.startswith("#"):
            if artista_album is not None:
                html_output.append("</div>\n\n")
            artista_album = linha[1:].strip()
            div_id = f"album{album_id}"
            html_output.append(
                f"<button onclick=\"toggleAlbum('{div_id}')\">Mostrar/Ocultar {artista_album}</button><br>\n"
                f'<div id="{div_id}" style="display:none;">\n'
                f"<h2>{artista_album}</h2>\n"
            )
            album_id += 1
            faixa_num = 1
        else:
            link = linha
            if "/" in link:
                nome_com_extensao = link.split("/")[-1]
                if "." in nome_com_extensao:
                    nome_arquivo = nome_com_extensao.rsplit(".", 1)[0]
                else:
                    nome_arquivo = nome_com_extensao
            else:
                nome_arquivo = f"Faixa {faixa_num}"

            bloco_html = f"""<p>{nome_arquivo}</p>
<audio controls preload="none">
    <source src="{link}" type="audio/ogg; codecs=opus">
</audio>\n"""
            html_output.append(bloco_html)
            faixa_num += 1

    if artista_album is not None:
        html_output.append("</div>\n")

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
        dbx.files_upload(f.read(), caminho_dropbox, mode=dropbox.files.WriteMode.overwrite)
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
