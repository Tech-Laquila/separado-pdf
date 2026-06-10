from fastapi import FastAPI, File, UploadFile, HTTPException
from pypdf import PdfReader, PdfWriter
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
    """Retorna as primeiras n linhas não vazias da página (área do título)."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return " ".join(linhas[:n_linhas])


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


@app.post("/separar")
async def separar(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")

    conteudo = await file.read()
    reader = PdfReader(io.BytesIO(conteudo))
    total = len(reader.pages)

    secoes = detectar_paginas(reader)

    if not secoes:
        raise HTTPException(status_code=422, detail="Nenhuma seção reconhecida no PDF.")

    paginas_auditoria = secoes.get("auditoria", [total - 1])
    base = file.filename.removesuffix(".pdf")

    documentos = []
    for tipo in ["contrato", "procuracao", "declaracao"]:
        if tipo in secoes:
            indices = secoes[tipo] + paginas_auditoria
            documentos.append({
                "tipo": tipo,
                "nome_arquivo": f"{base}_{tipo}.pdf",
                "paginas": len(indices),
                "conteudo_base64": gerar_pdf_base64(reader, indices),
            })

    return {"arquivo_original": file.filename, "documentos": documentos}


@app.get("/health")
def health():
    return {"status": "ok"}
