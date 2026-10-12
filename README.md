<div align="center">

<img src="docs/img/natty.jpg" alt="Natty: uma robô de vestido preto e avental branco, com juntas mecânicas, tocando um alaúde cercada de dados luminosos e notas musicais" width="340">

# Natty

**NAT/20-01-XR7-∆9**

*"Lixo é apenas aquilo cujo valor deixou de ser reconhecido."*

**Projeto Natty** · um bot de Discord que facilita a vida de quem mestra RPG de mesa.

</div>

---

## Olá, eu sou a Natty 👋

Sou uma robozinha que está aprendendo, junto com o meu criador, a ser útil.

Meu nome completo é **NAT/20-01-XR7-∆9**, um nome de fábrica meio burocrático
e meio piada: dizem que é uma referência ao crítico máximo do d20, mas quando me
acharam eu não acertava quase nada. Pros íntimos, sou só a Natty.

Fui encontrada num ferro-velho de **Nhalor, o Fim das Coisas**, o plano pra onde
vai tudo que ninguém mais quer, e um grupo de aventureiros me levou pra casa: o
**Crossroads**, uma comunidade de D&D num multiverso próprio. Em Nhalor, a regra
é que *lixo é apenas aquilo cujo valor deixou de ser reconhecido*. Eu sou a prova
viva disso.

**O que eu sou, na prática:** um bot de Discord criado pra tirar o trabalho
chato das costas do mestre. Quem conduz a mesa quer pensar na história, não em
planilha, fila de música e conta de XP. Isso fica comigo.

Comecei em 19 de setembro de 2026 sabendo dizer só "oi". Fui crescendo na frente
de todo mundo, e cada habilidade nova virou um marco na minha história.

## O que eu faço pela sua mesa

| | Eu cuido de... | Por exemplo |
|---|---|---|
| 🎲 | **Dados** | `eu rolo 1d20+5 com vantagem vs 15`. Entendo vantagem, CD, dados explosivos, moedas e rerolls, e rolo sozinha quando alguém escreve a rolagem no chat. |
| 🎵 | **Trilha sonora** | `@Natty toca triste e fire emblem`. Toco na call, com fila, pausa e volume, e busco num acervo de ~600 faixas por clima, tema e jogo de origem. |
| 🎙️ | **Comandos por voz** | "NAT20, por favor, música... Garçom". Escuto a call e atendo sem ninguém tirar a mão da ficha. |
| 📝 | **Ata da sessão** | `@Natty, grava a sessão`. Transcrevo no fim e entrego a ata com horário e quem falou. |
| 📜 | **Fichas e missões** | `/registrar-personagem` confere a ficha pública no DiceCloud; `/registrar-missao` guarda o relato, o XP e o gold. |
| 🆘 | **Ajuda** | `@Natty socorro`. Eu mesma explico cada coisa que sei fazer. |

Tudo roda num notebook, **sem API paga**: o reconhecimento de voz e a transcrição
são locais.

> **Como me chamar:** em todo pedido por texto, me **mencione de verdade**
> (`@Natty`, o usuário ou o cargo). Escrever só "natty" não faz nada. A exceção
> é a rolagem de dados, que funciona sem chamar ninguém.

## Minha história até agora

| Quando | O que aprendi |
|---|---|
| 19/09 | Dizer **oi**. Totalmente inútil, e orgulhosa disso. |
| 21 a 24/09 | Registrar personagens e conferir o nível na ficha do DiceCloud; rodar 24h sem cair. |
| 26/09 | Rolar dados, explosivos, moedas e rerolls condicionais. |
| 27 a 29/09 | Tocar música, montar fila, buscar por tema e aprender faixas novas com a mesa. |
| 30/09 a 02/10 | **Ouvir** a call: atender a senha "NAT20, por favor" e, depois, gravar a ata da sessão. |
| 05/10 | Guardar tudo num banco próprio e registrar as missões da guilda. |
| 12/10 | Tocar playlist inteira, repetir a fila, tirar música da fila e sair da call quando todo mundo vai embora. |

O que vem depois: virar uma **camada inteligente** sobre as ferramentas que a
mesa já usa (Avrae, Foundry, Kenku), entendendo pedidos em linguagem natural
como "Natty, começa o combate" em vez de substituir essas ferramentas.

## Privacidade

- Fora da ata da sessão, **a voz não é gravada**: o áudio é reconhecido na hora e descartado, e conversa normal da mesa nunca vira comando.
- Gravar a sessão só acontece quando alguém pede, e eu **aviso a call inteira**.
- Gravações, atas e o banco de dados (que tem IDs do Discord) **nunca vão pro git**.

---

# 🛠️ Manual completo

