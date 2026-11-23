#!/usr/bin/env python3
"""LigaFácil: servidor HTTP e API SQLite, sem dependências de terceiros.
Execute: python server.py (Python 3.10+). Uso recomendado em rede local;
para publicação na internet configure HTTPS em um proxy reverso.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
from contextlib import closing
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import unicodedata

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('LIGAFACIL_DATA_DIR', str(BASE / 'data'))).resolve()
DB_PATH = DATA_DIR / 'ligafacil.sqlite3'
PORT = int(os.environ.get('PORT', '8000'))
AUTH_DURATION = 12 * 60 * 60
MAX_BODY = 512_000


class BadRequest(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def connection():
    db = sqlite3.connect(str(DB_PATH), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 15000')
    return db


def key_name(name):
    # Normalização única, inclusive para letras acentuadas e espaços múltiplos.
    clean = ' '.join(name.split()).casefold()
    return ''.join(c for c in unicodedata.normalize('NFKD', clean) if not unicodedata.combining(c))


def validate_text(data, name, size, required=False):
    val = data.get(name, '')
    if not isinstance(val, str):
        raise BadRequest(f'Campo {name} inválido.')
    val = ' '.join(val.strip().split())
    if len(val) > size or (required and not val):
        raise BadRequest(f'Campo {name} deve conter entre {1 if required else 0} e {size} caracteres.')
    return val


def validate_int(data, name, minimum, maximum, nullable=False):
    raw = data.get(name)
    if nullable and raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum or raw > maximum:
        raise BadRequest(f'Campo {name} deve ser inteiro entre {minimum} e {maximum}.')
    return raw


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    hash_bytes = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f'scrypt$16384$8$1${salt.hex()}${hash_bytes.hex()}'


def verify_password(password, saved):
    try:
        method, n, r, p, salt, digest = saved.split('$')
        if method != 'scrypt':
            return False
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(test, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def init_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    novo_banco = not DB_PATH.exists()
    with closing(connection()) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY,
                usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
                senha_hash TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
                csrf TEXT NOT NULL,
                expira INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campeonatos (
                id INTEGER PRIMARY KEY,
                nome TEXT NOT NULL,
                nome_key TEXT NOT NULL,
                temporada INTEGER NOT NULL CHECK(temporada BETWEEN 2000 AND 2100),
                UNIQUE (nome_key, temporada)
            );
            CREATE TABLE IF NOT EXISTS equipes (
                id INTEGER PRIMARY KEY,
                campeonato_id INTEGER NOT NULL REFERENCES campeonatos(id) ON DELETE CASCADE,
                nome TEXT NOT NULL,
                nome_key TEXT NOT NULL,
                cidade TEXT NOT NULL DEFAULT '',
                UNIQUE(campeonato_id,nome_key)
            );
            CREATE TABLE IF NOT EXISTS jogadores (
                id INTEGER PRIMARY KEY,
                equipe_id INTEGER NOT NULL REFERENCES equipes(id) ON DELETE CASCADE,
                nome TEXT NOT NULL,
                camisa INTEGER NOT NULL CHECK(camisa BETWEEN 1 AND 99),
                UNIQUE(equipe_id,camisa)
            );
            CREATE TABLE IF NOT EXISTS partidas (
                id INTEGER PRIMARY KEY,
                campeonato_id INTEGER NOT NULL REFERENCES campeonatos(id) ON DELETE CASCADE,
                mandante_id INTEGER NOT NULL REFERENCES equipes(id) ON DELETE CASCADE,
                visitante_id INTEGER NOT NULL REFERENCES equipes(id) ON DELETE CASCADE,
                data TEXT NOT NULL,
                local TEXT NOT NULL DEFAULT '',
                gols_mandante INTEGER CHECK(gols_mandante BETWEEN 0 AND 99),
                gols_visitante INTEGER CHECK(gols_visitante BETWEEN 0 AND 99),
                CHECK(mandante_id != visitante_id),
                CHECK((gols_mandante IS NULL) = (gols_visitante IS NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_partida_camp ON partidas(campeonato_id, data);
        ''')
        if novo_banco:
            today = dt.datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
            past1 = (today - dt.timedelta(days=10)).isoformat(timespec='minutes')
            past2 = (today - dt.timedelta(days=7)).isoformat(timespec='minutes')
            next1 = (today + dt.timedelta(days=3)).isoformat(timespec='minutes')
            next2 = (today + dt.timedelta(days=3, hours=2)).isoformat(timespec='minutes')
            db.execute('INSERT INTO campeonatos(id,nome,nome_key,temporada) VALUES (1,?,?,?)',
                       ('Copa Municipal de Futebol Amador', key_name('Copa Municipal de Futebol Amador'), today.year))
            for eid, nome, cidade in [(1,'Atlético Ijuí','Ijuí'),(2,'União FC','Ijuí'),(3,'Estrela do Sul','Catuípe'),(4,'Juventude Amador','Ajuricaba')]:
                db.execute('INSERT INTO equipes(id,campeonato_id,nome,nome_key,cidade) VALUES (?,1,?,?,?)', (eid,nome,key_name(nome),cidade))
            for jid,eid,nome,camisa in [(1,1,'Pedro Oliveira',9),(2,1,'Bruno Martins',10),(3,2,'Lucas Silva',7),(4,2,'Rafael Souza',11),(5,3,'Diego Pereira',8),(6,4,'Gabriel Costa',5)]:
                db.execute('INSERT INTO jogadores(id,equipe_id,nome,camisa) VALUES (?,?,?,?)', (jid,eid,nome,camisa))
            for cid,home,away,date,sc1,sc2 in [(1,1,2,past1,2,1),(2,3,4,past2,0,0),(3,1,3,next1,None,None),(4,2,4,next2,None,None)]:
                db.execute('INSERT INTO partidas(id,campeonato_id,mandante_id,visitante_id,data,local,gols_mandante,gols_visitante) VALUES (?,1,?,?,?,\'Campo Municipal\',?,?)', (cid,home,away,date,sc1,sc2))
        db.commit()


def rows_as_dicts(db, query):
    return [dict(r) for r in db.execute(query)]


def get_data(db):
    return {
        'campeonatos': rows_as_dicts(db, 'SELECT id,nome,temporada FROM campeonatos ORDER BY temporada DESC,id'),
        'equipes': rows_as_dicts(db, 'SELECT id,campeonato_id AS campeonatoId,nome,cidade FROM equipes ORDER BY id'),
        'jogadores': rows_as_dicts(db, 'SELECT id,equipe_id AS equipeId,nome,camisa FROM jogadores ORDER BY id'),
        'partidas': rows_as_dicts(db, 'SELECT id,campeonato_id AS campeonatoId,mandante_id AS mandanteId,visitante_id AS visitanteId,data,local,gols_mandante AS golsMandante,gols_visitante AS golsVisitante FROM partidas ORDER BY id'),
    }


def validate_username_password(payload):
    username = validate_text(payload, 'usuario', 40, required=True)
    password = payload.get('senha', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username):
        raise BadRequest('Usuário deve ter de 3 a 40 caracteres (letras, números, _, ponto ou hífen).')
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise BadRequest('A senha precisa ter entre 10 e 128 caracteres.')
    return username, password


def save_record(db, kind, payload):
    raw_id = payload.get('id')
    if raw_id is not None and (isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 1):
        raise BadRequest('Identificador inválido.')
    rid = raw_id
    table = {'campeonatos':'campeonatos','equipes':'equipes','jogadores':'jogadores','partidas':'partidas'}.get(kind)
    if not table:
        raise BadRequest('Tipo de registro inválido.', 404)
    if rid is not None and not db.execute(f'SELECT 1 FROM {table} WHERE id = ?', (rid,)).fetchone():
        raise BadRequest('Registro não encontrado.', 404)

    if kind == 'campeonatos':
        nome = validate_text(payload, 'nome', 80, True)
        temporada = validate_int(payload, 'temporada', 2000, 2100)
        fields = {'nome':nome, 'nome_key':key_name(nome), 'temporada':temporada}
    elif kind == 'equipes':
        campeonato = validate_int(payload,'campeonatoId',1,2**31)
        if not db.execute('SELECT 1 FROM campeonatos WHERE id=?',(campeonato,)).fetchone():
            raise BadRequest('Campeonato não encontrado.')
        if rid is not None:
            origem = db.execute('SELECT campeonato_id FROM equipes WHERE id=?',(rid,)).fetchone()
            if origem and origem['campeonato_id'] != campeonato:
                raise BadRequest('Não é possível mover uma equipe para outro campeonato. Cadastre-a novamente.')
        nome = validate_text(payload,'nome',80,True)
        fields = {'campeonato_id':campeonato, 'nome':nome, 'nome_key':key_name(nome), 'cidade':validate_text(payload,'cidade',70)}
    elif kind == 'jogadores':
        equipe = validate_int(payload,'equipeId',1,2**31)
        if not db.execute('SELECT 1 FROM equipes WHERE id=?',(equipe,)).fetchone():
            raise BadRequest('Equipe não encontrada.')
        fields = {'equipe_id':equipe,'nome':validate_text(payload,'nome',80,True),'camisa':validate_int(payload,'camisa',1,99)}
    else:
        campeonato = validate_int(payload,'campeonatoId',1,2**31)
        mandante = validate_int(payload,'mandanteId',1,2**31)
        visitante = validate_int(payload,'visitanteId',1,2**31)
        if mandante == visitante:
            raise BadRequest('Escolha duas equipes diferentes.')
        ok = db.execute('SELECT COUNT(*) FROM equipes WHERE campeonato_id=? AND id IN (?,?)', (campeonato,mandante,visitante)).fetchone()[0]
        if ok != 2:
            raise BadRequest('As duas equipes devem pertencer ao campeonato.')
        data = validate_text(payload,'data',16,True)
        try:
            instante = dt.datetime.fromisoformat(data)
            if len(data) != 16 or data[10] != 'T' or not 2000 <= instante.year <= 2100:
                raise ValueError('Formato inválido')
        except (ValueError, TypeError):
            raise BadRequest('Informe data e horário válidos.')
        gols_casa = validate_int(payload,'golsMandante',0,99,True)
        gols_fora = validate_int(payload,'golsVisitante',0,99,True)
        if (gols_casa is None) != (gols_fora is None):
            raise BadRequest('Informe ambos os gols, ou deixe ambos em branco.')
        # Uma mesma dupla de equipes não pode jogar duas vezes exatamente no mesmo horário.
        repeated = db.execute('''SELECT 1 FROM partidas WHERE campeonato_id=? AND data=? AND id!=?
                AND ((mandante_id=? AND visitante_id=?) OR (mandante_id=? AND visitante_id=?))''',
                (campeonato,data,rid or 0,mandante,visitante,visitante,mandante)).fetchone()
        if repeated:
            raise BadRequest('Já existe partida entre estas equipes nesse horário.')
        fields = {'campeonato_id':campeonato, 'mandante_id':mandante, 'visitante_id':visitante,
                  'data':data, 'local':validate_text(payload,'local',100), 'gols_mandante':gols_casa,'gols_visitante':gols_fora}
    keys = list(fields.keys())
    if rid:
        db.execute(f"UPDATE {table} SET {', '.join(k+'=?' for k in keys)} WHERE id=?", (*fields.values(),rid))
        return rid
    cur = db.execute(f"INSERT INTO {table}({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",tuple(fields.values()))
    return cur.lastrowid


class RequestHandler(BaseHTTPRequestHandler):
    server_version = 'LigaFacil/2.0'

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        super().end_headers()

    def json_response(self, obj, status=200, cookie=None, download=None):
        body = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control','no-store')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def get_session(self, db):
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie',''))
            raw = cookies['ligafacil_sid'].value
        except (KeyError, ValueError):
            return None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return db.execute('''SELECT a.id, a.usuario, s.csrf FROM sessions s
                            JOIN admins a ON a.id=s.admin_id
                            WHERE s.token_hash=? AND s.expira>?''', (digest,int(dt.datetime.now().timestamp()))).fetchone()

    def require_session(self, db, csrf=True):
        session = self.get_session(db)
        if not session:
            raise BadRequest('Acesse sua conta de administrador.',401)
        if csrf and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
            raise BadRequest('Sessão inválida. Atualize a página e tente novamente.',403)
        return session

    def cookie_header(self, value='', expire=False):
        secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
        if expire:
            return 'ligafacil_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + secure
        return f'ligafacil_sid={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={AUTH_DURATION}' + secure

    def establish_session(self, db, admin_id):
        token = secrets.token_urlsafe(40)
        csrf = secrets.token_urlsafe(30)
        expire = int(dt.datetime.now().timestamp())+AUTH_DURATION
        db.execute('DELETE FROM sessions WHERE expira<?',(int(dt.datetime.now().timestamp()),))
        db.execute('INSERT INTO sessions(token_hash,admin_id,csrf,expira) VALUES (?,?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(),admin_id,csrf,expire))
        return self.cookie_header(token)

    def parse_json(self):
        length = self.headers.get('Content-Length')
        if not length or not length.isdigit() or int(length)>MAX_BODY:
            raise BadRequest('Requisição sem tamanho válido ou muito grande.',413)
        if not self.headers.get('Content-Type','').startswith('application/json'):
            raise BadRequest('O conteúdo precisa ser JSON.')
        try:
            body = json.loads(self.rfile.read(int(length)).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise BadRequest('JSON inválido.')
        if not isinstance(body,dict):
            raise BadRequest('Formato inválido.')
        return body

    def same_origin(self):
        origin = self.headers.get('Origin')
        if origin and origin != f"http://{self.headers.get('Host')}" and origin != f"https://{self.headers.get('Host')}":
            raise BadRequest('Origem não autorizada.',403)

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path in ('/api/state','/api/export'):
                with closing(connection()) as db:
                    if path == '/api/export':
                        self.require_session(db,csrf=False)
                        self.json_response({'version':2,'exportadoEm':dt.datetime.now().isoformat(timespec='seconds'),
                                            'dados':get_data(db)}, download='ligafacil-backup.json')
                        return
                    session = self.get_session(db)
                    setup = db.execute('SELECT NOT EXISTS(SELECT 1 FROM admins)').fetchone()[0] == 1
                    self.json_response({'dados':get_data(db),'admin':{'logado':bool(session),
                        'usuario':session['usuario'] if session else None,
                        'csrf':session['csrf'] if session else None,
                        'precisaCadastro':setup}})
                return
            static = {'/':'index.html','/index.html':'index.html','/style.css':'style.css','/script.js':'script.js','/favicon.ico':None}
            if path not in static:
                self.send_error(404,'Arquivo não encontrado')
                return
            if static[path] is None:
                self.send_response(204)
                self.end_headers()
                return
            file = BASE / static[path]
            body = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            self.wfile.write(body)
        except BadRequest as e:
            self.json_response({'erro':str(e)},e.code)
        except (sqlite3.Error, OSError):
            self.json_response({'erro':'Falha ao consultar dados.'},500)

    def do_POST(self):
        try:
            self.same_origin()
            body = self.parse_json()
            path = urlsplit(self.path).path
            with closing(connection()) as db:
                if path == '/api/setup':
                    username,password = validate_username_password(body)
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute('SELECT EXISTS(SELECT 1 FROM admins)').fetchone()[0]:
                        raise BadRequest('O administrador inicial já foi cadastrado.',409)
                    result = db.execute('INSERT INTO admins(usuario,senha_hash) VALUES (?,?)',(username,hash_password(password)))
                    cookie = self.establish_session(db,result.lastrowid)
                    db.commit()
                    self.json_response({'ok':True},201,cookie)
                    return
                if path == '/api/login':
                    username = validate_text(body,'usuario',40,True)
                    password = body.get('senha','')
                    admin = db.execute('SELECT * FROM admins WHERE usuario=? COLLATE NOCASE',(username,)).fetchone()
                    if not isinstance(password,str) or not admin or not verify_password(password,admin['senha_hash']):
                        raise BadRequest('Usuário ou senha incorretos.',401)
                    cookie = self.establish_session(db,admin['id'])
                    db.commit()
                    self.json_response({'ok':True},cookie=cookie)
                    return
                session = self.require_session(db)
                if path == '/api/logout':
                    cookie = self.headers.get('Cookie','')
                    match = re.search(r'(?:^|;)\s*ligafacil_sid=([^;]+)',cookie)
                    if match:
                        db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(match.group(1).encode()).hexdigest(),))
                    db.commit()
                    self.json_response({'ok':True},cookie=self.cookie_header(expire=True))
                    return
                if path == '/api/admins':
                    username,password = validate_username_password(body)
                    db.execute('INSERT INTO admins(usuario,senha_hash) VALUES (?,?)',(username,hash_password(password)))
                    db.commit()
                    self.json_response({'ok':True},201)
                    return
                match = re.fullmatch(r'/api/records/(campeonatos|equipes|jogadores|partidas)',path)
                if not match:
                    raise BadRequest('Rota não encontrada.',404)
                ident = save_record(db,match.group(1),body)
                db.commit()
                self.json_response({'ok':True,'id':ident})
        except BadRequest as e:
            self.json_response({'erro':str(e)},e.code)
        except sqlite3.IntegrityError as e:
            message = str(e)
            if 'equipes.campeonato_id, equipes.nome_key' in message:
                detail = 'Já existe uma equipe com esse nome neste campeonato.'
            elif 'jogadores.equipe_id, jogadores.camisa' in message:
                detail = 'Este número de camisa já pertence a um jogador dessa equipe.'
            elif 'campeonatos.nome_key, campeonatos.temporada' in message:
                detail = 'Já existe um campeonato com esse nome nessa temporada.'
            elif 'admins.usuario' in message:
                detail = 'Esse nome de usuário já está em uso.'
            else:
                detail = 'Registro inválido ou em conflito com outro cadastro.'
            self.json_response({'erro':detail},409)
        except sqlite3.Error:
            self.json_response({'erro':'Não foi possível salvar os dados.'},500)

    def do_DELETE(self):
        try:
            self.same_origin()
            path = urlsplit(self.path).path
            match = re.fullmatch(r'/api/records/(campeonatos|equipes|jogadores|partidas)/(\d+)',path)
            if not match:
                raise BadRequest('Rota não encontrada.',404)
            with closing(connection()) as db:
                self.require_session(db)
                result = db.execute(f'DELETE FROM {match.group(1)} WHERE id=?',(int(match.group(2)),))
                if result.rowcount==0:
                    raise BadRequest('Registro não encontrado.',404)
                db.commit()
                self.json_response({'ok':True})
        except BadRequest as e:
            self.json_response({'erro':str(e)},e.code)
        except sqlite3.Error:
            self.json_response({'erro':'Não foi possível excluir o registro.'},500)


if __name__ == '__main__':
    init_database()
    print(f'LigaFácil 2.0 disponível em http://localhost:{PORT} (Ctrl+C encerra)')
    print(f'Banco de dados: {DB_PATH}')
    ThreadingHTTPServer(('0.0.0.0',PORT),RequestHandler).serve_forever()
