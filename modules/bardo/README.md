# Módulo Bardo — música do YouTube, por link ou por busca

**Status:** ✅ Em produção desde 2026-09-27 · tocar, fila, pausar, continuar, parar e volume.
Playlist do YouTube, repetir a fila, remover da fila, `/repetir`, sair da call vazia e erros com motivo: 12/10/2026 (testado com dublês; falta validar ao vivo).
Busca no dataset (596 faixas) e busca livre no YouTube com aprendizado em mesa: ✅ em uso real —
17 faixas já entraram no dataset como "Descoberta em mesa". Pedido falado na call (via módulo Echo):
✅ validado em 01/10/2026 ("Garçom", "Ela Partiu").

> **Uso responsável:** este módulo toca áudio do YouTube com `yt-dlp` e foi feito para uma mesa pequena e privada, não para um bot público. Quem rodar a própria versão é responsável por respeitar os termos do YouTube e do Discord.

## O que faz, hoje

A Natty reconhece pedidos de música em linguagem natural — igual ao
módulo Dice reconhece "1d20 com vantagem" em vez de exigir um comando
formal — e toca no canal de voz de quem pediu, a partir de um link do
YouTube ou de uma busca por tema/origem no dataset local.

O pedido precisa **mencionar a Natty de verdade**: o usuário @Natty ou o
cargo automático @Natty, que o Discord oferece com o mesmo nome. Só
escrever "natty" no texto não basta (desde 02/10/2026) — evita a Natty
reagir a conversa da mesa que cita o nome dela. A única exceção é o
pedido falado na call: o Echo posta o texto com o marcador 🎙 e o Bardo
aceita mensagens da própria Natty com esse marcador como se fossem menção.

| Ação | Exemplos | Slash command |
|------|----------|---------------|
| Tocar (ou pôr na fila) | `@Natty toca <link>`, `@Natty bota <link>`, `@Natty adiciona <link>` | `/tocar pedido:<link>` |
| Pôr uma playlist inteira na fila | `@Natty toca https://www.youtube.com/playlist?list=...` | `/tocar pedido:<link da playlist>` |
| Buscar no dataset | `@Natty toca triste e fire emblem`, `@Natty toca boss fight sem elden ring` | `/tocar pedido:<busca>` |
| Buscar no YouTube (quando o dataset não tem) | `@Natty toca ragnar the red skyrim` | `/tocar pedido:<busca>` |
| Pular | `@Natty pula`, `@Natty próxima`, `@Natty skip` | `/pular` |
| Ver a fila | `@Natty fila`, `@Natty mostra a playlist` | `/fila` |
| Limpar a fila | `@Natty limpa a fila`, `@Natty esvazia a fila` | `/limpar-fila` |
| Tirar uma da fila | `@Natty tira a 3 da fila`, `@Natty remove 2` (a posição é a de `@Natty fila`) | `/remover posicao:3` |
| Pausar | `@Natty pausa` | `/pausar` |
| Continuar | `@Natty continua`, `@Natty volta a tocar`, `@Natty despausa` | `/continuar` |
| Parar (para a música e limpa a fila; **continua no canal**) | `@Natty para`, `@Natty chega`, `@Natty sai` | `/parar` |
| Repetir a faixa atual (liga/desliga) | `@Natty repete`, `@Natty loop`; desligar: `@Natty repete` de novo, `@Natty para de repetir`, `@Natty repete não` | `/repetir` (ou `modo: a música atual`) |
| Repetir a fila inteira (liga/desliga) | `@Natty repete a fila`, `@Natty loop da playlist`, `@Natty repete tudo` | `/repetir modo: a fila inteira` |
| Desligar qualquer repetição | `@Natty para de repetir` | `/repetir modo: desligar` |
| Volume | `@Natty volume 30`, `@Natty aumenta o volume`, `@Natty abaixa` | `/volume nivel:30` |
| Ver volume | `@Natty qual o volume?` | `/volume` |

- Tocar com música já tocando põe a nova no fim da fila. Quando uma música
  acaba, a próxima toca sozinha e a Natty avisa no canal do último pedido.
- A fila é por servidor, só em memória (some se a Natty reiniciar) e aceita
  até 50 músicas (`MAX_FILA`). A fila guarda o link, e a URL do áudio é
  resolvida de novo na hora de tocar, porque a do YouTube expira.
