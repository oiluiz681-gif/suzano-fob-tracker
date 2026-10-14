import os
import sqlite3
import json
import hashlib
import secrets
import threading
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "fob_tracker.db")

USERS_BACKUP = os.path.join(DB_DIR, "usuarios_permanentes.json")
FILAS_BACKUP = os.path.join(DB_DIR, "filas_permanentes.json")
OCORRENCIAS_BACKUP = os.path.join(DB_DIR, "ocorrencias_permanentes.json")

# =========================================================================
# LISTA DE USUÁRIOS FIXOS E IMUNES A QUALQUER REINÍCIO OU DORMIDA DO RENDER
# =========================================================================
USUARIOS_PRE_CADASTRADOS = [
    {
        "nome": "Luiz Fernando Ferreira",
        "username": "admin",
        "senha": "Suzano@2026",
        "perfil": "admin"
    },
    {
        "nome": "Luiz Fernando Ferreira",
        "username": "luiz.ferreira",
        "senha": "Suzano@2026",
        "perfil": "admin"
    },
    {
        "nome": "MARIANA DA SILVA MELO",
        "username": "marianasm@suzano.com.br",
        "senha": "Suzano@123",
        "perfil": "admin"
    },
    {
        "nome": "MARIANA DA SILVA MELO",
        "username": "marianasm",
        "senha": "Suzano@123",
        "perfil": "admin"
    }
]

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        pg_query = query.replace("?", "%s")
        if params is not None:
            return self.cursor.execute(pg_query, params)
        return self.cursor.execute(pg_query)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(r) for r in rows] if rows else []

    def close(self):
        return self.cursor.close()

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=RealDictCursor))

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

def get_db_url():
    url = os.getenv("DATABASE_URL")
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

def is_postgres():
    return bool(get_db_url() and psycopg2)

