# 🌲 Suzano - Gestão de Coletas FOB & Tratativa de Divergências

Sistema completo desenvolvido para registro, triagem e resolução ágil de divergências de cargas em coletas **FOB** nos armazéns da Suzano.

Permite que motoristas e clientes externos abram ocorrências na doca com fotos diretamente pelo celular, e que a equipe interna da Suzano realize a triagem direcionando os casos para as filas especializadas (**Fiscal, Armazém/Doca, Qualidade e Comercial**).

---

## 🚀 Como Iniciar o Sistema

### Método 1: Duplo Clique (Mais Fácil)
Dê um duplo clique no arquivo:
```
iniciar.bat
```

### Método 2: Pelo Terminal
Abra o PowerShell na pasta do projeto e execute:
```powershell
.\venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🌐 Como Acessar

* **No seu computador (Navegador):**
  * Tela Inicial / Hub: `http://localhost:8000`
  * Abrir Ocorrência (Mobile/Motorista): `http://localhost:8000/nova-ocorrencia`
  * Mesa de Triagem Suzano: `http://localhost:8000/painel`
  * Consulta de Protocolo: `http://localhost:8000/rastreio`

* **No Celular do Motorista / Outros Computadores (Mesma rede Wi-Fi ou VPN da Suzano):**
  * Descubra seu IP no Windows (`ipconfig`).
  * Exemplo: `http://192.168.1.150:8000/nova-ocorrencia`
  * O motorista pode acessar diretamente do celular para tirar fotos da carga na doca.

---

## 🔄 Fluxo Operacional

1. **Abertura Expressa (Motorista / Conferente na doca):**
   * Informa Nota Fiscal, Placa do Veículo e Transportadora.
   * Seleciona o motivo (*Avaria, Falta, Sobra, Mercadoria Trocada, Divergência Fiscal*).
   * Tira fotos ou anexa imagens com a câmera do celular.
   * Recebe na hora o número do protocolo (Ex: `FOB-2026-00101`).

2. **Triagem na Mesa Suzano (`/painel`):**
   * Visualização em tempo real das novas ocorrências com SLA.
   * Filtros por filas especializadas:
     * **Fiscal:** NF de devolução, recusa de canhoto, carta de correção.
     * **Armazém / Doca:** Recontagem física, conferência de paletes e fardos.
     * **Qualidade:** Laudo técnico de umidade, impacto ou avaria de embalagem.
     * **Comercial:** Acordo comercial, autorização de desconto ou reenvio.

3. **Despacho e Conclusão:**
   * Registro de cada movimentação no histórico de auditoria (quem fez, quando e parecer).
   * Resolução final disponibilizada para consulta do motorista no link de rastreio.
   * Exportação dos dados para relatórios em Excel (`.csv`).

---

## 🗄️ Estrutura do Projeto

* `app/database.py`: Banco de dados SQLite automático (`data/fob_tracker.db`) com histórico de auditoria e dados simulados.
* `app/main.py`: Servidor FastAPI com rotas web, upload de imagens e relatórios.
* `templates/`: Telas responsivas em Tailwind CSS e ícones Lucide.
* `uploads/`: Pasta onde ficam salvas as fotos tiradas pelos motoristas.