- Volume vai de 0 a 100%, começa em 50% e "aumenta"/"abaixa" mexe 20%.
  Vale por servidor e zera quando a Natty reinicia.
- Os slash commands não dependem de menção nem da Message Content Intent.
- Título com cara de comando funciona: quando o verbo de tocar vem antes
  de tudo, o resto é busca — `@Natty toca Volta pra Casa`, `@Natty toca
  Próxima Parada`. Comando continua comando: `@Natty volta a tocar`
  (continuar), `@Natty toca a próxima` (pular), `@Natty coloca o volume em 30`.
- `@Natty adiciona na fila Garçom` busca "Garçom" (o "na fila" sai da busca).

## Outras fontes (desde 12/10/2026)

- **Qualquer link que o yt-dlp entende**: SoundCloud, Bandcamp, Vimeo, link
  direto de .mp3... `@Natty toca https://soundcloud.com/...`. Set do
  SoundCloud e álbum do Bandcamp entram como playlist. Site que o yt-dlp
  não conhece: "não sei tocar desse site" (`LinkNaoSuportado`).
- **Anexo do Discord**: `@Natty toca` com um arquivo de áudio anexado toca o anexo.
- **Pasta local**: arquivos de áudio em `data/musicas/` (ou
  `BARDO_PASTA_LOCAL` no `.env`; fora do git) entram na busca **depois do
  dataset e antes do YouTube**: `@Natty toca tema da taverna` acha
  `data/musicas/taverna/Tema_da_Taverna.mp3` (todas as palavras no nome,
  subpastas contam). Na fila o link fica `arquivo:<caminho relativo>`, e o
  caminho é conferido pra nunca sair da pasta. Arquivo local toca sem as
  flags de reconexão do FFmpeg (são de HTTP). É a fonte certa pra ambiente
  longo: a URL do YouTube expira.
- Spotify não dá (DRM). Freesound precisaria de chave de API, fica de fora.

## Banco do Bardo: playlists, cenas e descobertas por servidor (desde 12/10/2026)

O Bardo tem banco próprio, `data/bardo.db` (`BARDO_DB_PATH`), fora do git
como o do core. `storage.py` é o único lugar que fala SQL; o schema é
criado sozinho no primeiro uso (`PRAGMA user_version`). Tabelas, todas por
servidor: `playlists` + `playlist_itens`, `sons` e `cenas` (usadas pelo
mixer), `descobertas`.

**Playlists salvas** (`/playlist ...`):

| Comando | O que faz |
|---|---|
| `/playlist salvar nome:<x> [substituir]` | salva a fila atual (a que toca + as próximas) |
| `/playlist tocar nome:<x>` ou `@Natty toca a playlist <x>` | põe na fila |
| `/playlist listar` · `/playlist ver nome:<x>` | lista / mostra as músicas |
| `/playlist apagar nome:<x>` | só quem criou ou quem tem o cargo de mestre |

Nome sem diferença de acento/maiúscula; nome errado vem com sugestão.

**Cargo de mestre**: `Condutor` (ou `BARDO_CARGO_MESTRE` no `.env`). O
dono do servidor sempre conta como mestre. Vale pra apagar coisa salva e
pro painel web.

**Dataset por servidor**: o `musicas.json` continua sendo a base global
(versionada). As descobertas do "era essa?" agora vão pra tabela
`descobertas` **do servidor** (mesmo formato de faixa do musicas.json, dá
pra promover pro global à mão), e a busca de cada servidor enxerga base +
as dele. `adicionar_descoberta_ao_dataset` (grava no JSON) ficou pros scripts.

## Playlist do YouTube (desde 12/10/2026)

Link de playlist (`youtube.com/playlist?list=...`) põe a playlist inteira
na fila, na ordem dela, até o limite de 50 (`MAX_FILA`); se não cabe tudo,
a Natty avisa quantas entraram. Vídeo privado ou apagado dentro dela é
pulado. A lista é lida sem resolver o áudio (`extract_flat`), então é
rápida; cada faixa é resolvida na hora de tocar, como qualquer item.

Link de **vídeo** com `&list=` (um vídeo aberto dentro de uma playlist)
continua tocando só aquele vídeo: é o que a pessoa estava vendo quando
copiou. Pra tocar a playlist, copia o link da playlist.

## Remover da fila (desde 12/10/2026)