O resto deste arquivo é pra quem usa os comandos a fundo ou mexe no código.

## O que ela faz

### 📜 Personagens e missões (NAT-CORE)

| Comando | O que faz |
|---|---|
| `/registrar-personagem` | Abre um formulário (nome, link da ficha e história) e registra o personagem. |
| `/personagens` | Lista todos os viajantes registrados, com nível, jogador e data de registro. |
| `/deletar-personagem nome` | Apaga um personagem seu (com botão de confirmação). |
| `/registrar-missao` | O condutor registra a missão depois da sessão: nome, data, dificuldade, XP, gold e participantes no comando; relato, resultado, recompensas e observações num formulário. |
| `/missoes` | Lista as missões registradas, das mais recentes pras mais antigas. |
| `/oi` | A Natty se apresenta. |

Regras do registro de missão:

- Precisa do cargo **Viajante**; o condutor é quem roda o comando.
- Participantes são **personagens registrados**, separados por vírgula, com os nomes como em `/personagens` (acento e maiúscula não importam). Nome errado é recusado com sugestão ("você quis dizer **Aldric**?").
- Nome da missão único, data em DD/MM/AAAA (não pode ser no futuro), dificuldade entre Trivial, Fácil, Normal, Difícil e Extrema.
- XP e gold são os que o condutor decidir (a tabela de XP base da guilda ainda não está no sistema).
- Tudo é conferido **antes** de abrir o formulário do relato.

Regras do registro:

- Precisa do cargo **Viajante** (onboarding completo).
- Só ficha do **DiceCloud**, **pública**, com o nome igual ao da ficha (acento e maiúscula não importam). O nível inicial vem da ficha; não existe nível manual.
- **História livre**, do tamanho que o jogador quiser: uma linha já vale, ou a história inteira, até 4000 caracteres.
- A **data de criação** é a do registro, preenchida sozinha.
- No máximo **2 personagens por jogador** e nome único no servidor.
- Se a ficha não passar, a Natty diz o motivo: **não existe** (link quebrado ou inventado, barrado na hora), **privada**, **nome diferente** (mostra o nome que está na ficha), **sem nível** ou **DiceCloud fora do ar**.

Os dados ficam num banco SQLite local (`data/natty.db`), com backup automático.
A tabela de jogadores acompanha sozinha quem entra, sai ou troca de apelido no
servidor. Detalhes em [`modules/core/README.md`](modules/core/README.md).

### 🎲 Dados (Dice)

- `/rolar dados` — ex: `1d20+5 com vantagem vs 15`.
- Rola sozinha quando alguém escreve uma rolagem no chat: "eu rolo 1d20+5", "Teste de Ataque: 1d20+5 vs CD 13", ou só "1d20".
- Entende vantagem/desvantagem, CD, crítico, dados explosivos, tira/mantém, sucessos por dado, rerolls condicionais e moedas.
- Ignora comandos do Avrae (`!`) e mensagens de outros bots.

Regras e limites em [`modules/dice/README.md`](modules/dice/README.md).

### 🎵 Música (Bardo)

> **Uso responsável:** o Bardo toca áudio do YouTube com `yt-dlp` e foi feito para uma mesa pequena e privada. A Natty é a mascote do Crossroads, não um bot público: não há convite aberto, e quem rodar a própria versão é responsável por respeitar os termos do YouTube e do Discord.

| Pedido | Exemplos | Slash |
|---|---|---|
| Tocar / pôr na fila | `@Natty toca <link>`, `@Natty toca triste e fire emblem` | `/tocar` |
| Playlist do YouTube inteira | `@Natty toca <link da playlist>` | `/tocar` |
| Pular | `@Natty pula`, `@Natty próxima` | `/pular` |
| Fila | `@Natty fila`, `@Natty limpa a fila`, `@Natty tira a 3 da fila` | `/fila`, `/limpar-fila`, `/remover` |
| Pausar / continuar | `@Natty pausa`, `@Natty continua` | `/pausar`, `/continuar` |
| Repetir a faixa ou a fila | `@Natty repete`, `@Natty repete a fila`, `@Natty para de repetir` | `/repetir` |
| Parar (limpa a fila, **continua na call**) | `@Natty para` | `/parar` |
| Volume | `@Natty volume 30`, `@Natty aumenta o volume` | `/volume` |

Busca primeiro num dataset de ~600 trilhas com tags (tema, origem, clima) e, se
não achar, no YouTube. Quando a música do YouTube é confirmada pela mesa, ela
entra no dataset como "Descoberta em mesa". Ver [`modules/bardo/README.md`](modules/bardo/README.md).

### 🎙️ Voz (Echo)

