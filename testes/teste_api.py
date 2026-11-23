"""Testes de aceitação da API. Sem dependências além da biblioteca padrão."""
import http.cookiejar
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class Cliente:
    def __init__(self, base):
        self.base=base
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=None

    def request(self, method, path, payload=None, csrf=True):
        headers={}
        if payload is not None:
            headers['Content-Type']='application/json'
        if csrf and self.csrf:
            headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request(self.base+path,method=method,
             data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with self.opener.open(req,timeout=4) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())

    def state(self):
        status,content=self.request('GET','/api/state')
        assert status==200
        self.csrf=content['admin']['csrf']
        return content


class TestesIntegracao(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        server.DATA_DIR=Path(self.tmp.name)
        server.DB_PATH=server.DATA_DIR/'ligafacil.sqlite3'
        server.init_database()
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.RequestHandler)
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.worker.start()
        endereco='http://127.0.0.1:'+str(self.http.server_port)
        self.admin=Cliente(endereco)
        self.visitor=Cliente(endereco)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(timeout=3)
        self.tmp.cleanup()

    def test_fluxos_de_aprovacao(self):
        estado=self.visitor.state()
        self.assertTrue(estado['admin']['precisaCadastro'])
        self.assertEqual(len(estado['dados']['equipes']),4)
        self.assertEqual(len(estado['dados']['partidas']),4)

        # Visitante não altera dados.
        status,_=self.visitor.request('POST','/api/records/equipes',{'campeonatoId':1,'nome':'Equipe visitante','cidade':'RS'})
        self.assertEqual(status,401)

        # Primeiro cadastro: conta real (sem credenciais fixas).
        status,_=self.admin.request('POST','/api/setup',{'usuario':'organizador','senha':'SenhaComplexa!2026'})
        self.assertEqual(status,201)
        self.assertTrue(self.admin.state()['admin']['logado'])
        status,_=self.visitor.request('POST','/api/setup',{'usuario':'outro','senha':'SenhaComplexa!2026'})
        self.assertEqual(status,409)
        self.assertFalse(self.visitor.state()['admin']['logado'])

        # Requisição sem CSRF bloqueada.
        status,_=self.admin.request('POST','/api/records/equipes',{'campeonatoId':1,'nome':'SEM TOKEN'},csrf=False)
        self.assertEqual(status,403)

        # Campeonato e equipes: cadastros diferentes no mesmo torneio.
        status,camp=self.admin.request('POST','/api/records/campeonatos',{'nome':'Copa Teste','temporada':2026})
        self.assertEqual(status,200)
        cid=camp['id']
        status,team=self.admin.request('POST','/api/records/equipes',{'campeonatoId':cid,'nome':'São Paulo','cidade':'RS'})
        self.assertEqual(status,200)
        tid=team['id']
        status,_=self.admin.request('POST','/api/records/equipes',{'campeonatoId':cid,'nome':'  SAO   PAULO ','cidade':'Ijuí'})
        self.assertEqual(status,409)
        status,other=self.admin.request('POST','/api/records/equipes',{'campeonatoId':cid,'nome':'União','cidade':'RS'})
        self.assertEqual(status,200)
        oid=other['id']

        # Camisas repetidas na mesma equipe: inválidas.
        status,_=self.admin.request('POST','/api/records/jogadores',{'equipeId':tid,'nome':'Goleiro','camisa':1})
        self.assertEqual(status,200)
        status,_=self.admin.request('POST','/api/records/jogadores',{'equipeId':tid,'nome':'Reserva','camisa':1})
        self.assertEqual(status,409)

        # Placar incompleto e mesmo time duas vezes: inválidos.
        game={'campeonatoId':cid,'mandanteId':tid,'visitanteId':oid,'data':'2026-11-27T15:00','local':'Campo','golsMandante':None,'golsVisitante':None}
        status,_=self.admin.request('POST','/api/records/partidas',{**game,'visitanteId':tid})
        self.assertEqual(status,400)
        status,_=self.admin.request('POST','/api/records/partidas',{**game,'golsMandante':1})
        self.assertEqual(status,400)

        # Jogo futuro, seguido de resultado; visitantes enxergam logo na consulta.
        status,partida=self.admin.request('POST','/api/records/partidas',game)
        self.assertEqual(status,200)
        pid=partida['id']
        s=self.visitor.state()
        self.assertTrue(any(p['id']==pid and p['golsMandante'] is None for p in s['dados']['partidas']))
        status,_=self.admin.request('POST','/api/records/partidas',{**game,'id':pid,'golsMandante':2,'golsVisitante':1})
        self.assertEqual(status,200)
        atualizado=next(p for p in self.visitor.state()['dados']['partidas'] if p['id']==pid)
        self.assertEqual((atualizado['golsMandante'],atualizado['golsVisitante']),(2,1))
        status,_=self.admin.request('POST','/api/records/partidas',{**game,'id':pid,'golsMandante':0,'golsVisitante':0})
        self.assertEqual(status,200)
        atualizado=next(p for p in self.visitor.state()['dados']['partidas'] if p['id']==pid)
        self.assertEqual((atualizado['golsMandante'],atualizado['golsVisitante']),(0,0))

        # Duplicação de confronto no mesmo horário.
        status,_=self.admin.request('POST','/api/records/partidas',game)
        self.assertEqual(status,400)

        # Criação de outro admin, download de backup e permissão de leitura pública.
        status,_=self.admin.request('POST','/api/admins',{'usuario':'tecnico','senha':'OutraSenhaForte123'})
        self.assertEqual(status,201)
        novo_admin=Cliente(self.admin.base)
        status,_=novo_admin.request('POST','/api/login',{'usuario':'tecnico','senha':'OutraSenhaForte123'})
        self.assertEqual(status,200)
        self.assertTrue(novo_admin.state()['admin']['logado'])
        status,bkp=self.admin.request('GET','/api/export')
        self.assertEqual(status,200)
        self.assertTrue('dados' in bkp)
        status,_=self.visitor.request('GET','/api/export')
        self.assertEqual(status,401)
        # Excluir uma equipe remove seus jogadores e partidas por cascata.
        status,_=self.admin.request('DELETE',f'/api/records/equipes/{tid}')
        self.assertEqual(status,200)
        state=self.visitor.state()['dados']
        self.assertFalse(any(j['equipeId']==tid for j in state['jogadores']))
        self.assertFalse(any(p['mandanteId']==tid or p['visitanteId']==tid for p in state['partidas']))

    def test_logout_e_login(self):
        status,_=self.admin.request('POST','/api/setup',{'usuario':'supervisor','senha':'UmaSenhaSegura123'})
        self.assertEqual(status,201)
        self.admin.state()
        status,_=self.admin.request('POST','/api/logout',{})
        self.assertEqual(status,200)
        self.assertFalse(self.admin.state()['admin']['logado'])
        status,_=self.admin.request('POST','/api/login',{'usuario':'supervisor','senha':'errada'})
        self.assertEqual(status,401)
        status,_=self.admin.request('POST','/api/login',{'usuario':'supervisor','senha':'UmaSenhaSegura123'})
        self.assertEqual(status,200)
        self.assertTrue(self.admin.state()['admin']['logado'])


if __name__=='__main__':
    unittest.main()
