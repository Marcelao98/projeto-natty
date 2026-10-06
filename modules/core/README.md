# NAT-CORE

Núcleo de dados da Natty: jogadores, personagens e missões da Crossroads.
Desde 2026-10-05 os dados ficam num **SQLite local** (`data/natty.db`), não mais
no Google Sheets. A planilha antiga não foi apagada nem alterada e serve de backup
histórico.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `storage.py` | Acesso cru ao SQLite: schema, migrações, backups, leitura e escrita. Sem regra de negócio. |
| `service.py` | Regras: registrar/deletar/listar personagem, limite por jogador, nível no DiceCloud, espelho dos membros do servidor. Sem discord.py. |
| `cog.py` | Slash commands e listeners de membros. Só traduz Discord → service. |
| `Fluxo-Atual-Crossroads.md` | Como a comunidade funciona hoje (fluxo de ficha, missões, calculadora). |
| `test_storage.py`, `test_service.py`, `test_scripts.py` | Testes com um banco temporário (sem rede). |

## O banco

Caminho: `NATTY_DB_PATH` do `.env`, ou `data/natty.db` se vazio (relativo à raiz
do projeto). O arquivo tem Discord IDs, por isso **nunca vai pro git**
(`data/*.db`, `-wal`, `-shm`, `-journal` e `data/backups/` estão no `.gitignore`).

Tabelas (schema v3, versão guardada em `PRAGMA user_version`):

- **jogadores**: um por membro do servidor (sem bots). `discord_id` é a chave;
  `username` e `nome_exibicao` (apelido) são sempre os mais recentes; `nome` é o
  nome usado nos registros antigos da planilha; `ativo = 0` quando saiu do
  servidor. Ninguém é apagado, porque personagens e missões antigos continuam
  apontando pra ele.
- **personagens**: `nome_chave` (nome sem acento/maiúscula) é único no servidor;
  `jogador_discord_id` liga ao dono; `nivel_inicial` vem do DiceCloud no registro
  e `nivel_atual` do `sincronizar_niveis.py`; `historia` é o texto livre do
  registro (v3; os migrados da planilha ficam sem); `criado_em` é a data do
  registro, automática (nos migrados, o carimbo do Google Forms).
- **missoes**: dados da missão, condutor (`condutor_discord_id` + `condutor_nome`),
  XP e Gold. `dificuldade` só aceita Trivial, Fácil, Normal, Difícil ou Extrema.
- **missao_participantes**: quem jogou cada missão. Apagar a missão apaga os
  participantes; apagar o personagem mantém a linha com o nome (`personagem_id`
  vira NULL).

Toda escrita roda em `BEGIN IMMEDIATE ... COMMIT` (`storage.transacao()`), com
`foreign_keys` ligado e journal em WAL. O registro de personagem busca o nível no
DiceCloud (20-45s) **fora** da transação e confere limite e nome de novo dentro
dela, pra dois registros simultâneos não furarem a regra.

### Migrações de schema

`SCHEMA_VERSAO` + o dicionário `MIGRACOES` em `storage.py`. Ao subir, se o banco
estiver numa versão antiga, a Natty faz um backup (`schema-vN`) e aplica as
migrações em ordem. Pra mudar o schema: suba `SCHEMA_VERSAO`, acrescente os
comandos em `MIGRACOES[versão_antiga]` e atualize `SCHEMA` (usado em banco novo).

## Backups

Ficam em `data/backups/natty-AAAAMMDD-HHMMSS-<motivo>.db` (cópia consistente via
`Connection.backup()`), e só os **20 mais recentes** são mantidos. São feitos:

- `inicio`: toda vez que a Natty sobe;
- `deletar`: antes de apagar um personagem;
- `schema-vN`: antes de migrar o schema;
- `recriar` e `vincular`: pelos scripts abaixo, antes de gravar.

## Quando o banco não está confiável ("BANCO ILEGÍVEL")

