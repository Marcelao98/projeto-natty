# Natty

Bot de Discord para a comunidade de D&D **The Crossroads**. Este repositório
cobre os módulos ativos da Natty:

- **NAT-CORE** (`modules/core/`) — núcleo de dados (SQLite local em
  `data/natty.db`: jogadores, personagens, missões; cálculo de XP/Gold ainda
  por fazer). O Google Sheets foi aposentado em 2026-10-05.
- **Dice** (`modules/dice/`) — rolagem de dados e moedas.
- **Bardo** (`modules/bardo/`) — música no canal de voz (YouTube + dataset).
- **Socorro** (`modules/socorro/`) — a Natty explica o que cada módulo faz.
- **Echo** (`modules/echo/`) — escuta a call: senha "NAT20, por favor" e
  comandos falados (rolagem, pedido de música, controles da música, sair da
  call) e a Escriba (ata da sessão: grava e transcreve no fim). Vosk offline
  com vocabulário fechado; Whisper local pro nome da música; faster-whisper
  pra ata.
- **Painel** (`modules/painel/`) — painel web (aiohttp, localhost) pra ver e
  controlar o Bardo. É uma *superfície*, não uma capacidade: fala com os
  módulos só por `bot.controles["<módulo>"]`, nunca importando.
- **Sieve** (`modules/sieve/`) — análise de repositórios de terceiros (só
  documentação/skill, não é Cog).

Não cobre LLM nem integração com Avrae/Foundry/Kenku — módulos futuros, fora
de escopo aqui.

## Princípio de arquitetura

Cada módulo da Natty é uma capacidade isolada, carregada como um Cog do
discord.py. Dentro de cada módulo, duas camadas obrigatórias:

- `service.py` — lógica de negócio pura, sem nenhuma dependência de discord.py.
  Funções que qualquer outro módulo (inclusive um futuro módulo de LLM) possa
  chamar diretamente, sem precisar simular um comando de Discord.
- `cog.py` — só traduz comando de Discord → chamada de service.py, e formata
  a resposta de volta. Nenhuma lógica de negócio aqui.

Isso existe pra permitir que, quando o módulo de LLM existir, ele decida a
intenção do usuário e chame a função de serviço certa diretamente — nunca
fingindo ser um comando de Discord nem tocando no banco fora do caminho
controlado que o módulo expõe.

## Módulos não importam uns aos outros

Nenhum módulo importa outro (só testes podem, pra validar ponta a ponta).
Quando um precisa acionar outro, ele posta texto no canal e o `on_message`
do outro reage como se alguém tivesse digitado.

O caso concreto é a voz: o Echo converte o que foi falado e posta
`🎙️ rolo 1d20+5` (Dice) ou `🎙️ natty toca Garçom` (Bardo). Como Dice e Bardo
ignoram mensagens de bot, os dois aceitam **só** mensagem da própria Natty
que comece com 🎙 (`MARCADOR_VOZ` no cog de cada um). Regras dessa convenção:

- Respostas de módulo nunca começam com 🎙 (senão a Natty reage a si mesma).
- O texto com 🎙 leva só o pedido, sem o nome de quem falou: o Dice lê a
  mensagem inteira, e um apelido "Dis" viraria desvantagem.
- Mensagens do Echo que não são pedido usam outro emoji (👂, 🎵).

Detalhes em `modules/echo/README.md` ("Rolagem falada", "Pedido de música").

## Estrutura de pastas

