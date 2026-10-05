import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
from app.database import get_connection

# Funções seguras de Hash de senha usando PBKDF2 (padrão criptográfico da biblioteca padrão Python)
def hash_senha(senha: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        senha.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}${key.hex()}"

def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        salt, key_hex = senha_hash.split('$')
        nova_key = hashlib.pbkdf2_hmac(
            'sha256',
            senha.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(key_hex, nova_key.hex())
    except Exception:
        return False

def criar_sessao(usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    criado_em = datetime.now()
    expira_em = criado_em + timedelta(days=7) # Sessão válida por 7 dias
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessoes (token, usuario_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """, (token, usuario_id, criado_em.strftime("%Y-%m-%d %H:%M:%S"), expira_em.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return token

def obter_usuario_da_sessao(token: str) -> Optional[dict]:
    if not token:
        return None
        
    conn = get_connection()
    cursor = conn.cursor()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        SELECT u.id, u.nome, u.username, u.perfil, u.ativo
        FROM sessoes s
        JOIN usuarios u ON s.usuario_id = u.id
        WHERE s.token = ? AND s.expires_at > ? AND u.ativo = 1
    """, (token, agora))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None

def encerrar_sessao(token: str):
    if token:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessoes WHERE token = ?", (token,))
        conn.commit()
        conn.close()