Ao subir, `service.preparar_banco()` confere o arquivo (`quick_check`, versão do
schema). A Natty **se recusa a subir** se:

- o arquivo existe mas está corrompido, não é SQLite ou tem versão desconhecida;
- o arquivo sumiu mas existem backups (criar um banco vazio esconderia a perda).

Nesse caso a cog sai com **código 3**, e o `scripts/rodar_natty.bat` para o loop
em vez de reiniciar a cada 10s (reiniciar não conserta). O log
(`logs/natty.log`) mostra `BANCO ILEGÍVEL` e o motivo. Pra resolver:

```
python scripts/restaurar_banco.py                 # oferece o backup mais recente
python scripts/restaurar_banco.py --arquivo X.db  # ou um específico
```

O arquivo ruim não é apagado: vai pra `data/natty.ilegivel-<data>.db`. Depois,
reinicie a tarefa (`scripts/reiniciar_natty.ps1`).

## Registro: como a ficha é conferida

`/registrar-personagem` → `service.registrar_personagem`, nesta ordem (a
primeira falha para tudo e nada é gravado):

1. Nome e **história** preenchidos. A história é livre e do tamanho que o
   jogador quiser (uma linha já vale), até `MAX_HISTORIA` = 4000 caracteres
   (o máximo de um campo de formulário do Discord). Vazia ou maior →
   recusada sem ir ao DiceCloud.
2. Limite de **2 personagens** por jogador e nome único no servidor.
3. Link tem que ser `dicecloud.com/character/<ID>` (senão: "Só aceito ficha do DiceCloud").
4. O `<ID>` tem que ter o formato de ID do DiceCloud (Meteor): **17 caracteres**,
   sem `0`, `1`, `I`, `O`, `l` (`DICECLOUD_ID_RE`). Fora disso é link quebrado ou
   inventado: barrado **sem ir à internet**, com "Opa, essa ficha não existe".
5. `consultar_ficha_dicecloud` busca a ficha na API e devolve o motivo exato
   (mensagens em `ERROS_FICHA`):

| Motivo | Quando | Tenta de novo? |
|---|---|---|
| `inexistente` | ID com formato certo mas que não existe (API: `400 "No such document exists"`) | não |
| `privada` | API recusa por permissão (400/401/403 sem "No such document") | não |
| `nome` | a ficha existe mas o nome é outro; a mensagem mostra o nome da ficha | — |
| `sem_nivel` | a ficha não tem nível calculado nem classe | — |
| `indisponivel` | timeout, sem rede ou erro 5xx do DiceCloud | sim (2 tentativas) |

6. Grava (com a data de agora em `criado_em`), conferindo limite e nome de
   novo dentro da transação. A confirmação e o `/personagens` mostram a
   data ("desde 05/10/2026").

Detalhe que custou um bug: a API devolve o **corpo do erro compactado em gzip**
(porque a Natty pede gzip), então `_motivo_http` descompacta antes de procurar
"No such document". A resposta pra ficha privada de verdade ainda não foi vista
numa ficha real; se aparecer outra coisa, ajustar `_motivo_http`.

## Membros do servidor → tabela jogadores

A tabela `jogadores` espelha **todos** os membros do servidor (não só quem tem
personagem):

- ao subir e a cada 24h, a cog busca a lista completa (`fetch_members`) e chama
  `service.sincronizar_membros` (cria novos, atualiza username/apelido, marca
  `ativo = 0` em quem saiu). Uma lista vazia é recusada sem gravar nada, pra uma
  busca que falhou não marcar o servidor inteiro como "saiu";
- no dia a dia, `on_member_join`, `on_member_update`, `on_user_update` e
  `on_member_remove` mantêm a tabela em dia;
- quem usa um comando do core também é atualizado.

Requisitos: `intents.members = True` no `bot.py` **e** o **Server Members Intent**
ligado no Developer Portal (Bot → Privileged Gateway Intents). Se o bot estiver
em mais de um servidor, defina `GUILD_ID` no `.env`.

