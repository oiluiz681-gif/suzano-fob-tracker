import os
import sqlite3
import json
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "fob_tracker.db")

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
        transportadora TEXT NOT NULL,
        placa_veiculo TEXT NOT NULL,
        motorista_nome TEXT NOT NULL,
        motorista_telefone TEXT NOT NULL,
        cliente_nome TEXT NOT NULL,
        cliente_cnpj TEXT,
        tipo_divergencia TEXT NOT NULL,
        descricao TEXT NOT NULL,
        fila_atual TEXT NOT NULL DEFAULT 'Triagem Inicial',
        status TEXT NOT NULL DEFAULT 'Novo',
        prioridade TEXT NOT NULL DEFAULT 'Normal',
        fotos TEXT NOT NULL DEFAULT '[]',
        resolucao_final TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    
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
    
    conn.commit()
    
    # Seed de dados iniciais para demonstração se a tabela estiver vazia
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
            "TransLog Express", "ABC-4D89", "Carlos Eduardo Mendes", "(11) 98765-4321",
            "Gráfica & Editora Alvorada Ltda", "12.345.678/0001-90",
            "Avaria Física / Embalagem",
            "Ao posicionar os paletes de bobinas de papel na doca 03, constatou-se que 2 bobinas sofreram impacto lateral com rasgo profundo no papel kraft e umidade visível.",
            "Qualidade", "Em Análise", "Alta",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00102", "NF 482933", "35260900000000000192550010004829331000482933",
            "Rápido Rodoviário Sul", "XYZ-9F12", "Marcos Vinicius Silva", "(19) 97123-8899",
            "Embalagens Progresso S/A", "98.765.432/0001-10",
            "Falta de Volumes / Paletes",
            "NF faturada com 24 fardos de celulose solúvel, porém na conferência física da doca foram disponibilizados apenas 22 fardos. Faltam 2 fardos.",
            "Armazém / Doca", "Em Análise", "Alta",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00103", "NF 483005", "35260900000000000192550010004830051000483005",
            "TransCargas Brasil", "JHG-2A33", "Roberto Santos", "(31) 99887-1122",
            "Cartonagem Horizonte", "44.555.666/0001-22",
            "Divergência Fiscal / Dados da NF",
            "Motorista alega que o CNPJ de faturamento saiu com filial antiga desativada. Solicitada carta de correção ou cancelamento e refaturamento imediato.",
            "Fiscal", "Em Análise", "Urgente",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00104", "NF 483120", "",
            "Paulista Logística", "KLE-7711", "Fernando Dias", "(11) 98111-2233",
            "Indústria de Papel Millennium", "55.666.777/0001-44",
            "Mercadoria Trocada / Lote Incorreto",
            "Lote constante na etiqueta do palete (LOTE-26A) difere do certificado de qualidade que acompanha o romaneio de carga (LOTE-26B).",
            "Triagem Inicial", "Novo", "Normal",
            json.dumps([]), None, agora, agora
        ),
        (
            "FOB-2026-00095", "NF 482500", "",
            "Expresso Sudeste", "QWE-1234", "Antonio Fagundes", "(11) 97654-3210",
            "Distribuidora Rio Branco", "33.222.111/0001-00",
            "Avaria Física / Embalagem",
            "Avaria sanada no local com substituição de 1 palete avariado por novo item inspecionado.",
            "Triagem Inicial", "Concluído", "Normal",
            json.dumps([]), "Item trocado na doca 02 sob supervisão. Liberado para viagem.", agora, agora
        )
    ]
    
    for ex in exemplos:
        cursor.execute("""
        INSERT INTO ocorrencias (
            protocolo, nf_numero, chave_nfe, transportadora, placa_veiculo,
            motorista_nome, motorista_telefone, cliente_nome, cliente_cnpj,
            tipo_divergencia, descricao, fila_atual, status, prioridade,
            fotos, resolucao_final, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ex)
        
        ocorrencia_id = cursor.lastrowid
        cursor.execute("""
        INSERT INTO historico (ocorrencia_id, autor, acao, observacao, created_at)
        VALUES (?, 'Sistema', 'Abertura do Protocolo', 'Protocolo registrado no armazém pelo motorista.', ?)
        """, (ocorrencia_id, agora))
        
    conn.commit()