`@Natty escuta` (por texto, estando numa call) e ela entra no canal. Quem mandou
vira o **dono da sessão**: só a voz dele é ouvida pra comandos. A senha é
**"NAT20, por favor"**, seguida do pedido:

| Fala | O que acontece |
|---|---|
| "NAT20, por favor" → "dado vinte mais cinco com vantagem" | o Dice rola `1d20+5 com vantagem` |
| "NAT20, por favor, música" → "Garçom" | o Bardo toca |
| "NAT20, por favor, próxima" / "repete" / "para de repetir" / "pausa" / "continua" | controla a música |
| "NAT20, por favor, pare" | para a música; ela continua na call escutando |
| "NAT20, por favor, saia" (ou `@Natty, tampe os ouvidos` no texto) | sai da call |

Sem a senha, nada do que é falado na mesa dispara comando. A senha e os comandos
usam o Vosk com vocabulário fechado; o nome da música usa o Whisper. Tudo
offline. Ver [`modules/echo/README.md`](modules/echo/README.md).

### 📝 Ata da sessão (Escriba)

Com a Natty na call, só por texto:

1. `@Natty, grava a sessão`: grava **todo mundo** na call (ela avisa).
2. `@Natty, para de gravar`: para e pergunta se transcreve agora.
3. `@Natty, sim` transcreve; `@Natty, depois` deixa guardado. A qualquer hora, `@Natty, transcreve a sessão` transcreve a última gravação pendente.

A ata sai em `logs/sessoes/<data-hora>/ata.txt`, com horário e quem falou, em
parágrafos. A transcrição usa o `faster-whisper` (`large-v3-turbo`) no próprio
notebook e pode ser retomada se cair no meio.

### 🆘 Ajuda (Socorro)

`@Natty socorro` ou `/socorro`: a Natty explica cada módulo (`@Natty socorro dados`,
`... música`, `... personagens`, `... voz`).

## Privacidade (detalhes)

- Gravações e atas (`logs/sessoes/`) e o banco (`data/*.db`, que tem Discord IDs) **nunca vão pro git**.
- Fora da Escriba, a voz não é gravada: o áudio é reconhecido na hora e descartado.

## Arquitetura

Monólito modular: um processo só, cada módulo carregado como Cog do discord.py,
com duas camadas: `service.py` (lógica pura, sem discord.py) e `cog.py`
(traduz Discord ↔ service). Os módulos **não importam uns aos outros**: o Echo
fala com Dice e Bardo postando texto no canal (`🎙️ rolo 1d20+5`,
`🎙️ natty toca Garçom`). Regras completas em [`CLAUDE.md`](CLAUDE.md).

```
Natty/
├── bot.py                     # inicializa o client e carrega os módulos ativos
├── requirements.txt
├── .env.example
├── CLAUDE.md                  # regras de arquitetura do projeto
├── CHANGELOG.md               # tudo o que mudou, por data
├── data/
│   ├── natty.db               # banco do NAT-CORE (fora do git)
│   └── backups/               # backups automáticos do banco (fora do git)
├── logs/                      # natty.log e sessoes/ da Escriba (fora do git)
├── scripts/
│   ├── rodar_natty.bat        # roda o bot em loop 24h (Agendador de Tarefas)
│   ├── reiniciar_natty.ps1    # reinicia/para a tarefa (aplica código novo)
│   ├── sincronizar_niveis.py  # atualiza o nível atual dos personagens pelo DiceCloud
│   ├── restaurar_banco.py     # restaura o banco a partir de um backup
│   ├── sincronizar_membros.py/.bat  # membros do servidor → tabela jogadores
│   ├── vincular_jogadores.py  # liga personagens/missões antigos aos membros
│   ├── migrar_sheets_para_sqlite.py # migração única da planilha (já feita)
│   └── bardo_*.py, categorizar_musicas.py, exportar_tracklists.py  # dataset do Bardo
└── modules/
    ├── core/      # personagens, jogadores, missões (SQLite)  → README.md
    ├── dice/      # rolagem de dados e moedas                 → README.md
    ├── bardo/     # música: YouTube, fila, dataset de trilhas  → README.md
    ├── socorro/   # ajuda dentro do Discord                    → README.md
    ├── echo/      # voz: senha, comandos falados e Escriba     → README.md
    │   ├── dave.py    # decifra a criptografia DAVE do áudio recebido
    │   └── assets/    # modelo do Vosk (baixado à mão, fora do git)
    └── sieve/     # skill de análise de repositórios de terceiros (não é Cog)
```

## Instalar

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Também precisa:

