import os
import shutil
import json
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import get_connection, init_db
from app.auth import hash_senha, verificar_senha, criar_sessao, obter_usuario_da_sessao, encerrar_sessao

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

# Inicializa banco de dados, tabelas de autenticação e filas dinâmicas
init_db()

# Dicionário oficial de centros da Suzano
CENTROS_SUZANO = {
    "1081": "CD Campina Grande do Sul",
    "1102": "Unidade Rio Verde SP",
    "1110": "Fábrica Mogi das Cruzes",
    "1111": "CD GUARULHOS",
    "1112": "CD Suzano UNBC",
    "1113": "CD Simões Filho UNBC",
    "1114": "CD Fortaleza UNBC",
    "1115": "CD Cabo de Sto. Agostinho UNBC",
    "1116": "CD Cachoeirinha UNBC",
    "1301": "Unidade Imperatriz MA",
    "2100": "Unidade Mucuri BA",
    "2280": "CD Maracanau",
    "2282": "CD Maracanau - CE",
    "2283": "Unidade Belem - PA",
    "3222": "Valencia",
    "3224": "Honfleur",
    "3608": "Santos ASIA (FIT)",
    "3841": "Veracel (FIT)",
    "5400": "Unidade Limeira SP",
    "6100": "Unidade Jacareí SP",
    "6300": "Unidade Aracruz ES",
    "6599": "VERACEL CELULOSE S.A.",
    "6800": "Suzano-MS Cel Sul M. Gros Ltda",
    "8012": "SFBC PARTICIPACOES FACEPA",
}

def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session_token")
    if not token:
        return None
    return obter_usuario_da_sessao(token)

def obter_filas_ativas() -> List[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, descricao FROM filas WHERE ativa = 1 ORDER BY ordem ASC, id ASC")
    filas = [dict(f) for f in cursor.fetchall()]
    conn.close()
    if not filas:
        return [{"id": 1, "nome": "Área de Devolução", "descricao": "Fila Inicial"}]
    return filas

def gerar_numero_protocolo():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    total = cursor.fetchone()["total"] + 1
    conn.close()
    ano = datetime.now().year
    return f"FOB-{ano}-{total:05d}"

# ==========================================
# ROTAS PÚBLICAS (Home e Rastreio)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    usuario = get_current_user(request)
    return templates.TemplateResponse(request=request, name="index.html", context={
        "usuario_logado": usuario
    })

@app.get("/rastreio", response_class=HTMLResponse)
async def rastreio_busca(request: Request):
    usuario = get_current_user(request)
    return templates.TemplateResponse(request=request, name="rastreio.html", context={
        "ocorrencia": None,
        "usuario_logado": usuario
    })

@app.get("/rastreio/{protocolo}", response_class=HTMLResponse)
async def rastreio_protocolo(request: Request, protocolo: str):
    usuario = get_current_user(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias WHERE protocolo = ?", (protocolo,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return templates.TemplateResponse(request=request, name="rastreio.html", context={
            "ocorrencia": None,
            "erro": f"Protocolo '{protocolo}' não localizado. Verifique a digitação.",
            "usuario_logado": usuario
        })
        
    ocorrencia = dict(row)
    ocorrencia["fotos_list"] = json.loads(ocorrencia["fotos"]) if ocorrencia["fotos"] else []

    cursor.execute("SELECT * FROM historico WHERE ocorrencia_id = ? ORDER BY id ASC", (ocorrencia["id"],))
    historico = [dict(h) for h in cursor.fetchall()]
    conn.close()

    return templates.TemplateResponse(request=request, name="rastreio.html", context={
        "ocorrencia": ocorrencia,
        "historico": historico,
        "usuario_logado": usuario
    })

# ==========================================
# ROTAS DE AUTENTICAÇÃO (Login e Logout)
# ==========================================

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: Optional[str] = "/painel"):
    usuario = get_current_user(request)
    if usuario:
        return RedirectResponse(url=next or "/painel", status_code=303)
        
    return templates.TemplateResponse(request=request, name="login.html", context={
        "usuario_logado": None,
        "erro": None
    })

