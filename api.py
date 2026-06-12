from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
import httpx
import io
import base64

app = FastAPI(title="Separador de Documentos PDF")

INICIO_SECAO = {
    "contrato":   ["CONTRATO DE", "Cláusula Primeira"],
    "procuracao": ["PROCURAÇÃO", "PROCURACAO", "AD JUDICIA", "OUTORGANTE"],
    "declaracao": ["HIPOSSUFICIÊNCIA", "HIPOSSUFICIENCIA", "gratuidade judici"],
    "auditoria":  ["autentique", "Trilha de auditoria", "Hash SHA256", "Identificador:"],
}


def _titulo_pagina(texto: str, n_linhas: int = 5) -> str:
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    titulo = " ".join(linhas[:n_linhas])
    return " ".join(titulo.split())


def detectar_paginas(reader: PdfReader) -> dict[str, list[int]]:
    total = len(reader.pages)
    paginas: dict[int, str | None] = {}

    for i in range(total):
        texto = reader.pages[i].extract_text() or ""
        titulo = _titulo_pagina(texto)
        encontrado = None
        for nome, chaves in INICIO_SECAO.items():
            if any(c.lower() in titulo.lower() for c in chaves):
                encontrado = nome
                break
        paginas[i] = encontrado

    ultima = None
    for i in range(total):
        if paginas[i]:
            ultima = paginas[i]
        elif ultima:
            paginas[i] = ultima

    resultado: dict[str, list[int]] = {}
    for i, nome in paginas.items():
        if nome:
            resultado.setdefault(nome, []).append(i)

    return resultado


def gerar_pdf_base64(reader: PdfReader, indices: list[int]) -> str:
    writer = PdfWriter()
    for idx in indices:
        writer.add_page(reader.pages[idx])
    buf = io.BytesIO()
    writer.write(buf)
    return base64.b64encode(buf.getvalue()).decode()


def _processar(conteudo: bytes, nome_base: str) -> dict:
    reader = PdfReader(io.BytesIO(conteudo))
    total = len(reader.pages)
    secoes = detectar_paginas(reader)

    if not secoes:
        raise HTTPException(status_code=422, detail="Nenhuma seção reconhecida no PDF.")

    paginas_auditoria = secoes.get("auditoria", [total - 1])

    documentos = []
    for tipo in ["contrato", "procuracao", "declaracao"]:
        if tipo in secoes:
            indices = secoes[tipo] + paginas_auditoria
            documentos.append({
                "tipo": tipo,
                "nome_arquivo": f"{nome_base}_{tipo}.pdf",
                "paginas": len(indices),
                "conteudo_base64": gerar_pdf_base64(reader, indices),
            })

    if not documentos:
        raise HTTPException(status_code=422, detail="Nenhum documento reconhecido (contrato/procuração/declaração).")
    return {"arquivo_original": nome_base, "documentos": documentos}


# ── Endpoint 1: upload de arquivo (teste local / genérico) ──────────────────
@app.post("/separar")
async def separar(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")
    conteudo = await file.read()
    return _processar(conteudo, file.filename.removesuffix(".pdf"))


# ── Endpoint 2: recebe URL (usado pelo n8n) ──────────────────────────────────
class SepararUrlBody(BaseModel):
    url: str
    nome: str = "documento"


@app.post("/separar-url")
async def separar_url(body: SepararUrlBody):
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(body.url, follow_redirects=True)
    if resp.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Erro ao baixar PDF: HTTP {resp.status_code}")
    nome_base = body.nome.removesuffix(".pdf")
    return _processar(resp.content, nome_base)


@app.get("/health")
def health():
    return {"status": "ok"}
