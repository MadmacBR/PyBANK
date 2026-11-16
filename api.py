import sqlite3
from datetime import datetime
from hashlib import sha256
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="PyBank Digital API",
    description="Sistema bancário seguro com autenticação SHA-256, SQLite e transações atômicas.",
    version="1.0.0"
)

# Habilita o CORS para permitir requisições do front-end HTML
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "contabancaria.db"


def inicializar_banco():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS contas
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY,
                       titular
                       TEXT
                       NOT
                       NULL,
                       saldo
                       REAL
                       NOT
                       NULL,
                       senha_hash
                       TEXT
                       NOT
                       NULL
                   )
                   """)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS transacoes
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       conta_id
                       INTEGER
                       NOT
                       NULL,
                       tipo
                       TEXT
                       NOT
                       NULL,
                       valor
                       REAL
                       NOT
                       NULL,
                       data_hora
                       TEXT
                       NOT
                       NULL,
                       FOREIGN
                       KEY
                   (
                       conta_id
                   ) REFERENCES contas
                   (
                       id
                   )
                       )
                   """)
    conn.commit()
    conn.close()


inicializar_banco()


# --- Modelos de Entrada (Pydantic) ---
class ContaCreate(BaseModel):
    id: int
    titular: str
    saldo_inicial: float = 0.0
    senha: str


class OperacaoRequest(BaseModel):
    valor: float
    senha: str


class TransferenciaRequest(BaseModel):
    conta_destino_id: int
    valor: float
    senha: str


# --- Rotas da API ---

@app.get("/")
def home():
    return {"mensagem": "API PyBank Digital ativa! Acesse /docs para documentação interativa."}


@app.post("/contas/", status_code=status.HTTP_201_CREATED)
def criar_conta(dados: ContaCreate):
    if len(dados.senha) < 6:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 6 caracteres.")

    senha_hash = sha256(dados.senha.encode()).hexdigest()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM contas WHERE id = ?", (dados.id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"A conta {dados.id} já existe.")

    try:
        cursor.execute(
            "INSERT INTO contas (id, titular, saldo, senha_hash) VALUES (?, ?, ?, ?)",
            (dados.id, dados.titular, dados.saldo_inicial, senha_hash)
        )
        if dados.saldo_inicial > 0:
            data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            cursor.execute(
                "INSERT INTO transacoes (conta_id, tipo, valor, data_hora) VALUES (?, ?, ?, ?)",
                (dados.id, "SALDO INICIAL", dados.saldo_inicial, data_atual)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {"mensagem": f"Conta {dados.id} criada com sucesso para {dados.titular}!"}


@app.get("/contas/{conta_id}")
def consultar_conta(conta_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, titular, saldo FROM contas WHERE id = ?", (conta_id,))
    resultado = cursor.fetchone()
    conn.close()

    if not resultado:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")

    return {"id": resultado[0], "titular": resultado[1], "saldo": resultado[2]}


@app.post("/contas/{conta_id}/depositar")
def depositar(conta_id: int, dados: OperacaoRequest):
    valor = abs(dados.valor)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT saldo FROM contas WHERE id = ?", (conta_id,))
    resultado = cursor.fetchone()
    if not resultado:
        conn.close()
        raise HTTPException(status_code=404, detail="Conta não encontrada.")

    novo_saldo = resultado[0] + valor
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    cursor.execute("UPDATE contas SET saldo = ? WHERE id = ?", (novo_saldo, conta_id))
    cursor.execute(
        "INSERT INTO transacoes (conta_id, tipo, valor, data_hora) VALUES (?, ?, ?, ?)",
        (conta_id, "DEPÓSITO", valor, data_atual)
    )
    conn.commit()
    conn.close()

    return {"mensagem": f"Depósito de R$ {valor:,.2f} realizado com sucesso.", "novo_saldo": novo_saldo}


@app.post("/contas/{conta_id}/sacar")
def sacar(conta_id: int, dados: OperacaoRequest):
    valor = abs(dados.valor)
    senha_hash = sha256(dados.senha.encode()).hexdigest()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT saldo, senha_hash FROM contas WHERE id = ?", (conta_id,))
    resultado = cursor.fetchone()

    if not resultado:
        conn.close()
        raise HTTPException(status_code=404, detail="Conta não encontrada.")

    saldo_atual, stored_hash = resultado

    if senha_hash != stored_hash:
        conn.close()
        raise HTTPException(status_code=401, detail="Senha incorreta.")

    if valor > saldo_atual:
        conn.close()
        raise HTTPException(status_code=400, detail="Saldo insuficiente.")

    novo_saldo = saldo_atual - valor
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    cursor.execute("UPDATE contas SET saldo = ? WHERE id = ?", (novo_saldo, conta_id))
    cursor.execute(
        "INSERT INTO transacoes (conta_id, tipo, valor, data_hora) VALUES (?, ?, ?, ?)",
        (conta_id, "SAQUE", valor, data_atual)
    )
    conn.commit()
    conn.close()

    return {"mensagem": f"Saque de R$ {valor:,.2f} realizado com sucesso.", "novo_saldo": novo_saldo}


@app.post("/contas/{conta_id}/transferir")
def transferir(conta_id: int, dados: TransferenciaRequest):
    valor = abs(dados.valor)
    if dados.conta_destino_id == conta_id:
        raise HTTPException(status_code=400, detail="Não é possível transferir para a própria conta.")

    senha_hash = sha256(dados.senha.encode()).hexdigest()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT saldo, senha_hash FROM contas WHERE id = ?", (conta_id,))
    origem = cursor.fetchone()
    if not origem or origem[1] != senha_hash:
        conn.close()
        raise HTTPException(status_code=401, detail="Conta de origem não encontrada ou senha incorreta.")

    saldo_origem = origem[0]
    if valor > saldo_origem:
        conn.close()
        raise HTTPException(status_code=400, detail="Saldo insuficiente para transferência.")

    cursor.execute("SELECT saldo FROM contas WHERE id = ?", (dados.conta_destino_id,))
    destino = cursor.fetchone()
    if not destino:
        conn.close()
        raise HTTPException(status_code=404, detail="Conta de destino não encontrada.")

    saldo_destino = destino[0]
    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    try:
        cursor.execute("UPDATE contas SET saldo = ? WHERE id = ?", (saldo_origem - valor, conta_id))
        cursor.execute("UPDATE contas SET saldo = ? WHERE id = ?", (saldo_destino + valor, dados.conta_destino_id))

        cursor.execute(
            "INSERT INTO transacoes (conta_id, tipo, valor, data_hora) VALUES (?, ?, ?, ?)",
            (conta_id, "TRANSF. ENVIADA", valor, data_atual)
        )
        cursor.execute(
            "INSERT INTO transacoes (conta_id, tipo, valor, data_hora) VALUES (?, ?, ?, ?)",
            (dados.conta_destino_id, "TRANSF. RECEBIDA", valor, data_atual)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Erro interno na transação: {e}")
    finally:
        conn.close()

    return {
        "mensagem": f"Transferência de R$ {valor:,.2f} realizada para a conta {dados.conta_destino_id} com sucesso."}


@app.get("/contas/{conta_id}/extrato")
def extrato(conta_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM contas WHERE id = ?", (conta_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Conta não encontrada.")

    cursor.execute(
        "SELECT data_hora, tipo, valor FROM transacoes WHERE conta_id = ? ORDER BY id ASC",
        (conta_id,)
    )
    movimentacoes = [{"data_hora": r[0], "tipo": r[1], "valor": r[2]} for r in cursor.fetchall()]
    conn.close()

    return {"conta_id": conta_id, "extrato": movimentacoes}