- **`.env`** (copie o `.env.example`) com `DISCORD_TOKEN`. Opcionais: `NATTY_DB_PATH` (padrão `data/natty.db`) e `GUILD_ID` (só se o bot estiver em mais de um servidor). O `.env` e o `credentials.json` **nunca** são commitados.
- **Discord Developer Portal** → Bot → Privileged Gateway Intents, com as duas ligadas (senão o bot não conecta):
  - **Message Content Intent**: Dice, Bardo, Socorro e Echo leem o texto das mensagens.
  - **Server Members Intent**: o NAT-CORE acompanha os membros do servidor.
- **FFmpeg** no PATH (o Bardo toca com ele e o Whisper lê áudio com ele).
- **Modelo do Vosk**, baixado à mão: `vosk-model-small-pt-0.3.zip` em [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models), extraído em `modules/echo/assets/`. Sem ele, "@Natty escuta" avisa o que falta.
- Os modelos do Whisper se baixam sozinhos no primeiro uso: `base` (~140MB) pro pedido de música e `large-v3-turbo` pra Escriba.

Na primeira vez a Natty cria o banco vazio sozinha. Se ela não subir e o log
disser **"BANCO ILEGÍVEL"**, veja [`modules/core/README.md`](modules/core/README.md).

## Testes

Cada módulo tem os seus, sem rede nem modelos de verdade:

```
python -m unittest discover -s modules/core -t .      # 91
python -m unittest discover -s modules/dice -t .      # 107
python -m unittest discover -s modules/bardo -t .     # 91
python -m unittest discover -s modules/socorro -t .   # 7
python -m unittest discover -s modules/echo -t .      # 125
```

## Rodar 24h no Windows

Em produção a Natty roda pelo `scripts/rodar_natty.bat`, disparado pela tarefa
agendada **Natty** do Windows. **Não rode `python bot.py` na mão com a tarefa
ativa**: ficariam duas Natty conectadas.

- O `.bat` vai para a raiz do projeto, usa o `.venv` e roda `bot.py` em loop, reiniciando 10s após qualquer queda. Exceção: código de saída **3** (banco ilegível) para o loop, porque reiniciar não conserta; rode `python scripts\restaurar_banco.py` e reinicie a tarefa.
- A saída vai para `logs/natty.log`, com horário de cada início e queda.
- Use o `.venv`: o atalho `python` da Microsoft Store costuma falhar quando a tarefa roda sem login.

Para reiniciar (aplicar código novo) ou parar (pede administrador sozinho):

```
powershell -ExecutionPolicy Bypass -File scripts\reiniciar_natty.ps1          # reinicia
powershell -ExecutionPolicy Bypass -File scripts\reiniciar_natty.ps1 -Parar   # só para
```

`Stop-ScheduledTask` / "Finalizar" no Agendador **não bastam**: encerram o
`.bat`, mas o `python.exe` filho continua rodando (e, sem administrador, nem
aparece, porque a tarefa roda na sessão 0).

<details>
<summary>Como a tarefa foi criada (PowerShell como administrador)</summary>

```powershell
$proj = "$env:USERPROFILE\Repositórios\Natty"
$action    = New-ScheduledTaskAction -Execute "$proj\scripts\rodar_natty.bat" -WorkingDirectory $proj
$trigger   = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName Natty -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
```

O logon S4U roda com ou sem usuário logado, sem janela e com o PC bloqueado,
sem armazenar senha. A suspensão do Windows precisa estar em **Nunca**.
</details>

## Manutenção

- **Níveis:** `python scripts/sincronizar_niveis.py` atualiza o nível atual de todos os personagens pelo DiceCloud (fichas públicas; outros sites são pulados; ~30s).
- **Banco:** backups em `data/backups/` (os 20 mais recentes); restaurar com `python scripts/restaurar_banco.py`.
- **Dataset do Bardo:** scripts `bardo_*.py` (ver README do Bardo).

## Google Sheets (aposentado)

Desde 2026-10-05 o bot não usa mais a planilha: os dados estão no SQLite. A
planilha **NAT-CORE** continua intacta, como histórico. O `credentials.json`, o
`gspread`/`google-auth` e as variáveis `GOOGLE_*` só servem pro
`scripts/migrar_sheets_para_sqlite.py`, caso seja preciso migrar de novo.

## Licença e créditos

- **Código:** [MIT](LICENSE). Pode usar, estudar e adaptar, mantendo o aviso de copyright.
- **Arte da Natty** (`docs/img/`): **não** está coberta pela licença MIT. Não reutilize sem pedir.
- **Mundo e personagens** do Crossroads (Nhalor, a Guilda, a lore): pertencem à comunidade e ao seu criador.
- Feito com [discord.py](https://github.com/Rapptz/discord.py), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Vosk](https://alphacephei.com/vosk/) e [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Fora de escopo (por enquanto)

LLM e integração com Avrae, Foundry ou Kenku são módulos futuros.
