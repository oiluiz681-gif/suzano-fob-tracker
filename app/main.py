import os
import shutil
import json
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import get_connection, init_db

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app = FastAPI(title="Suzano - Gestão de Coletas FOB e Divergências")

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Inicializa banco de dados e dados de exemplo
init_db()

def gerar_numero_protocolo():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    total = cursor.fetchone()["total"] + 1
    conn.close()
    ano = datetime.now().year
    return f"FOB-{ano}-{total:05d}"

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página inicial com acesso ao portal do motorista ou painel interno"""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/nova-ocorrencia", response_class=HTMLResponse)
async def nova_ocorrencia_form(request: Request):
    """Formulário mobile-first para o motorista/cliente reportar divergência na doca"""
    return templates.TemplateResponse(request=request, name="nova_ocorrencia.html")

@app.post("/nova-ocorrencia")
async def nova_ocorrencia_submit(
    request: Request,
    nf_numero: str = Form(...),
    chave_nfe: Optional[str] = Form(""),
    transportadora: str = Form(...),
    placa_veiculo: str = Form(...),
    motorista_nome: str = Form(...),
    motorista_telefone: str = Form(...),
    cliente_nome: str = Form(...),
    cliente_cnpj: Optional[str] = Form(""),
    tipo_divergencia: str = Form(...),
    descricao: str = Form(...),
    fotos: List[UploadFile] = File([])
):
    protocolo = gerar_numero_protocolo()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    salvas = []
    for foto in fotos:
        if foto.filename and foto.filename.strip():
            ext = os.path.splitext(foto.filename)[1].lower()
            nome_arquivo = f"{protocolo}_{int(datetime.now().timestamp()*1000)}{ext}"
            caminho_arquivo = os.path.join(UPLOAD_DIR, nome_arquivo)
            with open(caminho_arquivo, "wb") as buffer:
                shutil.copyfileobj(foto.file, buffer)
            salvas.append(nome_arquivo)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ocorrencias (
            protocolo, nf_numero, chave_nfe, transportadora, placa_veiculo,
            motorista_nome, motorista_telefone, cliente_nome, cliente_cnpj,
            tipo_divergencia, descricao, fila_atual, status, prioridade,
            fotos, resolucao_final, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Área de Devolução', 'Novo', 'Normal', ?, NULL, ?, ?)
    """, (
        protocolo, nf_numero.strip(), chave_nfe.strip() if chave_nfe else "",
        transportadora.strip(), placa_veiculo.strip().upper(),
        motorista_nome.strip(), motorista_telefone.strip(),
        cliente_nome.strip(), cliente_cnpj.strip() if cliente_cnpj else "",
        tipo_divergencia, descricao.strip(),
        json.dumps(salvas), agora, agora
    ))
    
    ocorrencia_id = cursor.lastrowid
    
    # Registro de auditoria
    cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, 'Motorista / Cliente', 'Abertura de Ocorrência FOB', 'Divergência registrada na doca e direcionada para a Área de Devolução.', ?)
    """, (ocorrencia_id, agora))
    
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/sucesso/{protocolo}", status_code=303)

@app.get("/sucesso/{protocolo}", response_class=HTMLResponse)
async def sucesso(request: Request, protocolo: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias WHERE protocolo = ?", (protocolo,))
    ocorrencia = cursor.fetchone()
    conn.close()
    
    if not ocorrencia:
        raise HTTPException(status_code=404, detail="Protocolo não localizado")

    return templates.TemplateResponse(request=request, name="sucesso.html", context={
        "ocorrencia": dict(ocorrencia)
    })

@app.get("/painel", response_class=HTMLResponse)
async def painel(
    request: Request,
    fila: Optional[str] = None,
    status: Optional[str] = None,
    busca: Optional[str] = None
):
    """Painel de Gestão e Triagem da Suzano"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Query base
    query = "SELECT * FROM ocorrencias WHERE 1=1"
    params = []
    
    if fila and fila != "Todas":
        query += " AND fila_atual = ?"
        params.append(fila)
        
    if status and status != "Todos":
        query += " AND status = ?"
        params.append(status)
        
    if busca:
        query += " AND (protocolo LIKE ? OR nf_numero LIKE ? OR transportadora LIKE ? OR placa_veiculo LIKE ? OR cliente_nome LIKE ?)"
        busca_param = f"%{busca}%"
        params.extend([busca_param, busca_param, busca_param, busca_param, busca_param])
        
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    itens = [dict(r) for r in cursor.fetchall()]
    
    for item in itens:
        item["fotos_list"] = json.loads(item["fotos"]) if item["fotos"] else []

    # Métricas gerais
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    total_geral = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE fila_atual = 'Área de Devolução' AND status = 'Novo'")
    total_novos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE status = 'Em Análise'")
    total_analise = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE status = 'Concluído'")
    total_concluidos = cursor.fetchone()["total"]

    # Contagem pelas filas personalizadas da Suzano
    filas_nome = ["Área de Devolução", "Análise de Procedência", "Finalizar FO", "Fiscal", "Qualidade"]
    contagem_filas = {}
    for f in filas_nome:
        cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE fila_atual = ? AND status != 'Concluído'", (f,))
        contagem_filas[f] = cursor.fetchone()["total"]

    conn.close()

    return templates.TemplateResponse(request=request, name="painel.html", context={
        "itens": itens,
        "total_geral": total_geral,
        "total_novos": total_novos,
        "total_analise": total_analise,
        "total_concluidos": total_concluidos,
        "contagem_filas": contagem_filas,
        "filtro_fila": fila or "Todas",
        "filtro_status": status or "Todos",
        "busca": busca or ""
    })

