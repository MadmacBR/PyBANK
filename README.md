# 🏦 PyBank Digital & Analytics — API Bancária Segura

Aplicação Full-Stack de gerenciamento de contas bancárias desenvolvida em **Python (FastAPI)** com persistência relacional em **SQLite**, segurança criptográfica via **SHA-256** e painel web interativo com visualização gráfica da evolução financeira.

---

## 🚀 Funcionalidades Principais

* **API RESTful com FastAPI:** Endpoints estruturados para criação de contas, consulta de saldo, depósitos, saques, transferências e extratos, com documentação automática via Swagger UI (`/docs`).
* **Segurança da Informação:** As senhas são processadas e validadas utilizando hash criptográfico **SHA-256** (`hashlib`), nunca sendo armazenadas em texto plano.
* **Persistência Relacional & Transações Atômicas:** Banco de dados **SQLite** estruturado com chaves estrangeiras (`contas` e `transacoes`). As transferências entre contas utilizam controle transacional (`COMMIT` / `ROLLBACK`), garantindo integridade total dos saldos.
* **Dashboard Web & Analytics:** Interface responsiva estilizada com **Tailwind CSS**, consumindo a API via JavaScript (`fetch`) e exibindo gráficos dinâmicos da evolução acumulada do saldo com **Chart.js**.

---

## 🛠️ Tecnologias Utilizadas

* **Back-end:** Python 3.x, FastAPI, Uvicorn, Pydantic
* **Banco de Dados:** SQLite3
* **Segurança:** Hashlib (SHA-256)
* **Front-end:** HTML5, JavaScript (ES6+), Tailwind CSS, Chart.js

---

## 📦 Como Instalar e Executar Localmente

### 1. Clonar o repositório
```bash
git clone [[https://github.com/seu-usuario](https://github.com/MadmacBR/PyBANK)/pybank-digital.git]([https://github.com/seu-usuario](https://github.com/MadmacBR/PyBANK)/pybank-digital.git)
cd pybank-digital
