import os
import sqlite3
import json
import hashlib
import secrets
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "fob_tracker.db")

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _gerar_hash_inicial(senha: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${key.hex()}"

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela principal de ocorrências
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ocorrencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protocolo TEXT UNIQUE NOT NULL,
        nf_numero TEXT NOT NULL,
        chave_nfe TEXT,
        centro_origem TEXT DEFAULT '',
        transportadora TEXT NOT NULL,
        placa_veiculo TEXT NOT NULL,
        motorista_nome TEXT NOT NULL,
        motorista_telefone TEXT NOT NULL,
        cliente_nome TEXT NOT NULL,
        cliente_cnpj TEXT,
        tipo_divergencia TEXT NOT NULL,
        descricao TEXT NOT NULL,
        fila_atual TEXT NOT NULL DEFAULT 'Área de Devolução',
        status TEXT NOT NULL DEFAULT 'Novo',
        prioridade TEXT NOT NULL DEFAULT 'Normal',
        fotos TEXT NOT NULL DEFAULT '[]',
        resolucao_final TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Migração automática caso o campo centro_origem ainda não exista
    cursor.execute("PRAGMA table_info(ocorrencias)")
    colunas = [c["name"] for c in cursor.fetchall()]
    if "centro_origem" not in colunas:
        cursor.execute("ALTER TABLE ocorrencias ADD COLUMN centro_origem TEXT DEFAULT ''")
    
    # Tabela de histórico / auditoria de tratativas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ocorrencia_id INTEGER NOT NULL,
        autor TEXT NOT NULL,
        acao TEXT NOT NULL,
        observacao TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (ocorrencia_id) REFERENCES ocorrencias(id) ON DELETE CASCADE
    );
    """)
    
    # Tabela de Usuários (Controle de Acesso / Perfis Admin e Comum)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL,
        perfil TEXT NOT NULL DEFAULT 'comum',
        ativo INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)

    # Tabela de Sessões para Login Seguro
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        usuario_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );
    """)

    conn.commit()

    # Criação do usuário Administrador inicial se não houver usuários cadastrados
    cursor.execute("SELECT COUNT(*) as total FROM usuarios")
    if cursor.fetchone()["total"] == 0:
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        senha_admin = _gerar_hash_inicial("Suzano@2026")
        cursor.execute("""
            INSERT INTO usuarios (nome, username, senha_hash, perfil, ativo, created_at)
            VALUES (?, ?, ?, 'admin', 1, ?)
        """, ("Administrador Suzano", "admin", senha_admin, agora))
        conn.commit()
    
    # Seed de dados de ocorrências se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    row = cursor.fetchone()
    if row["total"] == 0:
        seed_dados(conn)
        
    conn.close()

def seed_dados(conn):
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    exemplos = [
        (
            "FOB-2026-00101", "NF 482910", "35260900000000000192550010004829101000482911",
            "1112 - CD Suzano UNBC", "TransLog Express", "ABC-4D89", "Carlos Eduardo Mendes", "(11) 98765-4321",
            "Gráfica & Editora Alvorada Ltda", "12.345.678/0001-90",
            "Avaria Física / Embalagem",
            "Ao posicionar os paletes de bobinas de papel na doca 03, constatou-se impacto lateral com rasgo no papel kraft e umidade visível.",
            "Área de Devolução", "Novo", "Alta",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00102", "NF 482933", "35260900000000000192550010004829331000482933",
            "2100 - Unidade Mucuri BA", "Rápido Rodoviário Sul", "XYZ-9F12", "Marcos Vinicius Silva", "(19) 97123-8899",
            "Embalagens Progresso S/A", "98.765.432/0001-10",
            "Falta de Volumes / Paletes",
            "NF faturada com 24 fardos de celulose solúvel, porém na conferência física da doca foram disponibilizados apenas 22 fardos. Faltam 2 fardos.",
            "Análise de Procedência", "Em Análise", "Alta",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00103", "NF 483005", "35260900000000000192550010004830051000483005",
            "5400 - Unidade Limeira SP", "TransCargas Brasil", "JHG-2A33", "Roberto Santos", "(31) 99887-1122",
            "Cartonagem Horizonte", "44.555.666/0001-22",
            "Divergência Fiscal / Dados da NF",
            "Falta confirmada pela operação. Protocolo encaminhado para encerramento de FO e ressarcimento financeiro ao cliente.",
            "Finalizar FO", "Em Análise", "Urgente",
            json.dumps([]), None, agora, agora
        )
    ]
    
    for ex in exemplos:
        cursor.execute("""
        INSERT INTO ocorrencias (
            protocolo, nf_numero, chave_nfe, centro_origem, transportadora, placa_veiculo,
            motorista_nome, motorista_telefone, cliente_nome, cliente_cnpj,
            tipo_divergencia, descricao, fila_atual, status, prioridade,
            fotos, resolucao_final, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ex)
        
        ocorrencia_id = cursor.lastrowid
        cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, 'Sistema', 'Abertura do Protocolo', 'Protocolo registrado no armazém e encaminhado para a Área de Devolução.', ?)
        """, (ocorrencia_id, agora))
        
    conn.commit()