@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    senha: str = Form(...),
    next: Optional[str] = Form("/painel")
):
    conn = get_connection()
    cursor = conn.cursor()
    username_clean = username.strip().lower()
    
    # Permite login por username cadastrado ou pelo apelido luiz.ferreira / admin
    cursor.execute("""
        SELECT * FROM usuarios 
        WHERE (LOWER(username) = ? OR (id = 1 AND ? IN ('admin', 'luiz.ferreira', 'luiz')))
        AND ativo = 1
    """, (username_clean, username_clean))
    user_row = cursor.fetchone()
    conn.close()

    if not user_row or not verificar_senha(senha, user_row["senha_hash"]):
        return templates.TemplateResponse(request=request, name="login.html", context={
            "usuario_logado": None,
            "erro": "Usuário ou senha incorretos. Verifique suas credenciais."
        }, status_code=400)

    # Cria sessão segura
    token = criar_sessao(user_row["id"])
    dest_url = next if (next and next.startswith("/")) else "/painel"
    response = RedirectResponse(url=dest_url, status_code=303)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600, # 7 dias
        samesite="lax"
    )
    return response

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        encerrar_sessao(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response

# ========================================================
# ROTAS PROTEGIDAS DE PROTOCOLO (EXIGE LOGIN OBRIGATÓRIO)
# ========================================================

@app.get("/nova-ocorrencia", response_class=HTMLResponse)
async def nova_ocorrencia_form(request: Request):
    # LOGIN OBRIGATÓRIO PARA ABRIR PROTOCOLO
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login?next=/nova-ocorrencia", status_code=303)

    return templates.TemplateResponse(request=request, name="nova_ocorrencia.html", context={
        "centros": CENTROS_SUZANO,
        "usuario_logado": usuario
    })

@app.post("/nova-ocorrencia")
async def nova_ocorrencia_submit(
    request: Request,
    nf_numero: str = Form(...),
    chave_nfe: Optional[str] = Form(""),
    centro_origem: str = Form(...),
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
    # LOGIN OBRIGATÓRIO
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login?next=/nova-ocorrencia", status_code=303)

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
            protocolo, nf_numero, chave_nfe, centro_origem, transportadora, placa_veiculo,
            motorista_nome, motorista_telefone, cliente_nome, cliente_cnpj,
            tipo_divergencia, descricao, fila_atual, status, prioridade,
            fotos, resolucao_final, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Área de Devolução', 'Novo', 'Normal', ?, NULL, ?, ?)
    """, (
        protocolo, nf_numero.strip(), chave_nfe.strip() if chave_nfe else "",
        centro_origem.strip(), transportadora.strip(), placa_veiculo.strip().upper(),
        motorista_nome.strip(), motorista_telefone.strip(),
        cliente_nome.strip(), cliente_cnpj.strip() if cliente_cnpj else "",
        tipo_divergencia, descricao.strip(),
        json.dumps(salvas), agora, agora
    ))
    
    ocorrencia_id = cursor.lastrowid
    nome_abridor = f"{usuario['nome']} ({'Admin' if usuario['perfil'] == 'admin' else 'Operador'})"
    
    cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, ?, 'Abertura de Ocorrência FOB', 'Divergência registrada e direcionada para a Área de Devolução.', ?)
    """, (ocorrencia_id, nome_abridor, agora))
    
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/sucesso/{protocolo}", status_code=303)

@app.get("/sucesso/{protocolo}", response_class=HTMLResponse)
async def sucesso(request: Request, protocolo: str):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias WHERE protocolo = ?", (protocolo,))
    ocorrencia = cursor.fetchone()
    conn.close()
    
    if not ocorrencia:
        raise HTTPException(status_code=404, detail="Protocolo não localizado")

    return templates.TemplateResponse(request=request, name="sucesso.html", context={
        "ocorrencia": dict(ocorrencia),
        "usuario_logado": usuario
    })

# ==========================================
# ROTAS DA MESA OPERACIONAL SUZANO
# ==========================================

@app.get("/painel", response_class=HTMLResponse)
async def painel(
    request: Request,
    fila: Optional[str] = None,
    status: Optional[str] = None,
    busca: Optional[str] = None
):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login?next=/painel", status_code=303)

    filas_ativas = obter_filas_ativas()

    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM ocorrencias WHERE 1=1"
    params = []
    
    if fila and fila != "Todas":
        query += " AND fila_atual = ?"
        params.append(fila)
        
    if status and status != "Todos":
        query += " AND status = ?"
        params.append(status)
        
    if busca:
        query += " AND (protocolo LIKE ? OR nf_numero LIKE ? OR transportadora LIKE ? OR placa_veiculo LIKE ? OR cliente_nome LIKE ? OR centro_origem LIKE ?)"
        busca_param = f"%{busca}%"
        params.extend([busca_param, busca_param, busca_param, busca_param, busca_param, busca_param])
        
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    itens = [dict(r) for r in cursor.fetchall()]
    
    for item in itens:
        item["fotos_list"] = json.loads(item["fotos"]) if item["fotos"] else []

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    total_geral = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE fila_atual = 'Área de Devolução' AND status = 'Novo'")
    total_novos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE status = 'Em Análise'")
    total_analise = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE status = 'Concluído'")
    total_concluidos = cursor.fetchone()["total"]

    # Contagem dinâmica baseada nas filas ativas cadastradas pelo admin
    contagem_filas = {}
    for f in filas_ativas:
        cursor.execute("SELECT COUNT(*) as total FROM ocorrencias WHERE fila_atual = ? AND status != 'Concluído'", (f["nome"],))
        contagem_filas[f["nome"]] = cursor.fetchone()["total"]

    conn.close()

    return templates.TemplateResponse(request=request, name="painel.html", context={
        "itens": itens,
        "total_geral": total_geral,
        "total_novos": total_novos,
        "total_analise": total_analise,
        "total_concluidos": total_concluidos,
        "filas_ativas": filas_ativas,
        "contagem_filas": contagem_filas,
        "filtro_fila": fila or "Todas",
        "filtro_status": status or "Todos",
        "busca": busca or "",
        "usuario_logado": usuario
    })

@app.get("/painel/protocolo/{ocorrencia_id}", response_class=HTMLResponse)
async def detalhes_ocorrencia(request: Request, ocorrencia_id: int):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url=f"/login?next=/painel/protocolo/{ocorrencia_id}", status_code=303)

    filas_ativas = obter_filas_ativas()

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
        "historico": historico,
        "filas_ativas": filas_ativas,
        "usuario_logado": usuario
    })