def get_connection():
    db_url = get_db_url()
    if db_url and psycopg2:
        conn = psycopg2.connect(db_url)
        return PostgresConnectionWrapper(conn)
    else:
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def _gerar_hash_inicial(senha: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${key.hex()}"

def salvar_backup_local():
    """Grava o estado de usuários, filas e ocorrências em JSON persistente"""
    try:
        os.makedirs(DB_DIR, exist_ok=True)
        conn = get_connection()
        cursor = conn.cursor()
        
        # Usuários
        cursor.execute("SELECT id, nome, username, senha_hash, perfil, ativo, created_at FROM usuarios")
        usuarios = [dict(u) for u in cursor.fetchall()]
        with open(USERS_BACKUP, "w", encoding="utf-8") as f:
            json.dump(usuarios, f, indent=2, ensure_ascii=False)
            
        # Filas
        cursor.execute("SELECT id, nome, descricao, ordem, ativa, created_at FROM filas")
        filas = [dict(f) for f in cursor.fetchall()]
        with open(FILAS_BACKUP, "w", encoding="utf-8") as f:
            json.dump(filas, f, indent=2, ensure_ascii=False)

        # Ocorrências
        cursor.execute("SELECT * FROM ocorrencias")
        ocorrencias = [dict(o) for o in cursor.fetchall()]
        with open(OCORRENCIAS_BACKUP, "w", encoding="utf-8") as f:
            json.dump(ocorrencias, f, indent=2, ensure_ascii=False)

        conn.close()
    except Exception as e:
        print(f"[Backup] Erro ao salvar backup local: {e}")

def sincronizar_com_github():
    """Placeholder de sincronização em nuvem segura via variáveis de ambiente"""
    pass

def restaurar_backup_local(conn):
    """Restaura usuários, filas e ocorrências persistentes caso o container tenha sido recriado"""
    cursor = conn.cursor()
    
    if os.path.exists(USERS_BACKUP):
        try:
            with open(USERS_BACKUP, "r", encoding="utf-8") as f:
                usuarios = json.load(f)
            for u in usuarios:
                cursor.execute("""
                    INSERT INTO usuarios (id, nome, username, senha_hash, perfil, ativo, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        nome = excluded.nome,
                        senha_hash = excluded.senha_hash,
                        perfil = excluded.perfil,
                        ativo = excluded.ativo
                """, (u.get("id"), u["nome"], u["username"], u["senha_hash"], u["perfil"], u.get("ativo", 1), u.get("created_at", "")))
            conn.commit()
            print(f"[Backup] Restaurados {len(usuarios)} usuários do backup permanente!")
        except Exception as e:
            print(f"[Backup] Erro restaurando usuários: {e}")

    if os.path.exists(FILAS_BACKUP):
        try:
            with open(FILAS_BACKUP, "r", encoding="utf-8") as f:
                filas = json.load(f)
            for fl in filas:
                cursor.execute("""
                    INSERT INTO filas (id, nome, descricao, ordem, ativa, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(nome) DO UPDATE SET
                        descricao = excluded.descricao,
                        ordem = excluded.ordem,
                        ativa = excluded.ativa
                """, (fl.get("id"), fl["nome"], fl.get("descricao", ""), fl.get("ordem", 0), fl.get("ativa", 1), fl.get("created_at", "")))
            conn.commit()
            print(f"[Backup] Restauradas {len(filas)} filas do backup permanente!")
        except Exception as e:
            print(f"[Backup] Erro restaurando filas: {e}")

    if os.path.exists(OCORRENCIAS_BACKUP):
        try:
            with open(OCORRENCIAS_BACKUP, "r", encoding="utf-8") as f:
                ocorrencias = json.load(f)
            for oc in ocorrencias:
                cursor.execute("""
                    INSERT INTO ocorrencias (
                        id, protocolo, nf_numero, chave_nfe, centro_origem, transportadora, placa_veiculo,
                        motorista_nome, motorista_telefone, cliente_nome, cliente_cnpj,
                        tipo_divergencia, descricao, fila_atual, status, prioridade,
                        fotos, resolucao_final, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(protocolo) DO UPDATE SET
                        fila_atual = excluded.fila_atual,
                        status = excluded.status,
                        prioridade = excluded.prioridade,
                        resolucao_final = excluded.resolucao_final,
                        updated_at = excluded.updated_at
                """, (
                    oc.get("id"), oc["protocolo"], oc["nf_numero"], oc.get("chave_nfe", ""),
                    oc.get("centro_origem", ""), oc["transportadora"], oc["placa_veiculo"],
                    oc["motorista_nome"], oc["motorista_telefone"], oc["cliente_nome"], oc.get("cliente_cnpj", ""),
                    oc["tipo_divergencia"], oc["descricao"], oc.get("fila_atual", "Área de Devolução"),
                    oc.get("status", "Novo"), oc.get("prioridade", "Normal"),
                    oc.get("fotos", "[]"), oc.get("resolucao_final"), oc["created_at"], oc["updated_at"]
                ))
            conn.commit()
            print(f"[Backup] Restauradas {len(ocorrencias)} ocorrências do backup permanente!")
        except Exception as e:
            print(f"[Backup] Erro restaurando ocorrências: {e}")

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if is_postgres():
        # Tabelas para PostgreSQL em Nuvem (Render / Supabase / Neon)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ocorrencias (
            id SERIAL PRIMARY KEY,
            protocolo TEXT UNIQUE NOT NULL,
            nf_numero TEXT NOT NULL,
            chave_nfe TEXT DEFAULT '',
            centro_origem TEXT DEFAULT '',
            transportadora TEXT NOT NULL,
            placa_veiculo TEXT NOT NULL,
            motorista_nome TEXT NOT NULL,
            motorista_telefone TEXT NOT NULL,
            cliente_nome TEXT NOT NULL,
            cliente_cnpj TEXT DEFAULT '',
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
        cursor.execute("ALTER TABLE ocorrencias ADD COLUMN IF NOT EXISTS centro_origem TEXT DEFAULT '';")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico (
            id SERIAL PRIMARY KEY,
            ocorrencia_id INTEGER NOT NULL,
            autor TEXT NOT NULL,
            acao TEXT NOT NULL,
            observacao TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ocorrencia_id) REFERENCES ocorrencias(id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            perfil TEXT NOT NULL DEFAULT 'comum',
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessoes (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            usuario_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS filas (
            id SERIAL PRIMARY KEY,
            nome TEXT UNIQUE NOT NULL,
            descricao TEXT,
            ordem INTEGER DEFAULT 0,
            ativa INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)
    else:
        # Tabelas para SQLite local
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

        cursor.execute("PRAGMA table_info(ocorrencias)")
        colunas = [c["name"] for c in cursor.fetchall()]
        if "centro_origem" not in colunas:
            cursor.execute("ALTER TABLE ocorrencias ADD COLUMN centro_origem TEXT DEFAULT ''")

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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS filas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            descricao TEXT,
            ordem INTEGER DEFAULT 0,
            ativa INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

    conn.commit()

    # Restaura backups locais se existirem
    restaurar_backup_local(conn)

    # Garante os usuários pré-cadastrados fixos em todo reinício/dormida do Render
    for u in USUARIOS_PRE_CADASTRADOS:
        cursor.execute("SELECT id FROM usuarios WHERE LOWER(username) = LOWER(?)", (u["username"],))
        existe = cursor.fetchone()
        if not existe:
            senha_h = _gerar_hash_inicial(u["senha"])
            cursor.execute("""
                INSERT INTO usuarios (nome, username, senha_hash, perfil, ativo, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (u["nome"], u["username"], senha_h, u["perfil"], agora))
        else:
            senha_h = _gerar_hash_inicial(u["senha"])
            cursor.execute("""
                UPDATE usuarios SET nome = ?, senha_hash = ?, perfil = ?, ativo = 1 WHERE id = ?
            """, (u["nome"], senha_h, u["perfil"], existe["id"]))

    # Seed inicial das Filas de Destino se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) as total FROM filas")
    if cursor.fetchone()["total"] == 0:
        filas_iniciais = [
            ("Área de Devolução", "Fila inicial onde todos os novos protocolos de clientes são recepcionados", 1),
            ("Análise de Procedência", "Fila da operação que investiga a procedência da falta física", 2),
            ("Finalizar FO", "Fila que finaliza a FO para o cliente ser formalmente ressarcido", 3),
            ("Fiscal", "Tratativa tributária, notas de devolução e cancelamento de canhoto", 4),
        ]
        for f in filas_iniciais:
            cursor.execute("""
                INSERT INTO filas (nome, descricao, ordem, ativa, created_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(nome) DO NOTHING
            """, (f[0], f[1], f[2], agora))

    # Seed de ocorrências de exemplo se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) as total FROM ocorrencias")
    row = cursor.fetchone()
    if row["total"] == 0:
        seed_dados(conn)
        
    conn.commit()
    conn.close()

    # Garante o backup local sincronizado
    salvar_backup_local()

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
        ON CONFLICT(protocolo) DO NOTHING
        """, ex)
        
        cursor.execute("SELECT id FROM ocorrencias WHERE protocolo = ?", (ex[0],))
        row_oc = cursor.fetchone()
        ocorrencia_id = row_oc["id"] if row_oc else 0
        
        cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, 'Luiz Fernando Ferreira', 'Abertura do Protocolo', 'Protocolo registrado no armazém e encaminhado para a Área de Devolução.', ?)
        """, (ocorrencia_id, agora))
        
    conn.commit()
