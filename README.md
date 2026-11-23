# LigaFácil 2.0 — gestão de campeonatos de futebol amador

Versão revisada do projeto acadêmico, com **interface HTML/CSS/JavaScript**, **API em Python puro** e **banco SQLite**. Os dados são compartilhados entre os dispositivos que acessam o **mesmo servidor**. Não requer bibliotecas Python adicionais nem `npm install`.

## Como executar no Windows

1. Instale **Python 3.10 ou superior** pelo site [python.org](https://www.python.org/downloads/) (ative **Add Python to PATH** na instalação).
2. Extraia todo o ZIP para uma pasta (não execute diretamente dentro do ZIP).
3. Clique em `iniciar-windows.bat`. Se necessário, abra um terminal na pasta e execute `py -3 server.py` ou `python server.py`.
4. Abra **http://localhost:8000** no navegador.
5. Entre em **Administração**. No primeiro acesso, **crie seu usuário e sua senha** (mínimo 10 caracteres). A aplicação não usa a antiga senha fixa `admin123`.
6. Cadastre campeonatos, equipes, jogadores e partidas e informe os resultados.

## Como executar no Linux ou macOS

1. Tenha Python 3.10 ou superior instalado.
2. Extraia o ZIP e abra o terminal dentro da pasta `LigaFacil`.
3. Execute `python3 server.py` (ou `./iniciar-linux.sh`).
4. Acesse **http://localhost:8000** no navegador.

Para encerrar: pressione `Ctrl+C` no terminal onde o servidor está em execução.

**Importante:** não abra mais o arquivo `index.html` com um clique duplo (`file://`). **Esta versão precisa ser acessada pelo servidor Python**, pois os formulários usam a API `/api/...`.

## Acesso por outros computadores e celulares

Conecte os aparelhos à **mesma rede local** e mantenha o computador/servidor ligado. Descubra o endereço IP local da máquina que roda Python (`ipconfig` no Windows ou `hostname -I` no Linux) e acesse `http://IP-DO-SERVIDOR:8000` em outros dispositivos. Caso não abra, libere a porta **8000/TCP** no firewall da rede local. As alterações estarão disponíveis a todos os visitantes, com atualização automática da página a cada **15 segundos** (não usa WebSockets).

O servidor escuta todas as interfaces de rede (`0.0.0.0`) para permitir acesso local. **Não exponha a porta 8000 diretamente à internet.** Para publicar, use proxy reverso com HTTPS, restrições de firewall, atualizações e backups. Este servidor, embora mais seguro que o protótipo, **não é uma configuração pronta para produção pública**.

## Funcionalidades e critérios de avaliação

| Requisito | Implementação |
|---|---|
| Página inicial com campeonatos | Cartões selecionáveis, estatísticas e resumo |
| Cadastro/login de administradores | Primeiro cadastro por configuração inicial; novas contas feitas por administrador autenticado; senha com hash scrypt e cookies HttpOnly |
| Cadastro de campeonatos | Criar, editar e excluir; evita nome duplicado por temporada |
| Cadastro de equipes | Criar, editar e excluir; **impede equipes com nomes duplicados no mesmo campeonato** (ignora espaços, maiúsculas e acentos) |
| Cadastro de jogadores | Vinculados à equipe; evita números de camisa repetidos dentro da equipe |
| Cadastro de partidas | Data, horário, local e confronto; equipes obrigatoriamente do mesmo campeonato |
| Registro/edição de resultados | Dois placares inteiros, inclusive `0 × 0`; podem ser alterados |
| Classificação automática | Recalculada no navegador a partir dos resultados oficiais do servidor |
| Estatísticas completas | Pontos, jogos, vitórias, empates, derrotas, gols pró/contra e saldo |
| Próximos jogos | Partidas sem placar com data futura |
| Histórico | Partidas com placar; jogos com data passada e sem placar aparecem em "Pendentes de resultado" |
| Painel administrativo | Operações protegidas por sessão e validação de dados na API |
| Visitantes sem login | Todas as páginas públicas consultam os mesmos dados compartilhados |

## Arquivos

- `index.html`: interface pública e de administração.
- `style.css`: aparência responsiva.
- `script.js`: interface, cálculos, formulários e chamadas à API.
- `server.py`: servidor HTTP, autenticação, regras de negócio e banco SQLite.
- `iniciar-windows.bat` / `iniciar-linux.sh`: atalhos de execução.
- `testes/teste_api.py`: testes automatizados da API e das regras principais.
- `data/ligafacil.sqlite3`: banco **criado automaticamente na primeira execução** (não acompanha o ZIP).

## Dados, exportação e backup

O sistema inicia com uma competição, quatro equipes, seis jogadores, dois resultados e duas partidas futuras **de demonstração**. Os exemplos são adicionados somente quando um banco novo é criado. Os jogos de demonstração são datados relativamente ao primeiro dia de execução.

No painel administrativo, clique em **Baixar backup JSON** para obter uma cópia dos cadastros, sem senhas. O arquivo JSON é útil para consulta/exportação, mas **não é restaurado automaticamente pela interface**.

**Para backup e restauração completos, incluindo contas:** desligue o servidor (`Ctrl+C`) e copie a pasta `data/` inteira. Para restaurar, desligue o servidor e substitua `data/` pela cópia. Fazer cópia com o servidor parado evita problemas com os arquivos de WAL do SQLite.

**Dados antigos:** o arquivo `localStorage` da versão anterior **não é migrado automaticamente** para o SQLite. Se você já tinha dados próprios no protótipo anterior, preserve uma cópia e faça uma migração específica. Nunca sobrescreva seus dados sem backup.

Para iniciar um ambiente novo **descartando todos os cadastros e administradores**, desligue o servidor e renomeie a pasta `data/` (faça backup antes). Na próxima execução, uma base nova de demonstração será criada.

## Regras da classificação

- Vitória: 3 pontos; empate: 1 ponto; derrota: 0 pontos.
- Desempate simplificado: pontos, vitórias, saldo de gols, gols pró e nome.
- Jogos sem dois placares registrados não contam para a classificação.
- A tabela é recalculada após qualquer alteração e fica visível para visitantes na próxima consulta (automática a cada 15 segundos).

## Segurança e limitações

- As senhas são armazenadas com `scrypt` e salt aleatório; cookies de sessão são `HttpOnly` e `SameSite=Strict`, com duração de até 12 horas. Escritas requerem token CSRF e validação na API.
- Apenas a primeira criação de conta é liberada sem login, **quando ainda não há administradores**. Realize esta etapa antes de compartilhar o endereço do servidor.
- O Python HTTPServer da biblioteca padrão é adequado para **demonstrações, testes e redes locais confiáveis**, mas não substitui uma implantação web profissional endurecida. Em internet pública, configure HTTPS e um servidor/proxy adequado, controle de acesso e monitoramento.
- Não há recuperação de senha por email, auditoria detalhada, tabela de fases eliminatórias nem permissões diferentes por administrador.
- "Tempo real" é implementado por **consulta automática a cada 15 segundos**, sem comunicação instantânea/WebSocket.
- Um campeonato pode ter confrontos de ida e volta em dias diferentes, mas não dois jogos entre o mesmo par de times no mesmo horário.

## Executar os testes

Com o servidor parado, na pasta principal:

```bash
python3 -m unittest discover -s testes -v
```

Os testes utilizam um banco temporário e um servidor local em uma porta dinâmica. Não modificam seus cadastros.