`@Natty tira a 3 da fila` (ou `remove`, `retira`, `deleta`) tira a música
da posição 3 — a numeração é a de `@Natty fila` (1 = a próxima). Precisa
de um número ou da palavra "fila" na frase: "tira" solto é conversa. Sem
número, a Natty pergunta qual.

## Repetir a fila (desde 12/10/2026)

`@Natty repete a fila` (ou `loop da playlist`, `repete tudo`) liga a
repetição da **fila inteira**: cada música que sai (acabou ou foi pulada)
volta pro fim. Fila de uma música só fica repetindo ela.

- Um repetir desliga o outro: ligar o da faixa desliga o da fila, e vice-versa.
- `@Natty para de repetir` desliga os dois; `@Natty para` também (limpa tudo).
- **Pular não desliga** o da fila (pular numa playlist em loop é normal) —
  diferente do repetir da faixa.
- Música que não tocou (vídeo privado, removido...) **não volta** pro fim:
  senão ficaria falhando em loop pra sempre (`Fila.descartar_atual`).
- `@Natty fila` mostra "🔁 repetindo a fila".

## Sair sozinha da call vazia (desde 12/10/2026)

Quando a última pessoa sai do canal de voz da Natty (bots não contam), ela
espera 60 s (`SEGUNDOS_ANTES_DE_SAIR`) e, se ninguém voltou, para a música,
limpa a fila, sai e avisa no canal do último pedido. Se alguém volta
antes, a saída é cancelada.

**Com o Echo escutando ela não sai**: na conexão do Echo
(`VoiceRecvClient`, a que tem `stop_playing()`), quem decide a saída é o
Echo ("NAT20, por favor, saia"). O Bardo não derruba a escuta de ninguém
nem importa o Echo pra saber disso. Onde mora: `deve_sair_do_canal()` no
`service.py`; o listener `on_voice_state_update` no cog.

## Erros com motivo (desde 12/10/2026)

O `youtube.py` traduz o erro do yt-dlp num `ErroDeMusica` com o motivo, e
a Natty diz o motivo em vez de um "deu erro":

| Erro | O que a Natty diz |
|---|---|
| `VideoPrivado` | o vídeo é privado |
| `RestricaoDeIdade` | o vídeo tem restrição de idade (precisa de login) |
| `SoParaMembros` | o vídeo é só pra membros do canal |
| `BloqueadoNaRegiao` | o vídeo está bloqueado no nosso país |
| `VideoIndisponivel` | o vídeo não existe mais ou está indisponível |
| `PlaylistIndisponivel` | a playlist não existe ou é privada |
| `NadaEncontrado` | (busca livre) "Não achei nada pra ..." |

Erro conhecido vira uma linha de aviso no log, sem traceback; busca sem
resultado nem isso (é só `info`). Erro desconhecido continua com traceback
e com a resposta genérica. `NadaEncontrado` também é `LookupError`, então
quem pegava `LookupError` continua pegando.

O id da menção também não vira mais número: `@Natty volume 30` chega como
`<@1234...> volume 30`, e os dígitos do id eram lidos como volume (ia pra
100%). As menções saem do texto antes de interpretar.

## Busca livre no YouTube e aprendizado por confirmação

Se "@Natty toca <texto>" não acha nada no dataset, a Natty busca o texto
direto no YouTube, toca o primeiro resultado (ou põe na fila, como um link)
e pergunta no mesmo canal: *"Era essa mesmo? **Responde a esta mensagem**
(reply) com uns temas dela"*.

