'use strict';
// LigaFácil 2.0 — cliente sem dependências. Todos os dados são lidos e gravados via API.
const $ = id => document.getElementById(id);
let dados = {campeonatos:[], equipes:[], jogadores:[], partidas:[]};
let campeonatoAtual = null;
let paginaAtual = 'inicio';
let adminLogado = false;
let csrf = null;
let requerCadastro = false;
let usuarioAtual = null;
let consultaAnterior = '';

function escapar(valor) {
  return String(valor ?? '').replace(/[&<>"']/g, caractere => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[caractere]));
}
function mostrarAviso(texto, erro=false) {
  $('aviso').textContent = texto;
  $('aviso').className = 'aviso'+(erro?' erro':'');
}
function nomeEquipe(id) { return dados.equipes.find(e=>e.id===id)?.nome || 'Equipe removida'; }
function equipesAtuais() { return dados.equipes.filter(e=>e.campeonatoId===campeonatoAtual); }
function partidasAtuais() { return dados.partidas.filter(p=>p.campeonatoId===campeonatoAtual); }
function partidaFinalizada(p) { return Number.isInteger(p.golsMandante)&&Number.isInteger(p.golsVisitante); }
function dataFormatada(data) {
  const d = new Date(data);
  return Number.isNaN(d.getTime()) ? 'Data inválida' : new Intl.DateTimeFormat('pt-BR', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(d);
}
async function requisicao(path, options={}) {
  const headers = {};
  if (options.body!==undefined) headers['Content-Type']='application/json';
  if (csrf && options.method && options.method!=='GET') headers['X-CSRF-Token']=csrf;
  let response;
  try {
    response = await fetch(path,{credentials:'same-origin',method:options.method||'GET',
      headers,body:options.body===undefined?undefined:JSON.stringify(options.body),cache:'no-store'});
  } catch (_) { throw new Error('Servidor indisponível. Verifique a conexão com o LigaFácil.'); }
  let resultado;
  try { resultado=await response.json(); } catch (_) { throw new Error('Resposta inválida do servidor.'); }
  if (!response.ok) throw new Error(resultado.erro||'Não foi possível completar a operação.');
  return resultado;
}
async function buscarDados(silencioso=false) {
  try {
    const estado = await requisicao('/api/state');
    const assinatura=JSON.stringify(estado.dados);
    const loginMudou = adminLogado !== estado.admin.logado || requerCadastro !== estado.admin.precisaCadastro;
    adminLogado=estado.admin.logado;
    csrf=estado.admin.csrf;
    requerCadastro=estado.admin.precisaCadastro;
    usuarioAtual=estado.admin.usuario;
    if (assinatura!==consultaAnterior || loginMudou) {
      dados=estado.dados;
      consultaAnterior=assinatura;
      if (!campeonatoAtual) campeonatoAtual=dados.campeonatos[0]?.id||null;
      atualizarTudo();
    } else {
      // O tempo passa mesmo sem alteração de registros: atualiza jogos atrasados.
      atualizarPublico();
    }
    $('statusAtualizacao').textContent='Sincronizado com o servidor · atualização a cada 15 segundos';
  } catch (erro) {
    $('statusAtualizacao').textContent='Sem conexão com o servidor';
    if (!silencioso) mostrarAviso(erro.message,true);
  }
}
function calcularClassificacao() {
  const tabela=equipesAtuais().map(e=>({...e,P:0,J:0,V:0,E:0,D:0,GP:0,GC:0,SG:0}));
  for (const p of partidasAtuais().filter(partidaFinalizada)) {
    const casa=tabela.find(t=>t.id===p.mandanteId), fora=tabela.find(t=>t.id===p.visitanteId);
    if (!casa||!fora) continue;
    casa.J++;fora.J++;
    casa.GP+=p.golsMandante;casa.GC+=p.golsVisitante;
    fora.GP+=p.golsVisitante;fora.GC+=p.golsMandante;
    if (p.golsMandante>p.golsVisitante) {casa.V++;casa.P+=3;fora.D++;}
    else if (p.golsMandante<p.golsVisitante) {fora.V++;fora.P+=3;casa.D++;}
    else {casa.E++;fora.E++;casa.P++;fora.P++;}
  }
  tabela.forEach(t=>t.SG=t.GP-t.GC);
  return tabela.sort((a,b)=>b.P-a.P||b.V-a.V||b.SG-a.SG||b.GP-a.GP||a.nome.localeCompare(b.nome,'pt-BR'));
}
function tabelaClassificacao(resumida=false) {
  const times=calcularClassificacao();
  if (!times.length) return '<p class="vazio">Nenhuma equipe cadastrada.</p>';
  const colunas=resumida?['P','J','SG']:['P','J','V','E','D','GP','GC','SG'];
  return `<div class="tabela-container"><table class="tabela"><thead><tr><th>#</th><th>Equipe</th>${colunas.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>`+
    times.map((t,i)=>`<tr><td class="colocacao">${i+1}º</td><td>${escapar(t.nome)}</td>${colunas.map(c=>`<td>${t[c]}</td>`).join('')}</tr>`).join('')+'</tbody></table></div>';
}
function listaPartidas(partidas) {
  if (!partidas.length) return '<p class="vazio">Nenhuma partida encontrada.</p>';
  return partidas.map(p=>{
    const atrasado=!partidaFinalizada(p) && new Date(p.data).getTime()<Date.now();
    const estado=partidaFinalizada(p)?'Encerrado':atrasado?'Aguardando resultado':'Agendado';
    return `<article class="jogo ${atrasado?'jogo-atrasado':''}"><div class="jogo-topo"><span>${escapar(dataFormatada(p.data))}</span><span>${estado}</span></div><div class="confronto"><span class="nome-time">${escapar(nomeEquipe(p.mandanteId))}</span><span class="placar">${partidaFinalizada(p)?`${p.golsMandante} × ${p.golsVisitante}`:'×'}</span><span class="nome-time">${escapar(nomeEquipe(p.visitanteId))}</span></div><div class="local-jogo">📍 ${escapar(p.local||'Local a definir')}</div></article>`;
  }).join('');
}
function atualizarPublico() {
  const times=equipesAtuais(),partidas=partidasAtuais(),agora=Date.now();
  const futuras=partidas.filter(p=>!partidaFinalizada(p)&&new Date(p.data).getTime()>=agora).sort((a,b)=>a.data.localeCompare(b.data));
  const pendentes=partidas.filter(p=>!partidaFinalizada(p)&&new Date(p.data).getTime()<agora).sort((a,b)=>b.data.localeCompare(a.data));
  const concluidas=partidas.filter(partidaFinalizada).sort((a,b)=>b.data.localeCompare(a.data));
  $('campeonatosDisponiveis').innerHTML=dados.campeonatos.length ? dados.campeonatos.map(c=>{
    const equipes=dados.equipes.filter(e=>e.campeonatoId===c.id).length;
    const jogos=dados.partidas.filter(p=>p.campeonatoId===c.id).length;
    return `<button type="button" class="card-campeonato ${c.id===campeonatoAtual?'selecionado':''}" data-selecionar="${c.id}"><span class="selo-campeonato">Temporada ${c.temporada}</span><strong>${escapar(c.nome)}</strong><small>${equipes} equipes · ${jogos} partidas</small></button>`;
  }).join(''):'<p class="vazio">Nenhum campeonato cadastrado.</p>';
  const stats=[['Equipes',times.length],['Partidas',partidas.length],['Resultados',concluidas.length],['Próximos jogos',futuras.length]];
  $('resumo').innerHTML=stats.map(([nome,valor])=>`<div class="estatistica"><strong>${valor}</strong><span>${nome}</span></div>`).join('');
  $('classificacaoResumo').innerHTML=tabelaClassificacao(true);
  $('classificacaoCompleta').innerHTML=tabelaClassificacao();
  $('proximosResumo').innerHTML=listaPartidas(futuras.slice(0,3));
  $('proximosCompleto').innerHTML=listaPartidas(futuras);
  $('resultadosCompletos').innerHTML=listaPartidas(concluidas);
  $('pendentesCompletos').innerHTML=listaPartidas(pendentes);
  $('listaEquipes').innerHTML=times.length?times.map(t=>{
    const jogadores=dados.jogadores.filter(j=>j.equipeId===t.id).sort((a,b)=>a.camisa-b.camisa);
    return `<article class="card-equipe"><div class="sigla-time">${escapar(t.nome.slice(0,2).toUpperCase())}</div><h3>${escapar(t.nome)}</h3><p>${escapar(t.cidade||'Cidade não informada')}</p><strong>Jogadores (${jogadores.length})</strong>${jogadores.length?`<ul>${jogadores.map(j=>`<li>${j.camisa} · ${escapar(j.nome)}</li>`).join('')}</ul>`:'<p>Nenhum jogador cadastrado.</p>'}</article>`;
  }).join(''):'<p class="vazio">Nenhuma equipe cadastrada.</p>';
}
function opcoesEquipes(selecionado) {
  return '<option value="">Selecione uma equipe</option>'+equipesAtuais().map(e=>`<option value="${e.id}" ${e.id===selecionado?'selected':''}>${escapar(e.nome)}</option>`).join('');
}
function atualizarSeletores() {
  $('campeonatoAtual').innerHTML=dados.campeonatos.length?dados.campeonatos.map(c=>`<option value="${c.id}">${escapar(c.nome)} (${c.temporada})</option>`).join(''):'<option value="">Nenhum campeonato</option>';
  $('campeonatoAtual').value=campeonatoAtual===null?'':String(campeonatoAtual);
  for (const id of ['equipeJogador','mandante','visitante']) {
    const selecionado=Number($(id).value);
    $(id).innerHTML=opcoesEquipes(selecionado);
  }
}
function listaAdmin(itens,tipo,resumo) {
  return '<div class="admin-lista">'+(itens.length?itens.map(item=>`<div class="admin-item"><div class="admin-item-info"><strong>${escapar(resumo(item)[0])}</strong><small>${escapar(resumo(item)[1])}</small></div><div class="admin-item-acoes"><button type="button" data-editar="${tipo}" data-id="${item.id}">Editar</button><button class="excluir" type="button" data-excluir="${tipo}" data-id="${item.id}">Excluir</button></div></div>`).join(''):'<p class="vazio">Nenhum registro.</p>')+'</div>';
}
function atualizarAdmin() {
  $('loginArea').classList.toggle('escondido',adminLogado);
  $('adminArea').classList.toggle('escondido',!adminLogado);
  $('primeiroCadastro').classList.toggle('escondido',!requerCadastro);
  $('loginExistente').classList.toggle('escondido',requerCadastro);
  if (!adminLogado) return;
  $('adminUsuarioAtual').textContent=usuarioAtual||'';
  $('adminCampeonatos').innerHTML=listaAdmin(dados.campeonatos,'Campeonato',c=>[c.nome,String(c.temporada)]);
  $('adminEquipes').innerHTML=listaAdmin(equipesAtuais(),'Equipe',e=>[e.nome,e.cidade||'Sem cidade']);
  const ids=new Set(equipesAtuais().map(e=>e.id));
  $('adminJogadores').innerHTML=listaAdmin(dados.jogadores.filter(j=>ids.has(j.equipeId)),'Jogador',j=>[j.nome,`${nomeEquipe(j.equipeId)} · Camisa ${j.camisa}`]);
  $('adminPartidas').innerHTML=listaAdmin(partidasAtuais().slice().sort((a,b)=>a.data.localeCompare(b.data)),'Partida',p=>[`${nomeEquipe(p.mandanteId)} × ${nomeEquipe(p.visitanteId)}`,`${dataFormatada(p.data)} · ${partidaFinalizada(p)?p.golsMandante+' × '+p.golsVisitante:'Sem resultado'}`]);
}
function atualizarTudo() {
  if (!dados.campeonatos.some(c=>c.id===campeonatoAtual)) campeonatoAtual=dados.campeonatos[0]?.id||null;
  atualizarSeletores(); atualizarPublico(); atualizarAdmin();
}
function irPara(pagina) {
  paginaAtual=pagina;
  document.querySelectorAll('.pagina').forEach(sec=>sec.classList.toggle('escondido',sec.id!=='pagina-'+pagina));
  document.querySelectorAll('.navegacao button').forEach(btn=>btn.classList.toggle('nav-ativo',btn.dataset.pagina===pagina));
  window.scrollTo({top:0,behavior:'smooth'});
}
function limparFormulario(tipo) {
  $('form'+tipo).reset();
  $(tipo.toLowerCase()+'Id').value='';
}
async function salvarRegistro(tipo,body,mensagem) {
  try {
    await requisicao('/api/records/'+tipo,{method:'POST',body});
    await buscarDados();
    mostrarAviso(mensagem);
    return true;
  } catch (erro) {mostrarAviso(erro.message,true);return false;}
}
$('formCampeonato').addEventListener('submit',async evento=>{
  evento.preventDefault();
  const id=Number($('campeonatoId').value)||undefined;
  const item={id,nome:$('nomeCampeonato').value.trim(),temporada:Number($('temporada').value)};
  if (await salvarRegistro('campeonatos',item,'Campeonato salvo.')) {
    if (!id) campeonatoAtual=Math.max(...dados.campeonatos.map(c=>c.id));
    limparFormulario('Campeonato'); atualizarTudo();
  }
});
$('formEquipe').addEventListener('submit',async evento=>{
  evento.preventDefault();
  if (!campeonatoAtual) return mostrarAviso('Cadastre um campeonato primeiro.',true);
  const id=Number($('equipeId').value)||undefined;
  const item={id,campeonatoId:campeonatoAtual,nome:$('nomeEquipe').value.trim(),cidade:$('cidadeEquipe').value.trim()};
  if (await salvarRegistro('equipes',item,'Equipe salva.')) {limparFormulario('Equipe');atualizarTudo();}
});
$('formJogador').addEventListener('submit',async evento=>{
  evento.preventDefault();
  const id=Number($('jogadorId').value)||undefined;
  const item={id,equipeId:Number($('equipeJogador').value),nome:$('nomeJogador').value.trim(),camisa:Number($('camisaJogador').value)};
  if (await salvarRegistro('jogadores',item,'Jogador salvo.')) {limparFormulario('Jogador');atualizarTudo();}
});
$('formPartida').addEventListener('submit',async evento=>{
  evento.preventDefault();
  const id=Number($('partidaId').value)||undefined;
  const casa=$('golsMandante').value.trim(),fora=$('golsVisitante').value.trim();
  if ((casa==='')!==(fora==='')) return mostrarAviso('Preencha os dois placares ou deixe os dois em branco.',true);
  const item={id,campeonatoId:campeonatoAtual,mandanteId:Number($('mandante').value),visitanteId:Number($('visitante').value),data:$('dataPartida').value,local:$('localPartida').value.trim(),golsMandante:casa===''?null:Number(casa),golsVisitante:fora===''?null:Number(fora)};
  if (await salvarRegistro('partidas',item,'Partida salva e classificação recalculada.')) {limparFormulario('Partida');atualizarTudo();}
});
const configuracaoEdicao={
  Campeonato:{lista:()=>dados.campeonatos,campos:{campeonatoId:'id',nomeCampeonato:'nome',temporada:'temporada'}},
  Equipe:{lista:()=>dados.equipes,campos:{equipeId:'id',nomeEquipe:'nome',cidadeEquipe:'cidade'}},
  Jogador:{lista:()=>dados.jogadores,campos:{jogadorId:'id',nomeJogador:'nome',equipeJogador:'equipeId',camisaJogador:'camisa'}},
  Partida:{lista:()=>dados.partidas,campos:{partidaId:'id',mandante:'mandanteId',visitante:'visitanteId',dataPartida:'data',localPartida:'local',golsMandante:'golsMandante',golsVisitante:'golsVisitante'}}
};
const tabelas={Campeonato:'campeonatos',Equipe:'equipes',Jogador:'jogadores',Partida:'partidas'};
function editar(tipo,id) {
  const config=configuracaoEdicao[tipo]; if (!config) return;
  const item=config.lista().find(i=>i.id===id);if (!item) return;
  for (const [elemento,campo] of Object.entries(config.campos)) $(elemento).value=item[campo]??'';
  $('form'+tipo).scrollIntoView({behavior:'smooth',block:'center'});
}
async function excluir(tipo,id) {
  if (!tabelas[tipo]) return;
  const alertas={Campeonato:'Também serão removidos equipes, jogadores e partidas deste campeonato.',Equipe:'Também serão removidos jogadores e partidas desta equipe.',Jogador:'',Partida:''};
  if (!confirm(`Deseja realmente excluir este registro? ${alertas[tipo]}`)) return;
  try {
    await requisicao('/api/records/'+tabelas[tipo]+'/'+id,{method:'DELETE'});
    limparFormulario(tipo);await buscarDados();mostrarAviso('Registro excluído.');
  } catch (erro) {mostrarAviso(erro.message,true);}
}
document.addEventListener('click',evento=>{
  const selecionar=evento.target.closest('[data-selecionar]');
  if (selecionar) {
    campeonatoAtual=Number(selecionar.dataset.selecionar);
    ['Campeonato','Equipe','Jogador','Partida'].forEach(limparFormulario);
    atualizarTudo();return;
  }
  const pagina=evento.target.closest('[data-pagina]');if (pagina) return irPara(pagina.dataset.pagina);
  const editarBotao=evento.target.closest('[data-editar]');if (editarBotao&&adminLogado) return editar(editarBotao.dataset.editar,Number(editarBotao.dataset.id));
  const excluirBotao=evento.target.closest('[data-excluir]');if (excluirBotao&&adminLogado) return excluir(excluirBotao.dataset.excluir,Number(excluirBotao.dataset.id));
  const cancelar=evento.target.closest('[data-form]');if (cancelar) limparFormulario(cancelar.dataset.form);
});
$('campeonatoAtual').addEventListener('change',evento=>{
  campeonatoAtual=Number(evento.target.value)||null;
  ['Campeonato','Equipe','Jogador','Partida'].forEach(limparFormulario);
  atualizarTudo();
});
$('formCadastroInicial').addEventListener('submit',async evento=>{
  evento.preventDefault();
  try {
    await requisicao('/api/setup',{method:'POST',body:{usuario:$('usuarioInicial').value.trim(),senha:$('senhaInicial').value}});
    $('formCadastroInicial').reset();await buscarDados();mostrarAviso('Conta de administrador criada com sucesso.');
  } catch (erro) {mostrarAviso(erro.message,true);}
});
$('formLogin').addEventListener('submit',async evento=>{
  evento.preventDefault();
  try {
    await requisicao('/api/login',{method:'POST',body:{usuario:$('usuario').value.trim(),senha:$('senha').value}});
    $('senha').value='';await buscarDados();mostrarAviso('Bem-vindo ao painel administrativo.');
  } catch (erro) {mostrarAviso(erro.message,true);}
});
$('formNovoAdmin').addEventListener('submit',async evento=>{
  evento.preventDefault();
  try {
    await requisicao('/api/admins',{method:'POST',body:{usuario:$('novoUsuario').value.trim(),senha:$('novaSenha').value}});
    $('formNovoAdmin').reset();mostrarAviso('Novo administrador cadastrado.');
  } catch (erro) {mostrarAviso(erro.message,true);}
});
$('sair').addEventListener('click',async()=>{
  try {await requisicao('/api/logout',{method:'POST',body:{}});await buscarDados();mostrarAviso('Sessão encerrada.');}
  catch (erro) {mostrarAviso(erro.message,true);}
});
$('baixarBackup').addEventListener('click',()=>{window.location.href='/api/export';});
$('exportarClassificacao').addEventListener('click',()=>{
  const tabela=calcularClassificacao();
  if (!tabela.length) return mostrarAviso('Cadastre uma equipe para exportar a classificação.',true);
  const escaparCSV=valor=>'"'+String(valor).replace(/"/g,'""')+'"';
  const linhas=[['Posição','Equipe','P','J','V','E','D','GP','GC','SG'],...tabela.map((t,i)=>[i+1,t.nome,t.P,t.J,t.V,t.E,t.D,t.GP,t.GC,t.SG])];
  const csv='\ufeff'+linhas.map(l=>l.map(escaparCSV).join(';')).join('\r\n');
  const endereco=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=endereco;link.download='ligafacil-classificacao.csv';link.click();
  setTimeout(()=>URL.revokeObjectURL(endereco),500);
});
buscarDados();
setInterval(()=>buscarDados(true),15_000);
