import os
import subprocess
import asyncio
import discord
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import dropbox

# Tokens via variáveis de ambiente (não comitar tokens no código)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")
if not DISCORD_TOKEN:
    print("⚠️ DISCORD_TOKEN não definido. O bot Discord não será conectado.")
if not DROPBOX_TOKEN:
    print("⚠️ DROPBOX_TOKEN não definido. Endpoint de upload Dropbox falhará sem token.")

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
    if DROPBOX_TOKEN is None:
        raise HTTPException(
            status_code=500, detail="DROPBOX_TOKEN não definido no ambiente"
        )

    if not os.path.exists(path_local):
        raise HTTPException(
            status_code=404, detail=f"Arquivo local não encontrado: {path_local}"
        )

    try:
        dbx = dropbox.Dropbox(DROPBOX_TOKEN)
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


@app.post("/collect_and_upload")
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

# Faz upload pro Dropbox (TOKEN)
dbx = dropbox.Dropbox(
    "sl.u.AGGNnHlzcjFJty-xQgO35yMpCfEjfjJ-gVeQfcj-c_o3blNLwDWxblOGhiAZjxBNz3fu-PNHysN5LskKUlXGPbd6tIVW220cdDzxOZ4dIYRblJLcYuuR6p22TT6Vq-qHyBksnwer7OxZMOolFNWcorAD0c1eDc0wbvxXMpAQfTxlMgZAMZ6N8O7eG4AZB6j-2KFWywJAe0lbMXKSqSfr_sR_H75dySveWDmJZsY5WlLjXxrRQcb289NPYZhIt_I52gh2j_QDf1kKiWR470B818az_m9rKbtPT-k05ZN3tEHIV5VG50bsjCLqoOBxe2jcMtEgxeHCMC6CoiHFJ9WF4DuKvm8N41a1qSnROm-WUDT_fyGL-CQ7-FHnOavEBvGDqnh7ZZgKiIBMqmRb171RgB0oDQLNblE-wMxYrulTpbyl7vRHRq8lUEvW8E6LTjNqnrim68-otGVhN4B-jgyElphJgwIkMB-foCdbfQ1PX5ZMIzPoeoopcGzMoBF54aBBDTWrE8JKKHr8uFkcee_yXsVtENm8W6eOlq8qUB4ZYDXUCFumrrSZVHCZ7wT_DDiZp2910CCSZWAnVEwfV28EuxBeO74KWvbg12mrOtZ4xRcoiW1w7-a4FdMFaoxn7hL54OwyIMVW3n44yrkLDAxgjadEDuQUNo4AHOsZZ2Y86sfoKIPDv_8ZTqGyNDONw5Jzr0rJJ-RmsJL0Oj59vOa_7KoEhLVPCRmFNcMxEzWsA8TbfO_d6hd4yzCREtsZhTHfiFr6ajqrINfKj6j5idaPvTG18LMRrJ59NuuQsHoLyRYsWsqhbQCTLO16L0C_Pal_mIs0a1CDqOMgfECj1wsMngJ6iV6qqDH3qJGwofWs9ow1w_WboWx1Ev8suO5jGT6MsalrqDWFb_jrY-ZTF-KXHmYKAoNNlTKK-LP_pV51KaHQkVnPOjEiUgzm6cBzSHdihvahGG9NUbYx3SgFY9nxhhpFHl_xc9ySJ2dZ4dA3xPqj1gR_gpGLo7x8qvdgosEZKtkx7t6uih4JVbEHi31fO-64lFHJt4tObgOsgywXeoGS7fafHC6aUEbn2aNfJttqA5JBmfuoczZZTK2ZjxMISUO1TGuLaBVHqFYyyzfFptAeO-3YZ_Xnw8ETp6SERusAhEDLENdNCU-559m1_lXlWOCP8le_VLVZAgfsbAJ46aoHByc37QmQQU0DpGhdLAK81tEMvO1wYk7EVz7uEBHNpBSRrXCL04JRzjKmR2gaEXR2TOKkU63xvuozoh3sKvAnw_y-hCNjTyuQwcBWcT8scsZigwHNnDr3hm6z7pfP3pczUQ9zFtpym80lAUX7en68rzZfeiwpwzByqEhhdp0_AlaV-yCdPDkp1Ljpp7kKQ2r6xkm_gjuNkwxOLilUtAbGxPcnSBPDKzggTDkyxPXUbOIIC475m4UJ1EXBVvtwND_8Y74Peu8nL-oO4VyqPqMcsu8"
)

arquivo_local = "links_dos_arquivos.html"
caminho_dropbox = "/links_dos_arquivos.html"

with open(arquivo_local, "rb") as f:
    dbx.files_upload(f.read(), caminho_dropbox, mode=dropbox.files.WriteMode.overwrite)

print("✅ Upload concluído para o Dropbox!")

# Tenta pegar link existente (sem precisar criar)
try:
    links = dbx.sharing_list_shared_links(path=caminho_dropbox).links
    if links:
        link = links[0].url
        print("🔗 Link existente:", link.replace("?dl=0", "?raw=1"))
    else:
        print("ℹ️ Nenhum link encontrado — crie um manualmente no Dropbox.")
except Exception as e:
    print("⚠️ Não foi possível listar links. Provável limitação de permissões.")
    print("   Basta criar o link manualmente no Dropbox uma vez.")
