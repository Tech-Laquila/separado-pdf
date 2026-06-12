from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
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

LABELS = {
    "contrato": "Contrato",
    "procuracao": "Procuração",
    "declaracao": "Declaração",
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
    documentos = [
        {
            "tipo": "original",
            "nome_arquivo": f"{nome_base}.pdf",
            "paginas": total,
            "conteudo_base64": base64.b64encode(conteudo).decode(),
        }
    ]
    for tipo in ["contrato", "procuracao", "declaracao"]:
        if tipo in secoes:
            indices = secoes[tipo] + paginas_auditoria
            documentos.append({
                "tipo": tipo,
                "nome_arquivo": f"{nome_base}_{tipo}.pdf",
                "paginas": len(indices),
                "conteudo_base64": gerar_pdf_base64(reader, indices),
            })
    if len(documentos) == 1:
        raise HTTPException(status_code=422, detail="Nenhum documento reconhecido (contrato/procuração/declaração).")
    return {"arquivo_original": nome_base, "documentos": documentos}


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Separador de Documentos PDF</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 40px 16px; }
  h1 { font-size: 1.5rem; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; }
  p.sub { color: #6b7280; font-size: 0.9rem; margin-bottom: 32px; }
  #drop-area { width: 100%; max-width: 560px; border: 2px dashed #c5c8d0; border-radius: 16px; background: #fff; padding: 48px 24px; text-align: center; cursor: pointer; transition: border-color .2s, background .2s; }
  #drop-area.hover { border-color: #4f46e5; background: #eef2ff; }
  #drop-area svg { width: 48px; height: 48px; color: #9ca3af; margin-bottom: 16px; }
  #drop-area p { color: #6b7280; font-size: 0.95rem; }
  #drop-area strong { color: #4f46e5; }
  #file-input { display: none; }
  #status { margin-top: 24px; font-size: 0.95rem; color: #6b7280; min-height: 24px; }
  #results { width: 100%; max-width: 560px; margin-top: 24px; display: flex; flex-direction: column; gap: 12px; }
  .card { background: #fff; border-radius: 12px; padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card-info { display: flex; flex-direction: column; gap: 2px; }
  .card-tipo { font-weight: 600; color: #1a1a2e; font-size: 1rem; }
  .card-meta { font-size: 0.8rem; color: #9ca3af; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; margin-right: 8px; }
  .badge-original { background: #f3f4f6; color: #374151; }
  .badge-contrato { background: #dbeafe; color: #1d4ed8; }
  .badge-procuracao { background: #ede9fe; color: #6d28d9; }
  .badge-declaracao { background: #d1fae5; color: #065f46; }
  .btn-download { background: #4f46e5; color: #fff; border: none; border-radius: 8px; padding: 8px 18px; font-size: 0.88rem; font-weight: 600; cursor: pointer; text-decoration: none; transition: background .15s; white-space: nowrap; }
  .btn-download:hover { background: #4338ca; }
  .error { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; padding: 12px 16px; max-width: 560px; width: 100%; margin-top: 16px; font-size: 0.9rem; }
  .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid #e5e7eb; border-top-color: #4f46e5; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<h1>Separador de Documentos PDF</h1>
<p class="sub">Arraste ou selecione um contrato assinado para separar os documentos</p>
<div id="drop-area" onclick="document.getElementById('file-input').click()">
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>
  </svg>
  <p><strong>Clique aqui</strong> ou arraste o PDF</p>
  <p style="font-size:.8rem;margin-top:6px;color:#c5c8d0">Somente arquivos .pdf</p>
</div>
<input type="file" id="file-input" accept=".pdf">
<div id="status"></div>
<div id="results"></div>
<script>
const drop = document.getElementById('drop-area');
const input = document.getElementById('file-input');
const status = document.getElementById('status');
const results = document.getElementById('results');
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('hover'); });
drop.addEventListener('dragleave', () => drop.classList.remove('hover'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('hover'); const file = e.dataTransfer.files[0]; if (file) processar(file); });
input.addEventListener('change', () => { if (input.files[0]) processar(input.files[0]); });
const LABELS = { original: 'Original', contrato: 'Contrato', procuracao: 'Procuração', declaracao: 'Declaração' };
const BADGES = { original: 'badge-original', contrato: 'badge-contrato', procuracao: 'badge-procuracao', declaracao: 'badge-declaracao' };
async function processar(file) {
  results.innerHTML = '';
  status.innerHTML = '<span class="spinner"></span>Processando <strong>' + file.name + '</strong>…';
  const form = new FormData();
  form.append('file', file);
  try {
    const resp = await fetch('/separar', { method: 'POST', body: form });
    const data = await resp.json();
    if (!resp.ok) { status.innerHTML = ''; results.innerHTML = '<div class="error">Erro: ' + (data.detail || 'Falha ao processar o PDF.') + '</div>'; return; }
    status.innerHTML = 'Separação concluída — <strong>' + data.documentos.length + ' documento(s)</strong> encontrado(s)';
    data.documentos.forEach(doc => {
      const bytes = atob(doc.conteudo_base64);
      const arr = new Uint8Array(bytes.length);
      for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
      const blob = new Blob([arr], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = '<div class="card-info"><div class="card-tipo"><span class="badge ' + BADGES[doc.tipo] + '">' + (LABELS[doc.tipo] || doc.tipo) + '</span></div><div class="card-meta">' + doc.nome_arquivo + ' &nbsp;·&nbsp; ' + doc.paginas + ' página(s)</div></div><a class="btn-download" href="' + url + '" download="' + doc.nome_arquivo + '">Baixar</a>';
      results.appendChild(card);
    });
  } catch (err) { status.innerHTML = ''; results.innerHTML = '<div class="error">Erro de conexão. Verifique se o servidor está rodando.</div>'; }
}
</script>
</body>
</html>"""


@app.post("/separar")
async def separar(file: UploadFile = File(...)):
    nome = file.filename or "documento"
    if not nome.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")
    conteudo = await file.read()
    return _processar(conteudo, nome.removesuffix(".pdf"))


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