@app.get("/painel/protocolo/{ocorrencia_id}", response_class=HTMLResponse)
async def detalhes_ocorrencia(request: Request, ocorrencia_id: int):
    """Visão 360 do caso para a equipe da Suzano"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM ocorrencias WHERE id = ?", (ocorrencia_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada")
        
    ocorrencia = dict(row)
    ocorrencia["fotos_list"] = json.loads(ocorrencia["fotos"]) if ocorrencia["fotos"] else []
    
    cursor.execute("SELECT * FROM historico WHERE ocorrencia_id = ? ORDER BY id DESC", (ocorrencia_id,))
    historico = [dict(h) for h in cursor.fetchall()]
    
    conn.close()
    
    return templates.TemplateResponse(request=request, name="detalhes.html", context={
        "ocorrencia": ocorrencia,
        "historico": historico
    })

@app.post("/painel/protocolo/{ocorrencia_id}/tratar")
async def tratar_ocorrencia(
    ocorrencia_id: int,
    fila_destino: str = Form(...),
    novo_status: str = Form(...),
    prioridade: str = Form(...),
    autor: str = Form("Equipe Suzano"),
    observacao: str = Form(""),
    resolucao: Optional[str] = Form(None)
):
    """Executa o direcionamento entre as filas da Suzano"""
    conn = get_connection()
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Busca estado anterior
    cursor.execute("SELECT fila_atual, status FROM ocorrencias WHERE id = ?", (ocorrencia_id,))
    antigo = cursor.fetchone()
    if not antigo:
        conn.close()
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

    res_texto = resolucao.strip() if resolucao else None

    cursor.execute("""
        UPDATE ocorrencias
        SET fila_atual = ?, status = ?, prioridade = ?, resolucao_final = COALESCE(?, resolucao_final), updated_at = ?
        WHERE id = ?
    """, (fila_destino, novo_status, prioridade, res_texto, agora, ocorrencia_id))

    # Monta descrição do histórico de auditoria
    mudancas = []
    if antigo["fila_atual"] != fila_destino:
        mudancas.append(f"Fila alterada: '{antigo['fila_atual']}' ➔ '{fila_destino}'")
    if antigo["status"] != novo_status:
        mudancas.append(f"Status alterado: '{antigo['status']}' ➔ '{novo_status}'")
    
    acao = "Tratativa / Direcionamento" if mudancas else "Atualização de Parecer"
    desc_historico = " | ".join(mudancas)
    if observacao.strip():
        desc_historico = f"{desc_historico}\nParecer: {observacao.strip()}" if desc_historico else observacao.strip()

    cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ocorrencia_id, autor.strip(), acao, desc_historico, agora))

    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/painel/protocolo/{ocorrencia_id}?sucesso=1", status_code=303)

@app.get("/rastreio", response_class=HTMLResponse)
async def rastreio_busca(request: Request):
    """Tela de busca pública de protocolo"""
    return templates.TemplateResponse(request=request, name="rastreio.html", context={"ocorrencia": None})

@app.get("/rastreio/{protocolo}", response_class=HTMLResponse)
async def rastreio_protocolo(request: Request, protocolo: str):
    """Linha do tempo pública do protocolo"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias WHERE protocolo = ?", (protocolo,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return templates.TemplateResponse(request=request, name="rastreio.html", context={
            "ocorrencia": None,
            "erro": f"Protocolo '{protocolo}' não localizado. Verifique a digitação."
        })
        
    ocorrencia = dict(row)
    ocorrencia["fotos_list"] = json.loads(ocorrencia["fotos"]) if ocorrencia["fotos"] else []

    cursor.execute("SELECT * FROM historico WHERE ocorrencia_id = ? ORDER BY id ASC", (ocorrencia["id"],))
    historico = [dict(h) for h in cursor.fetchall()]
    conn.close()

    return templates.TemplateResponse(request=request, name="rastreio.html", context={
        "ocorrencia": ocorrencia,
        "historico": historico
    })

@app.get("/exportar-csv")
async def exportar_csv():
    """Gera exportação em CSV para relatórios em Excel"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Protocolo", "NF", "Transportadora", "Placa", "Motorista", "Telefone",
        "Cliente", "CNPJ", "Tipo Divergência", "Fila Atual", "Status", "Prioridade",
        "Data Abertura", "Última Atualização", "Resolução"
    ])
    for r in rows:
        writer.writerow([
            r["protocolo"], r["nf_numero"], r["transportadora"], r["placa_veiculo"],
            r["motorista_nome"], r["motorista_telefone"], r["cliente_nome"], r["cliente_cnpj"],
            r["tipo_divergencia"], r["fila_atual"], r["status"], r["prioridade"],
            r["created_at"], r["updated_at"], r["resolucao_final"] or ""
        ])

    output.seek(0)
    return Response(
        content=output.getvalue().encode('utf-8-sig'),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fob_divergencias_suzano_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"}
    )