```
Natty/
├── bot.py                    # só inicializa o client e carrega os módulos ativos
├── requirements.txt
├── .env.example
├── README.md
├── CHANGELOG.md
├── data/                     # natty.db + backups/ (NÃO vão pro git) e tracklists
├── scripts/                  # scripts manuais e de operação (rodar_natty.bat,
│                             # reiniciar_natty.ps1, sincronizar_niveis.py, bardo_*,
│                             # restaurar_banco.py, sincronizar_membros, vincular_jogadores)
└── modules/
    ├── core/
    │   ├── cog.py             # comandos Discord + espelho dos membros do servidor
    │   ├── storage.py         # acesso cru ao SQLite (schema, migrações, backups)
    │   ├── service.py         # lógica de negócio: registrar, listar, calcular
    │   ├── test_*.py
    │   ├── README.md          # banco, backups, recuperação e scripts
    │   └── Fluxo-Atual-Crossroads.md
    ├── dice/                  # rolagem de dados (/rolar + listener do chat)
    │   ├── cog.py, service.py, detector.py, format.py, coins.py,
    │   │   conditional_rerolls.py, test_*.py
    │   └── README.md          # regras e limites do módulo
    ├── bardo/                 # música (YouTube, fila, dataset de trilhas)
    │   ├── cog.py, motor.py (player), service.py, storage.py (bardo.db),
    │   │   youtube.py, eventos.py, test_*.py
    │   ├── dataset/           # musicas.json + vocabulario.json (versionados)
    │   └── README.md
    ├── socorro/               # ajuda: "natty socorro [módulo]" e /socorro
    ├── echo/                  # voz: senha, rolagem e música faladas
    │   ├── cog.py             # entra/sai da call, estados por pessoa, vigia
    │   ├── service.py         # Vosk (senha, rolagem), Whisper (música), normalização
    │   ├── dave.py            # decifra o DAVE do áudio recebido (remendo temporário)
    │   ├── test_*.py
    │   ├── assets/            # modelo do Vosk, baixado à mão — NÃO vai pro git
    │   └── README.md
    ├── painel/                # painel web (aiohttp + static/), fala via bot.controles
    └── sieve/                 # skill de análise de repositórios (Findings/)
```

**Regra de documentação:** conhecimento de domínio específico de um módulo
(regras de negócio, fluxos, contexto narrativo) vive dentro da pasta daquele
módulo — nunca na raiz. A raiz só guarda o que é transversal (README,
CHANGELOG, este CLAUDE.md).

## Por que não microsserviços

Um processo só, um bot só, organizado internamente em módulos independentes
("monólito modular"). Sem complexidade operacional de múltiplos serviços —
decisão a ser revisitada só se algum módulo específico precisar de
isolamento que o processo principal não aguente.

## Escopo do NAT-CORE

Cobre: banco SQLite (`storage.py`, único lugar que fala SQL), espelho dos
membros do servidor na tabela `jogadores`, registro e consulta de personagens,
registro e consulta de missões, cálculo de XP/Gold. Detalhes (schema, backups,
"BANCO ILEGÍVEL", scripts) em `modules/core/README.md`.

## Testes

Cada módulo tem os seus, sem rede nem modelo de verdade (dublês):

```
python -m unittest discover -s modules/<modulo> -t .
```

Os do Echo importam Dice e Bardo de propósito, pra provar que o texto que
ele posta é entendido pelos módulos de verdade.

## Segurança

`.env` e `credentials.json` NUNCA são commitados (já no `.gitignore`). Sempre
rodar `git status` antes de qualquer commit pra confirmar que nenhum dos dois
está staged. O modelo do Vosk em `modules/echo/assets/` também fica fora do
git (pesado, baixado à mão), e as gravações e atas da Escriba em
`logs/sessoes/` também (é a voz e a conversa de todo mundo da mesa). O banco
do NAT-CORE (`data/*.db`, `-wal`, `-shm`) e `data/backups/` também ficam fora
(têm Discord IDs).

## Repositório público: nada de dados reais

Este repositório é público. Em testes, exemplos, READMEs e no CHANGELOG, use
**nomes fictícios** (Aldric, Tavi, Vexil, Tomas Vale...) e nunca nomes reais,
usernames do Discord, IDs ou apelidos de jogadores da comunidade. No
CHANGELOG, fale de "um jogador" em vez de citar a pessoa. Nunca commite `.env`,
`credentials.json`, o banco (`data/*.db`), gravações ou atas da Escriba.