- A resposta tem que ser um **reply direto à mensagem da pergunta**, de
  qualquer pessoa — a mesa é coletiva. O reply não precisa de @ (a
  própria resposta já aponta pra Natty). Mensagem solta no canal, mesmo
  com @Natty, não conta como resposta, e reply a outra mensagem também
  não. Assim, "kkkk" ou um "transcrever" no meio da conversa não viram
  tema (já aconteceu: a faixa "Weight of the World: Piano Collections
  Version" ganhou o tema "transcrever" assim, limpo em 02/10/2026).
  - reply `"não"` (o "não" em qualquer lugar da frase) → descarta, nada é gravado.
  - reply `"é triste e épico"` → grava a faixa com os temas `triste`,
    `épico` (separa por vírgula e por " e "; ignora "sim", "é", "essa",
    "mesmo"...; no máximo 5 temas).
  - reply `"sim"` sem tema → grava como `"não classificado"`: a música é
    a certa, só ninguém opinou sobre o clima.
- O id da mensagem da pergunta fica na pendência (`mensagem_pergunta_id`,
  via `registrar_pergunta_da_pendencia`); `eh_resposta_da_pendencia`
  confere se o reply aponta pra ela.
- A pergunta vale 3 minutos (`SEGUNDOS_PARA_RESPONDER`); depois disso
  ninguém respondeu, e a próxima mensagem é só conversa. Uma pergunta
  por servidor: uma busca nova substitui a anterior.
- Pedido pra Natty (`@Natty pula`, `@Natty toca ...`) nunca conta como resposta.
  Pedidos normais continuam funcionando enquanto a pergunta está aberta.
- A faixa entra no `musicas.json` com origem `Descoberta em mesa` (tipo
  `outro`), id `descoberta-em-mesa-<título>`, e já com as categorias
  calculadas pelo vocabulário. A busca acha ela na hora, sem reiniciar.
  Vídeo que já está no dataset não é gravado de novo.
- Grava o link de watch do vídeo, não a URL de áudio (essa expira).
- Vale conferir de tempos em tempos as faixas `Descoberta em mesa` no
  `musicas.json`: o tema é o que a mesa digitou, não passa pelo vocabulário.

## Busca no dataset

"@Natty toca <texto>" sem link procura no `dataset/musicas.json` (~580
faixas de Elden Ring, Dark Souls, Bloodborne, Fire Emblem: Three Houses,
Umineko, Subahibi, Hollow Knight e NieR:Automata, cada uma com origem e
temas em português) e põe o resultado na fila. Se nada tocava, a primeira
já começa. Se não acha nada, cai na busca livre no YouTube (acima).

- `e` = E, `ou` = OU, `sem`/`não` antes de um termo = exclui o termo.
- O `ou` separa grupos inteiros: `boss fight e elden ring ou hollow knight`
  é `(boss fight e elden ring) ou hollow knight` — traz todo o Hollow
  Knight, não só os boss fights. Pra isso, repete o termo:
  `boss fight e elden ring ou boss fight e hollow knight`.
- Cada termo bate com a faixa se aparece (sem acento, sem diferenciar
  maiúscula) no nome da faixa, na origem, nos temas ou nas categorias —
  **ou** se é sinônimo de uma categoria da faixa (ver abaixo).
- Termo de várias palavras tenta a frase inteira ("boss fight", "hollow
  knight") e, se não bater, cada palavra: "luta de chefe" = luta e chefe.
- Palavras de preenchimento ("uma", "música", "de", "para", "clima"...) são
  ignoradas: "uma música para relaxar", "clima de taverna".
- Achando mais de 15 (`MAX_RESULTADOS_DA_BUSCA`), sorteia 15 e avisa
  quantas achou. A fila continua limitada a 50.

### Categorias e sinônimos

O dataset tinha ~170 temas soltos ("melancólico", "sereno-macabro",
"ódio"...), muitos com uma faixa só, e ninguém numa mesa busca assim. Por
isso existem as **categorias** (`dataset/vocabulario.json`): ~27 coisas que
alguém de fato pede — triste, calmo, tenso, combate, chefe, épico,
sombrio, terror, mistério, mágico, sagrado, alegre, engraçado, romântico,
nobreza, cidade (taverna), exploração, natureza, masmorra, descanso
(acampamento), vilão, final, abertura...

Cada categoria tem:
- `palavras`: o que as pessoas digitam e leva à categoria — "trágico",
  "tristeza", "luto" levam a *triste*; "taverna", "vila" levam a *cidade*.
- `temas`: temas crus que colocam a faixa na categoria, mas que sozinhos
  são específicos demais pra puxá-la inteira (quem busca "coral" quer
  coral, não todo o épico).

Cada faixa do `musicas.json` guarda as suas em `categorias`, geradas a
partir dos `temas`. Depois de mexer no vocabulário ou acrescentar faixas:

```
python scripts/categorizar_musicas.py
```

O script só acrescenta categorias; dá pra pôr uma à mão numa faixa (ex:
"taverna" onde o vocabulário não pegou) e ela fica. Pra tirar, apaga à mão.

**Ainda falta curadoria:**
- 37 faixas (24 do Umineko, com nomes abstratos como "Core" e "Mind", 9 da
  NieR:Automata e 4 do Subahibi) estão como "não classificado" — precisa
  ouvir pra marcar.
- Não há faixa de taverna de verdade: "taverna" cai em *cidade* (hubs,
  cotidiano, mercado), que é a aproximação mais próxima.
- Tema em português não bate com palavra em inglês que só está no nome
  da faixa ("sem chuva" não filtra "(Rain)").

## Repetir a faixa atual (desde 02/10/2026)

`@Natty repete` (ou `repetir`, `repita`, `loop`) liga a repetição da **música que está tocando**: quando ela acaba sozinha, volta do começo em vez de seguir a fila. Pedir de novo desliga; `@Natty para de repetir`, `@Natty repete não`, `@Natty chega de loop` e `@Natty desliga o repetir` desligam sempre. A Natty sempre responde qual estado ficou ("🔁 Repetindo **X**…" / "➡️ Repetição desligada…"), e a `@Natty fila` mostra 🔁 ao lado da atual.

- **Só a faixa atual**. Pra fila inteira, ver "Repetir a fila".
- **Pular desliga o repetir** ("Pulei ⏭️ (repetição desligada)"): pular é "chega dessa", e sem isso a próxima também entraria em loop sem ninguém pedir. **Parar** também desliga (limpa tudo).
- A cada volta a URL de áudio é resolvida de novo (a do YouTube expira), sem aviso no canal. Se falhar, desliga o repetir, avisa e segue a fila.
- "@Natty toca Repete Comigo" continua sendo busca: quando "toca" vem antes, o "repete" é parte do nome.
- Onde mora: o estado é `Fila.repetir` (por servidor, junto da fila); `alternar_repetir()` e `deve_repetir()` no `service.py`; o cog só decide, no fim da faixa, se chama `_repetir_musica()` ou `_tocar_proxima()`.

## Parar não sai mais da call (desde 02/10/2026)

"@Natty para" (e `@Natty chega`, `@Natty sai`, `/parar`) para a música e limpa a fila, mas **a Natty continua no canal de voz**. Quem tira ela da call agora é só o Echo: "NAT20, por favor, saia" ou "@Natty, tampe os ouvidos".

Motivo: com o Echo escutando, sair da call no "para" derrubava a escuta — "NAT20, por favor, pare" (que posta `🎙️ natty para`) deixaria a Natty fora da call. E tinha um bug escondido: na conexão do Echo (`VoiceRecvClient`), `stop()` para a música **e a escuta**, então até "@Natty pula" deixava a Natty surda pra senha. Agora `_parar` e `_pular` usam `_parar_audio()`, que chama `stop_playing()` quando a conexão tem (só a do Echo tem) e `stop()` quando não — sem importar nada do Echo. Testes em `test_cog.py`.

Usando o Bardo **sem** o Echo, depois de "@Natty para" a Natty fica parada no canal até alguém tirar ela ou até a call esvaziar (ver "Sair sozinha da call vazia").

## Pedido falado (mensagens da própria Natty com 🎙)

O listener ignora mensagens de bots, menos a da **própria Natty que começa com 🎙** (`MARCADOR_VOZ` no `cog.py`) — a mesma convenção do Dice. É assim que o pedido de música falado numa call chega aqui: o módulo Echo grava o pedido, transcreve com Whisper e posta `🎙️ natty toca <o que ouviu>`; o Bardo trata como qualquer pedido digitado (dataset, e YouTube se não achar). Nenhum dos dois importa o outro. Quem "pediu" é a própria Natty, então a música toca no canal de voz dela — o mesmo onde o Echo está escutando. As respostas do Bardo nunca começam com 🎙, então ele não reage a si mesmo. Ver `modules/echo/README.md`, seção "Pedido de música".

## Por que não usa Lavalink

Decisão registrada em `modules/sieve/Findings/natty-reports/lavalink-perspective.md`
e confirmada em conversa: para o estágio atual (uma mesa, sem Spotify como
requisito), nem Lavalink nem Kenku em produção fazem sentido. O trade-off
central é que ambos trocam "sem processo extra" por "um processo extra"
(JVM ou Electron) — e o Natty hoje é um monólito modular Python puro (ver
`CLAUDE.md` da raiz).

Este MVP usa a abordagem mais simples possível: `discord.py`'s
`voice_client` nativo + `yt-dlp` (resolve o link em URL de áudio direto) +
FFmpeg (decodifica o stream pro formato que o Discord espera). Zero
processo extra, zero JVM.

A interface de `service.py` foi desenhada para poder ser trocada por um
cliente de um nó Lavalink de verdade no futuro, se o áudio algum dia pesar
demais no processo principal — sem precisar reescrever `cog.py`.

## Estrutura

```
modules/bardo/
├── __init__.py
├── youtube.py     # acesso cru ao YouTube via yt-dlp: link, busca, playlist; traduz os erros
├── service.py      # lógica pura: pedido, fila, volume, busca booleana, busca livre + aprendizado
├── cog.py           # interface Discord: on_message + slash commands, voz, playback, sair da call vazia
├── test_service.py  # testes de pedidos, fila e busca
├── test_youtube.py  # erros traduzidos e playlist, com yt-dlp falso
├── test_cog.py      # parar/pular, repetir, remover, playlist, erros, sair da call vazia
├── dataset/
│   ├── musicas.json      # faixas taggeadas (origem, temas, categorias)
│   └── vocabulario.json  # categorias de busca e seus sinônimos
└── README.md
```

## Requisitos de ambiente (fora do `pip install`)

1. **FFmpeg instalado no sistema** (não é pacote Python — precisa estar no
   `PATH` da máquina que roda o bot). No Ubuntu/Debian: `apt install ffmpeg`.
2. **PyNaCl** e **davey** (já em `requirements.txt`) — `discord.py` exige
   os dois pra voz; o `davey` é a criptografia de voz (DAVE) que o Discord
   passou a exigir. Sem ele a conexão de voz falha.
3. **Message Content Intent habilitada no Discord Developer Portal**
   (Bot → Privileged Gateway Intents → Message Content Intent). Sem isso,
   `message.content` chega sempre vazio pro bot, mesmo com
   `intents.message_content = True` no código — as duas coisas são
   independentes e as duas são necessárias.

## Fluxo

```
Usuário: "@Natty toca https://youtube.com/watch?v=xxx"
        ↓
cog.py (on_message)
  ├─ reply à pergunta "era essa?"? eh_resposta_da_pendencia → interpretar_resposta_de_pendencia
  ├─ falou com a Natty? (menção, cargo ou 🎙 da própria Natty) → _falou_com_a_natty (discord.py)
  ├─ interpretar_pedido(texto) → Pedido      → service.py (regex: tocar/pausar/continuar/parar/volume)
  ├─ usuário está em canal de voz?            → discord.py (message.author.voice)
  ├─ sem link? buscar_musicas(busca)            → service.py (dataset/musicas.json) → fila
  ├─ nada no dataset? resolver_por_busca_livre → youtube.py (ytsearch1:) → toca + criar_pendencia()
  ├─ resposta aceita? adicionar_descoberta_ao_dataset
  ├─ resolver_musica(link)                    → service.py → youtube.py → yt-dlp
  ├─ conecta/move pro canal de voz            → discord.py (voice_client)
  └─ toca via FFmpegPCMAudio + volume         → discord.py + FFmpeg
```

## Testes

```
python -m unittest discover -s modules/bardo -t .
```

Cobrem o reconhecimento de pedidos, a fila, a busca booleana e o
aprendizado por confirmação (resposta, prazo, gravação sem duplicar)
(`service.py`), inclusive um teste que valida o dataset real; a tradução
de erros e a leitura de playlist (`youtube.py`, sem rede); e o cog com
dublês do Discord. A parte de voz é validada à mão no Discord.

## O que falta pro próximo passo

- Classificar as 37 faixas "não classificado" e trilhas de taverna de verdade
- Completar Dark Souls no dataset (hoje 3 faixas)
- Volume por voz (os outros controles — tocar, parar, próxima, repete, pausa, continua — já funcionam pelo Echo; ver README do Echo, "Controles do Bardo por voz")
- Validar ao vivo: playlist, repetir a fila e a saída da call vazia (testados só com dublês)

Resolvidos: o "era essa?" que aceitava qualquer mensagem já era só por
reply desde 02/10/2026 (ver "Busca livre"); título com "volta"/"próxima"/
"fila" virando comando, erro genérico e traceback em busca sem resultado,
remover da fila, playlist, repetir a fila, `/repetir` e sair da call vazia
saíram em 12/10/2026.