@app.post("/painel/protocolo/{ocorrencia_id}/tratar")
async def tratar_ocorrencia(
    request: Request,
    ocorrencia_id: int,
    fila_destino: str = Form(...),
    novo_status: str = Form(...),
    prioridade: str = Form(...),
    observacao: str = Form(""),
    resolucao: Optional[str] = Form(None)
):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    mudancas = []
    if antigo["fila_atual"] != fila_destino:
        mudancas.append(f"Fila alterada: '{antigo['fila_atual']}' ➔ '{fila_destino}'")
    if antigo["status"] != novo_status:
        mudancas.append(f"Status alterado: '{antigo['status']}' ➔ '{novo_status}'")
    
    acao = "Tratativa / Direcionamento" if mudancas else "Atualização de Parecer"
    desc_historico = " | ".join(mudancas)
    if observacao.strip():
        desc_historico = f"{desc_historico}\nParecer: {observacao.strip()}" if desc_historico else observacao.strip()

    nome_autor = f"{usuario['nome']} ({'Admin' if usuario['perfil'] == 'admin' else 'Operador'})"

    cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ocorrencia_id, nome_autor, acao, desc_historico, agora))

    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/painel/protocolo/{ocorrencia_id}?sucesso=1", status_code=303)

@app.get("/exportar-csv")
async def exportar_csv(request: Request):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login?next=/painel", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ocorrencias ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Protocolo", "Centro de Origem", "NF", "Transportadora", "Placa", "Motorista", "Telefone",
        "Cliente", "CNPJ", "Tipo Divergência", "Fila Atual", "Status", "Prioridade",
        "Data Abertura", "Última Atualização", "Resolução"
    ])
    for r in rows:
        writer.writerow([
            r["protocolo"], r["centro_origem"] or "", r["nf_numero"], r["transportadora"], r["placa_veiculo"],
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

# =========================================================================
# ROTAS EXCLUSIVAS DO ADMINISTRADOR (CADASTRO DE USUÁRIOS E FILAS DE DESTINO)
# =========================================================================

@app.get("/admin/usuarios", response_class=HTMLResponse)
async def admin_usuarios_page(request: Request, msg: Optional[str] = None, erro: Optional[str] = None):
    usuario = get_current_user(request)
    if not usuario:
        return RedirectResponse(url="/login?next=/admin/usuarios", status_code=303)
        
    if usuario["perfil"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito exclusivamente aos administradores do sistema.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, username, perfil, ativo, created_at FROM usuarios ORDER BY id ASC")
    lista_usuarios = [dict(u) for u in cursor.fetchall()]

    cursor.execute("SELECT id, nome, descricao, ordem, ativa FROM filas ORDER BY ordem ASC, id ASC")
    lista_filas = [dict(f) for f in cursor.fetchall()]
    conn.close()

    return templates.TemplateResponse(request=request, name="admin_usuarios.html", context={
        "usuario_logado": usuario,
        "usuarios": lista_usuarios,
        "filas": lista_filas,
        "mensagem": msg,
        "erro": erro
    })

@app.post("/admin/usuarios/criar")
async def admin_criar_usuario(
    request: Request,
    nome: str = Form(...),
    username: str = Form(...),
    senha: str = Form(...),
    perfil: str = Form("comum")
):
    usuario = get_current_user(request)
    if not usuario or usuario["perfil"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito aos administradores.")

    if len(senha.strip()) < 4:
        return RedirectResponse(url="/admin/usuarios?erro=A+senha+deve+ter+no+minimo+4+caracteres", status_code=303)

    tipo_perfil = "admin" if perfil == "admin" else "comum"
    senha_hasheada = hash_senha(senha.strip())
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO usuarios (nome, username, senha_hash, perfil, ativo, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (nome.strip(), username.strip().lower(), senha_hasheada, tipo_perfil, agora))
        conn.commit()
    except Exception:
        conn.close()
        return RedirectResponse(url="/admin/usuarios?erro=Nome+de+usuario+ja+cadastrado.+Escolha+outro.", status_code=303)

    conn.close()
    return RedirectResponse(url="/admin/usuarios?msg=Usuario+cadastrado+com+sucesso!", status_code=303)

@app.post("/admin/usuarios/{usuario_id}/excluir")
async def admin_excluir_usuario(request: Request, usuario_id: int):
    usuario = get_current_user(request)
    if not usuario or usuario["perfil"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito aos administradores.")

    if usuario["id"] == usuario_id:
        return RedirectResponse(url="/admin/usuarios?erro=Voce+nao+pode+excluir+o+proprio+usuario+em+uso.", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id = ? AND id != 1", (usuario_id,))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/admin/usuarios?msg=Acesso+do+usuario+removido+com+sucesso!", status_code=303)

# CADASTRO E GERENCIAMENTO DE FILAS DE DESTINO PELO ADMIN
@app.post("/admin/filas/criar")
async def admin_criar_fila(
    request: Request,
    nome_fila: str = Form(...),
    descricao: str = Form("")
):
    usuario = get_current_user(request)
    if not usuario or usuario["perfil"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito.")

    nome_clean = nome_fila.strip()
    if not nome_clean:
        return RedirectResponse(url="/admin/usuarios?erro=O+nome+da+fila+nao+pode+ser+vazio", status_code=303)

    conn = get_connection()
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute("SELECT COALESCE(MAX(ordem), 0) + 1 as proxima FROM filas")
        proxima_ordem = cursor.fetchone()["proxima"]
        
        cursor.execute("""
            INSERT INTO filas (nome, descricao, ordem, ativa, created_at)
            VALUES (?, ?, ?, 1, ?)
        """, (nome_clean, descricao.strip(), proxima_ordem, agora))
        conn.commit()
    except Exception:
        conn.close()
        return RedirectResponse(url="/admin/usuarios?erro=Esta+fila+ja+esta+cadastrada.", status_code=303)

    conn.close()
    return RedirectResponse(url="/admin/usuarios?msg=Nova+fila+de+destino+cadastrada+com+sucesso!", status_code=303)

@app.post("/admin/filas/{fila_id}/excluir")
async def admin_excluir_fila(request: Request, fila_id: int):
    usuario = get_current_user(request)
    if not usuario or usuario["perfil"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM filas WHERE id = ?", (fila_id,))
    fila = cursor.fetchone()
    if not fila:
        conn.close()
        return RedirectResponse(url="/admin/usuarios?erro=Fila+nao+encontrada.", status_code=303)

    # Não permite excluir a Área de Devolução (pois é a fila inicial do sistema)
    if fila["nome"] == "Área de Devolução":
        conn.close()
        return RedirectResponse(url="/admin/usuarios?erro=A+fila+Area+de+Devolucao+e+obrigatoria+e+nao+pode+ser+removida.", status_code=303)

    cursor.execute("DELETE FROM filas WHERE id = ?", (fila_id,))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/admin/usuarios?msg=Fila+removida+com+sucesso!", status_code=303)
