#!/usr/bin/env python3
"""
Script para separar automaticamente o PDF de documentos advocatícios.
Detecta automaticamente os documentos pelas palavras-chave no texto.
A ultima pagina (relatorio de auditoria) e adicionada a todos os documentos.

Uso:
    python separar_documentos.py <arquivo.pdf> [pasta_saida]

Exemplo:
    python separar_documentos.py contrato.pdf ./documentos_separados/
"""

import os
import sys
from pypdf import PdfReader, PdfWriter

INICIO_SECAO = {
    "contrato":   ["CONTRATO DE", "Cláusula Primeira"],
    "procuracao": ["PROCURAÇÃO", "PROCURACAO", "AD JUDICIA", "OUTORGANTE"],
    "declaracao": ["HIPOSSUFICIÊNCIA", "HIPOSSUFICIENCIA", "gratuidade judici"],
    "auditoria":  ["autentique", "Trilha de auditoria", "Hash SHA256", "Identificador:"],
}

def texto_pagina(reader, idx):
    return reader.pages[idx].extract_text() or ""

def titulo_pagina(texto, n_linhas=5):
    """Retorna as primeiras n linhas nao vazias da pagina (area do titulo)."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return " ".join(linhas[:n_linhas])

def detectar_paginas(reader):
    """
    Retorna um dicionario: nome_secao -> lista de indices de paginas.
    Cada pagina e atribuida a secao cuja palavra-chave aparece no seu texto.
    Se nenhuma palavra-chave bater, a pagina e agrupada com a secao anterior.
    """
    total = len(reader.pages)
    paginas = {}

    for i in range(total):
        texto = texto_pagina(reader, i)
        titulo = titulo_pagina(texto)
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

    resultado = {}
    for i, nome in paginas.items():
        if nome:
            resultado.setdefault(nome, []).append(i)

    return resultado

def salvar_pdf(reader, paginas, caminho):
    writer = PdfWriter()
    for idx in paginas:
        writer.add_page(reader.pages[idx])
    with open(caminho, "wb") as f:
        writer.write(f)
    print(f"  Salvo: {caminho}  ({len(paginas)} pagina(s): {[p+1 for p in paginas]})")

def separar(caminho_pdf, pasta_saida=None):
    if not os.path.exists(caminho_pdf):
        print(f"Erro: arquivo nao encontrado: {caminho_pdf}")
        sys.exit(1)

    if pasta_saida is None:
        pasta_saida = os.path.dirname(os.path.abspath(caminho_pdf))
    os.makedirs(pasta_saida, exist_ok=True)

    reader = PdfReader(caminho_pdf)
    total = len(reader.pages)
    print(f"PDF: {caminho_pdf} ({total} paginas)")

    secoes = detectar_paginas(reader)
    print(f"Secoes detectadas: { {k: [p+1 for p in v] for k,v in secoes.items()} }")

    paginas_auditoria = secoes.get("auditoria", [total - 1])
    base = os.path.splitext(os.path.basename(caminho_pdf))[0]

    print("\nGerando arquivos:")
    for nome in ["contrato", "procuracao", "declaracao"]:
        if nome in secoes:
            paginas = secoes[nome] + paginas_auditoria
            saida = os.path.join(pasta_saida, f"{base}_{nome}.pdf")
            salvar_pdf(reader, paginas, saida)

    print("\nPronto!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    separar(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
