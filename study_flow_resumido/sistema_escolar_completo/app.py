from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
from functools import wraps
from config import DB_CONFIG

app = Flask(__name__)
app.secret_key = "troque-esta-chave-por-uma-chave-secreta"

def login_obrigatorio(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

def conectar():
    return mysql.connector.connect(**DB_CONFIG)

def estrutura(cursor, tabela):
    cursor.execute(f"SHOW COLUMNS FROM `{tabela}`")
    colunas = cursor.fetchall()
    cursor.execute("""
        SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
          AND REFERENCED_TABLE_NAME IS NOT NULL
    """, (DB_CONFIG["database"], tabela))
    fks = {r["COLUMN_NAME"]: (r["REFERENCED_TABLE_NAME"], r["REFERENCED_COLUMN_NAME"])
           for r in cursor.fetchall()}
    cursor.execute(f"SHOW KEYS FROM `{tabela}` WHERE Key_name = 'PRIMARY'")
    chaves = cursor.fetchall()
    pk = chaves[0]["Column_name"] if len(chaves) == 1 else None
    return colunas, fks, pk

def tabelas_banco(cursor):
    cursor.execute("SHOW TABLES")
    return [list(r.values())[0] for r in cursor.fetchall()]

def opcoes_fk(cursor, tabela_ref, coluna_ref):
    cursor.execute(f"SHOW COLUMNS FROM `{tabela_ref}`")
    cols = [r["Field"] for r in cursor.fetchall()]
    rotulo = next((c for c in ["nome", "titulo", "email"] if c in cols), coluna_ref)
    cursor.execute(f"SELECT `{coluna_ref}`, `{rotulo}` FROM `{tabela_ref}` ORDER BY 1")
    return [{"id": r[coluna_ref], "nome": r[rotulo]} for r in cursor.fetchall()]

def campos_form(cursor, tabela, valores=None):
    colunas, fks, pk = estrutura(cursor, tabela)
    resultado = []
    for col in colunas:
        nome = col["Field"]
        if col.get("Extra") == "auto_increment":
            continue
        item = {"nome": nome, "tipo": "text", "opcoes": [], "obrigatorio": col["Null"] == "NO",
                "valor": (valores or {}).get(nome, "")}
        tipo = col["Type"].lower()
        if nome in fks:
            ref_tabela, ref_coluna = fks[nome]
            item["tipo"] = "fk"
            item["opcoes"] = opcoes_fk(cursor, ref_tabela, ref_coluna)
        elif "enum(" in tipo:
            item["tipo"] = "select"
            item["opcoes"] = [{"id": v, "nome": v} for v in tipo.split("enum(",1)[1].rsplit(")",1)[0].replace("'", "").split(",")]
        elif "date" in tipo:
            item["tipo"] = "date"
        elif "int" in tipo:
            item["tipo"] = "number"
        elif "decimal" in tipo or "float" in tipo or "double" in tipo:
            item["tipo"] = "number_decimal"
        elif "text" in tipo:
            item["tipo"] = "textarea"
        if item["valor"] is None:
            item["valor"] = ""
        resultado.append(item)
    return resultado, pk

@app.route("/login", methods=["GET", "POST"])
def login():
    if "usuario_id" in session:
        return redirect(url_for("inicio"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        conexao = conectar()
        cursor = conexao.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id_usuario, nome, email, senha, tipo_usuario, ativo FROM usuarios WHERE email = %s LIMIT 1", (email,))
            usuario = cursor.fetchone()
            # Neste projeto escolar, a senha é comparada em texto simples conforme o requisito atual.
            if usuario and str(usuario.get("senha", "")) == senha and usuario.get("ativo", 1):
                session.clear()
                session["usuario_id"] = usuario["id_usuario"]
                session["usuario_nome"] = usuario["nome"]
                session["usuario_tipo"] = usuario["tipo_usuario"]
                flash("Login realizado com sucesso!")
                return redirect(url_for("inicio"))
            flash("E-mail ou senha incorretos, ou usuário inativo.")
        except Exception as erro:
            flash("Não foi possível entrar. Confira a conexão com o banco e se a tabela usuarios existe.")
        finally:
            cursor.close()
            conexao.close()
    return render_template("login.html")

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if "usuario_id" in session:
        return redirect(url_for("inicio"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not nome or not email or not senha:
            flash("Preencha todos os campos.")
            return render_template("cadastro.html")
        if len(nome) > 100 or len(email) > 150:
            flash("Nome ou e-mail muito longo.")
            return render_template("cadastro.html")
        if senha != confirmar_senha:
            flash("As senhas não são iguais.")
            return render_template("cadastro.html")
        if len(senha) < 6:
            flash("A senha precisa ter pelo menos 6 caracteres.")
            return render_template("cadastro.html")

        conexao = None
        cursor = None
        try:
            conexao = conectar()
            cursor = conexao.cursor(dictionary=True)
            cursor.execute("SELECT id_usuario FROM usuarios WHERE email = %s LIMIT 1", (email,))
            if cursor.fetchone():
                flash("Já existe uma conta com esse e-mail.")
                return render_template("cadastro.html")
            # O cadastro público cria apenas contas de aluno, nunca contas administrativas.
            cursor.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo_usuario, ativo) VALUES (%s, %s, %s, %s, %s)",
                (nome, email, senha, "ALUNO", True)
            )
            conexao.commit()
            flash("Conta criada! Agora você já pode entrar.")
            return redirect(url_for("login"))
        except Exception:
            if conexao:
                conexao.rollback()
            flash("Não foi possível criar a conta. Confira a conexão com o banco de dados.")
        finally:
            if cursor:
                cursor.close()
            if conexao:
                conexao.close()
    return render_template("cadastro.html")

@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_obrigatorio
def inicio():
    conexao = conectar()
    cursor = conexao.cursor(dictionary=True)
    try:
        nomes = tabelas_banco(cursor)
        return render_template("index.html", tabelas=nomes)
    finally:
        cursor.close()
        conexao.close()

@app.route("/<tabela>")
@login_obrigatorio
def listar(tabela):
    conexao = conectar()
    cursor = conexao.cursor(dictionary=True)
    try:
        nomes = tabelas_banco(cursor)
        if tabela not in nomes: return "Tabela não encontrada", 404
        colunas, fks, pk = estrutura(cursor, tabela)
        cursor.execute(f"SELECT * FROM `{tabela}`")
        registros = cursor.fetchall()

        # A listagem mostra informações úteis, não os IDs técnicos do banco.
        colunas_visiveis = []
        rotulos = {}
        for coluna in colunas:
            nome = coluna["Field"]
            if nome == pk or nome.lower() == "id" or nome.lower().startswith("id_"):
                if nome in fks:
                    tabela_ref, coluna_ref = fks[nome]
                    cursor.execute(f"SHOW COLUMNS FROM `{tabela_ref}`")
                    campos_ref = [c["Field"] for c in cursor.fetchall()]
                    preferidos = ["nome", "nome_completo", "titulo", "descricao", "email", "nome_disciplina", "nome_aluno"]
                    campo_rotulo = next((c for c in preferidos if c in campos_ref), None)
                    if campo_rotulo:
                        cursor.execute(f"SELECT `{coluna_ref}`, `{campo_rotulo}` FROM `{tabela_ref}`")
                        rotulos[nome] = {str(r[coluna_ref]): r[campo_rotulo] for r in cursor.fetchall()}
                        colunas_visiveis.append({"nome": nome, "rotulo": campo_rotulo.replace("_", " ").title(), "fk": True})
                continue
            colunas_visiveis.append({"nome": nome, "rotulo": nome.replace("_", " ").title(), "fk": False})

        registros_exibicao = []
        for registro in registros:
            exibicao = dict(registro)
            for nome, mapa in rotulos.items():
                valor = registro.get(nome)
                exibicao[nome] = mapa.get(str(valor), "—") if valor is not None else "—"
            registros_exibicao.append(exibicao)
        return render_template("lista.html", tabela=tabela, colunas=colunas_visiveis,
                               registros=registros_exibicao, pk=pk, pk_original=pk, tabelas=nomes)
    finally:
        cursor.close()
        conexao.close()

@app.route("/<tabela>/novo", methods=["GET", "POST"])
@login_obrigatorio
def novo(tabela):
    conexao = conectar()
    cursor = conexao.cursor(dictionary=True)
    try:
        if tabela not in tabelas_banco(cursor): return "Tabela não encontrada", 404
        campos, pk = campos_form(cursor, tabela)
        if request.method == "POST":
            nomes, valores = [], []
            for campo in campos:
                nome = campo["nome"]
                valor = request.form.get(nome, "").strip()
                if valor == "" and not campo["obrigatorio"]: valor = None
                if campo["tipo"] == "number" and valor is not None: valor = int(valor)
                if campo["tipo"] == "number_decimal" and valor is not None: valor = valor.replace(",", ".")
                if nome in ("ativo", "presente") and valor is not None: valor = int(valor)
                nomes.append(nome); valores.append(valor)
            sql = f"INSERT INTO `{tabela}` ({', '.join('`'+n+'`' for n in nomes)}) VALUES ({', '.join(['%s']*len(nomes))})"
            cursor.execute(sql, valores); conexao.commit()
            flash("Cadastro realizado!")
            return redirect(url_for("listar", tabela=tabela))
        return render_template("formulario.html", tabela=tabela, campos=campos, acao="Novo cadastro", tabelas=tabelas_banco(cursor))
    except Exception as erro:
        conexao.rollback()
        flash("Erro ao cadastrar: " + str(erro))
        campos, pk = campos_form(cursor, tabela, request.form)
        return render_template("formulario.html", tabela=tabela, campos=campos, acao="Novo cadastro", tabelas=tabelas_banco(cursor))
    finally:
        cursor.close(); conexao.close()

@app.route("/<tabela>/editar/<int:id>", methods=["GET", "POST"])
@login_obrigatorio
def editar(tabela, id):
    conexao = conectar()
    cursor = conexao.cursor(dictionary=True)
    try:
        if tabela not in tabelas_banco(cursor): return "Tabela não encontrada", 404
        colunas, fks, pk = estrutura(cursor, tabela)
        if not pk: return "Esta tabela usa chave primária composta e não tem edição nesta versão.", 400
        if request.method == "POST":
            campos, pk = campos_form(cursor, tabela)
            sets, valores = [], []
            for campo in campos:
                valor = request.form.get(campo["nome"], "").strip()
                if valor == "" and not campo["obrigatorio"]: valor = None
                if campo["tipo"] == "number" and valor is not None: valor = int(valor)
                if campo["tipo"] == "number_decimal" and valor is not None: valor = valor.replace(",", ".")
                sets.append(f"`{campo['nome']}`=%s"); valores.append(valor)
            valores.append(id)
            cursor.execute(f"UPDATE `{tabela}` SET {', '.join(sets)} WHERE `{pk}`=%s", valores)
            conexao.commit(); flash("Registro atualizado!")
            return redirect(url_for("listar", tabela=tabela))
        cursor.execute(f"SELECT * FROM `{tabela}` WHERE `{pk}`=%s", (id,))
        registro = cursor.fetchone()
        if not registro: return "Registro não encontrado", 404
        campos, pk = campos_form(cursor, tabela, registro)
        return render_template("formulario.html", tabela=tabela, campos=campos, acao="Editar registro", tabelas=tabelas_banco(cursor))
    except Exception as erro:
        conexao.rollback(); flash("Erro ao editar: " + str(erro))
        return redirect(url_for("listar", tabela=tabela))
    finally:
        cursor.close(); conexao.close()

@app.route("/<tabela>/excluir/<int:id>", methods=["POST"])
@login_obrigatorio
def excluir(tabela, id):
    conexao = conectar()
    cursor = conexao.cursor(dictionary=True)
    try:
        if tabela not in tabelas_banco(cursor): return "Tabela não encontrada", 404
        colunas, fks, pk = estrutura(cursor, tabela)
        if not pk: return "Esta tabela usa chave primária composta e não tem exclusão nesta versão.", 400
        cursor.execute(f"DELETE FROM `{tabela}` WHERE `{pk}`=%s", (id,))
        conexao.commit(); flash("Registro excluído, se não houver relacionamentos impedindo.")
    except Exception as erro:
        conexao.rollback(); flash("Não foi possível excluir: " + str(erro))
    finally:
        cursor.close(); conexao.close()
    return redirect(url_for("listar", tabela=tabela))

if __name__ == "__main__":
    app.run(debug=True)