## Scripts (pasta `scripts/`)

| Script | Pra quê |
|---|---|
| `migrar_sheets_para_sqlite.py` | Migração única das abas Personagens e Missões da planilha. `--simular` só mostra; sem flag migra (aborta se o banco já tiver dados); `--recriar` faz backup, esvazia e migra de novo. Só **lê** a planilha. É o último uso do `gspread`/`credentials.json` no projeto. |
| `sincronizar_membros.py` / `.bat` | Mesma sincronização de membros que a Natty faz sozinha, pra rodar na mão (o `.bat` é duplo clique). |
| `vincular_jogadores.py` | Interativo: liga os personagens antigos (sem Discord ID) e os condutores das missões aos membros da tabela `jogadores`. Rode `sincronizar_membros` antes. `--forcar` refaz vínculos existentes. Pede confirmação e faz backup antes de gravar. |
| `importar_missoes_historicas.py` | Importa as missões dos posts do canal de missões (JSON em `data/importacao/`, ou `--arquivo`). **Dry-run por padrão**; só grava com `--aplicar`, e se recusa enquanto houver pendência. Missão existente: participantes intocados, só preenche campo vazio; campo com valor diferente é conflito e só muda com decisão explícita. Missão nova: insere com participantes resolvidos pela tabela `jogadores` (menção → username/apelido, parcial, ou dono do personagem com esse nome). Ambiguidades, data faltando e "possível mesma missão" vão num JSON de `--decisoes` (formato no topo do script). Idempotente, com backup antes. |
| `sincronizar_niveis.py` | Preenche `nivel_atual` de cada personagem a partir do DiceCloud (fichas públicas; outros links são pulados). |
| `restaurar_banco.py` | Recuperação, ver acima. |

## Registro de missão (`/registrar-missao`)

Substitui o Google Forms "Registro de Missões". Duas etapas:

1. **Comando**, com os campos curtos: `nome`, `data` (DD/MM/AAAA), `dificuldade`
   (lista com as 5), `xp`, `gold` e `participantes` (nomes dos personagens
   separados por vírgula, `;` ou quebra de linha). O cog chama
   `service.conferir_missao`, que checa tudo **sem gravar**: nome único (sem
   acento/maiúscula), data válida e não futura, dificuldade, XP/gold ≥ 0, e cada
   participante tem que ser um personagem registrado (se não for, a mensagem
   sugere o nome mais parecido, via `difflib`).
2. **Formulário** (`MissaoModal`): relato (obrigatório, até 4000), resultado,
   outras recompensas e observações (opcionais). No envio,
   `service.registrar_missao` confere tudo de novo dentro da transação e grava
   missão + participantes (com `personagem_id`).

- Condutor = quem rodou o comando (precisa do cargo **Viajante**).
  `condutor_nome` segue o padrão das antigas: o `nome` do jogador (ex:
  "Marcelo"), senão o apelido.
- **XP e gold são digitados** pelo condutor. O gold da guilda é "Gold Base do
  nível médio × multiplicador da dificuldade" (`Fluxo-Atual-Crossroads.md`),
  mas a tabela de **XP base** não está documentada e os valores históricos não
  fecham numa fórmula só; calcular sozinho fica pra quando ela existir.
- Ainda não existe `/deletar-missao` nem edição: correção é direto no banco
  (com backup).
- `/missoes` lista as missões (mais recentes primeiro) com data, dificuldade,
  condutor, XP, gold e participantes.

## Estado em 2026-10-05

Migração feita e vínculos completos: 47 jogadores, 14 personagens (todos ligados
a um Discord ID), **7 missões** (as 4 do Sheets completadas e 3 novas, vindas dos
posts do canal de missões via `importar_missoes_historicas.py`). Pendente: a
personagem Lucy (Ana) não está registrada e aparece só pelo nome em "Pra onde foi
o nosso lixo".

## Testes

```
python -m unittest discover -s modules/core -t .
```
