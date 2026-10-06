# Módulo Echo

Ouve fala em canal de voz e reconhece a senha de ativação **"NAT20, por
favor"** (referência à designação dela, NAT/20-01-XR7-Δ9, e ao crítico
natural de 20 no d20). Tudo offline, sem custo de API.

**O que faz hoje:** "NAT20, por favor" → a Natty responde "👂 fala a
rolagem" → a pessoa fala uma rolagem ("rola dado vinte mais cinco com
vantagem") → ela posta `🎙️ rolo 1d20+5 com vantagem` no canal e o Dice
rola. "NAT20, por favor, saia" tira ela da call. Ver "Fluxo de voz" e
"Rolagem falada". "NAT20, por favor, música" + o nome da música → o Bardo
toca (ver "Pedido de música").

## Fluxo de voz

```
@Natty escuta (texto)  → 👂 Escutando...
        │
"NAT20, por favor"  ──────────────┬─ "..., saia" / "sai" / "sair" → 🙈 sai da call
  (Vosk, grammar da senha)        │
                                  ├─ "..., música" → 🎵 fala a música → "Garçom"
                                  │     (grava, Whisper) → 🎙️ natty toca Garçom → 🎵 Bardo toca
                                  │
                                  ├─ "..., pare" / "para" / "parar" → 🎙️ natty para
                                  │     → Bardo para a música; a Natty continua na call, escutando
                                  │
                                  ├─ "..., próxima" / "pula" → 🎙️ natty pula
                                  ├─ "..., repete" → 🎙️ natty repete (liga/desliga o loop da faixa)
                                  ├─ "..., para de repetir" → 🎙️ natty para de repetir
                                  ├─ "..., pausa" / "continua" → 🎙️ natty pausa / continua
                                  │
                                  └─ sozinha, "..., rolo" ou qualquer outra coisa
                                        → 👂 fala a rolagem ─┬─ "dado vinte mais cinco"
                                                             │    → 🎙️ rolo 1d20+5 → 🎲 Dice rola
                                                             └─ "música" → 🎵 fala a música → ...
@Natty, tampe os ouvidos (texto) → 🙈 sai da call
```

- O que vem **na mesma frase** da senha decide o caminho
  (`acao_depois_da_senha()`, que usa `extrair_comando()`): "saia/sai/sair"
  sai, "música" grava o pedido de música; o resto abre a janela da rolagem
  — e lá, "música" como primeira palavra também troca pro pedido de música
  (`escolheu_musica()`), pra quem fala a senha e faz uma pausa.
- "saia", "sai", "sair", "música" e "rolo" estão na grammar da senha
  (`PALAVRAS_DEPOIS_DA_SENHA`). Fora dela, o Vosk transformaria a palavra em
  `[unk]` e ela sumiria — foi o que aconteceu com o "dê". Sozinhas (sem a
  senha) não fazem nada: "Saia daqui, goblin" ou "vou sair" na conversa da
  mesa não tiram a Natty da call.
- Testado com o Vosk real e voz sintética: "…por favor, saia" saiu
  `net vinte por favor saia` (e "sai" igual); "…por favor, rolo" e a senha
  sozinha abriram a rolagem; "Vou sair pra pegar água" e "Saia daqui
  goblin" não fizeram nada. **Em call real (01/10/2026): 4 de 4**
  ("nate vinte por favor saia"), com outras 3 pessoas falando na sala.
- Sair por voz e por texto usam a mesma função (`_desligar` no cog).
- **"NAT20, por favor, pare"** (ou "para"/"parar") posta `🎙️ natty para` e o
  Bardo para a música — a Natty **continua na call, escutando a senha**.
  Pra isso o Bardo mudou junto: o "parar" dele não sai mais da call, e
  parar/pular agora usam `stop_playing()` na conexão do Echo — o `stop()` do
  `VoiceRecvClient` para a música **e a escuta**, e deixava a Natty surda
  (ver README do Bardo, "Parar não sai mais da call"). Desde então, **só o
  Echo tira a Natty da call** ("saia" / "tampe os ouvidos"). "pare/para/parar"
  estão na grammar da senha; sozinhos não fazem nada.
- **Controles do Bardo por voz** (`COMANDOS_DO_BARDO_POR_VOZ`): depois da
  senha, "próxima"/"pula", "repete", "para de repetir", "pausa" e
  "continua" postam `🎙️ natty <comando>` — o Bardo já entende todos por
  texto, então o Echo só traduz a palavra falada. "para de repetir" é frase
  inteira na grammar e é checada **antes** do "para" (senão pararia a
  música em vez de desligar o loop). "loop" e "proxima" sem acento não
  existem no vocabulário do modelo — por voz é "repete" e "próxima".
  Testado com o Vosk real e voz sintética: os 6 comandos saíram certos, e
  "Pula essa parte, vamos continuar" sem a senha não fez nada.

### Quem ela escuta: só quem mandou "@Natty escuta"

O Discord já entrega o áudio de **cada pessoa separado** (um fluxo por
participante, não o som misturado da sala), e o Echo sempre teve um
reconhecedor por pessoa — a voz de um nunca entra na frase do outro.
Mesmo assim, ouvir a sala inteira tinha custo: numa call real com 4 pessoas
(01/10/2026) vieram 332 frases de ruído — a conversa da mesa sendo forçada
nas palavras da grammar ("favor", "rolo", "sai", "música") — sem nenhum
disparo falso, mas sujando o log e gastando CPU.

Por isso **quem manda "@Natty escuta" vira o dono da sessão**: só a voz
dele é processada; o áudio dos outros é descartado logo na entrada do
`_on_audio`, antes do Vosk (contador `sink.outros` no diagnóstico). Outra
pessoa assume mandando "@Natty escuta" de novo. Áudio cujo dono o Discord
ainda não identificou também é descartado (o `dave.py` descobre o dono em
instantes).

## Escriba (ata da sessão: grava tudo, transcreve no fim)

```
Mestre (texto): @Natty, grava a sessão
Natty:          🔴 Gravando a sessão — todo mundo na call. Pra parar: @Natty, para de gravar.
   ... a mesa joga; comandos de voz continuam funcionando normalmente ...
Mestre (texto): @Natty, para de gravar
Natty:          🛑 Gravação encerrada (212 min). Quer que eu transcreva agora? @Natty, sim ou @Natty, depois.
Mestre (texto): @Natty, sim
Natty:          📝 Transcrevendo (pode levar alguns minutos)...
Natty:          📝 Pronto! Ata salva em `logs/sessoes/2026-10-02-21h30/ata.txt`.
```

| Gatilho (só por texto, com **@Natty de verdade**) | O que faz |
|---|---|
| `@Natty, grava a sessão` / `grava` / `começa a gravar` | Começa a gravar (precisa ter mandado "@Natty escuta" antes) |
| `@Natty, para de gravar` / `pare a gravação` | Para de gravar e **pergunta** se transcreve agora |
| `@Natty, sim` / `pode` / `transcreve` (depois da pergunta) | Transcreve a gravação que acabou de parar |
| `@Natty, depois` / `não` (depois da pergunta) | Não transcreve: "Ok, fica gravado. Quando quiser, chama `@Natty, transcreve a sessão`." |
| `@Natty, transcreve a sessão` (a qualquer hora) | Transcreve a gravação mais recente que ainda não tem `ata.txt` (se não houver: "Não achei nenhuma sessão gravada esperando transcrição.") |
| Sair da call ("saia" / "tampe os ouvidos") com a gravação ligada | Fecha os arquivos e **não** transcreve — o áudio fica guardado |

- A pergunta "transcrevo agora?" fica guardada em
  `sessao_pendente_transcricao[guild_id] = (pasta, quando)` e vale 15 min
  (`ESCRIBA_CONFIRMACAO_SEGUNDO`). Depois disso, "sim" não faz nada — mas o
  `@Natty, transcreve a sessão` continua achando a pasta.
- Outro comando no meio (ex: `@Natty toca …`) não mexe na pergunta.
- "Transcrever" separado de "parar" porque a transcrição de uma sessão
  inteira leva tempo e pesa a CPU: dá pra parar no fim da mesa e mandar
  transcrever quando o notebook estiver livre.

**Liga/desliga só por texto, de propósito**: é coisa de começo e fim de
sessão, não de meio de jogo, e assim essas palavras não entram na grammar
da senha disputando espaço com os comandos de voz.

**Como funciona:**

1. **Grava, não transcreve.** Enquanto ligada, cada pacote de áudio de
   **cada pessoa** (todo mundo, não só o dono da sessão — é a ata da mesa)
   vai pra um `.wav` dela em `logs/sessoes/<data-hora>/`, em 16kHz mono. A
   gravação acontece antes do filtro do dono no `_on_audio`; senha e
   comandos continuam só do dono. A mensagem de ligar avisa que todo mundo
   está sendo gravado.
2. **Marcas de horário.** O Discord só manda áudio **enquanto a pessoa
   fala** — nos silêncios não chega pacote nenhum, então o `.wav` é fala
   colada com fala, e a posição no arquivo não é o horário da sessão. A
   cada volta da fala depois de uma pausa (`ESCRIBA_PAUSA_MARCA_SEGUNDO`,
   0.3s), o cog guarda uma marca `[posição no arquivo, horário real]`
   (`marcas.json`). Sem isso, a ata sairia com horários errados e a ordem
   entre pessoas embaralhada. Preencher os silêncios com zeros também
   resolveria, mas a ~115MB por pessoa por hora; as marcas custam quase nada.
3. **Transcreve em blocos de fala.** `blocos_de_fala` corta o `.wav` de
   cada pessoa onde houve pausa **real** ≥ 4.5s
   (`PAUSA_NOVO_PARAGRAFO_SEGUNDO`), e cada bloco vai separado pro
   faster-whisper `large-v3-turbo` (int8, português fixo, `vad_filter=True`).
   Cada segmento vira horário real pelas marcas (`horario_real`).
4. **Junta em parágrafos.** `juntar_em_paragrafos` emenda falas seguidas da
   mesma pessoa quando a pausa entre elas é menor que 4.5s — a ata fica
   `[HH:MM:SS] Nome: parágrafo`, em vez de uma linha por frase quebrada.
   Outra pessoa falando no meio sempre abre parágrafo novo, e nenhum
   parágrafo passa de 60s (`DURACAO_MAX_PARAGRAFO_SEGUNDO`) — quem narra
   sem pausa vira vários parágrafos, cada um com o seu horário.

**Modelo: `large-v3-turbo`, não `distil-large-v3`.** O pedido original era
o `distil-large-v3`, mas ele é **só inglês** — com português ele traduz ou
inventa. O `large-v3-turbo` é multilíngue, tem a mesma ideia (decoder
enxuto, rápido) e é bem melhor que o `small` usado na 1ª versão.

**Hotwords (`TERMOS_DA_CAMPANHA`):** nomes da campanha (Natty, Nhalor,
Crossroads, Vorric, Elijah Vorren, Thalassar...) vão como `hotwords` pro
modelo preferir essas grafias. Quando aparecer nome novo na mesa, é só
acrescentar ali.

**`condition_on_previous_text=False`:** com `True`, o turbo repetiu uma
frase em loop e **pulou o final** de uma gravação real. Sem o contexto
anterior cada trecho é independente — perde um pouco de coerência, mas não
trava em repetição.

**Resultado real (02/10/2026, leitura da Nhalor, ~3 min):** o turbo acertou
o que o `small` errava ("Natty", "deixou de ser reconhecido", "aventureiros
do Crossroads", "rolo os dados"), texto completo, 110s pra transcrever.
Ainda erra "Naylor" (Nhalor — mesmo com hotword) e "Toca física" (toco
música). RAM: ~833MB com o modelo carregado, pico ~1.2GB transcrevendo. O
modelo só é carregado na primeira transcrição e depois fica em memória até
o bot reiniciar.

**Velocidade e fila (02/10/2026, depois da 1ª sessão real):** duas
sessões (38 e 75 min de fala somando todo mundo) passaram de 2h
transcrevendo ao mesmo tempo, com a máquina 75% ociosa. Mudou:
- `beam_size=1` (`ESCRIBA_BEAM_SIZE`): o padrão testa 5 hipóteses por
  trecho; com 1, a qualidade em português de mesa quase não muda e fica
  2-3x mais rápido.
- `cpu_threads` = núcleos físicos (`ESCRIBA_CPU_THREADS`, 6 no Ryzen 5
  4600H); o padrão era 4.
- **Uma transcrição por vez** (`_escriba_fila`): a segunda pedida responde
  "📝 Na fila…" e espera. A mesma sessão não entra duas vezes, e
  `@Natty, transcreve a sessão` pula a que já está rodando.
- **Pacotes de blocos (a causa principal):** o Whisper processa sempre
  janelas de 30s, então um bloco de 2s custa o mesmo que um de 30s. Na
  sessão 19h08 eram 336 blocos pra 40 min de fala, 279 com menos de 10s.
  Agora blocos seguidos da mesma pessoa vão juntos (`agrupar_blocos`, até
  28s com 1s de silêncio entre eles), e o modelo devolve o horário de cada
  palavra (`word_timestamps=True`). `falas_por_bloco` devolve cada palavra
  pro bloco dela, e um trecho que atravesse o silêncio vira duas falas, cada
  uma no horário certo. Ganho esperado: ~4x menos chamadas. **Ainda não
  medido com áudio real**: o teste foi interrompido por falta de RAM,
  porque o notebook tem 7.4GB e o bot já estava com o modelo carregado.
- **Idioma fixo em português** (`ESCRIBA_IDIOMA = "pt"`): com
  `language=None` o faster-whisper roda o encoder (a parte pesada do modelo)
  uma vez a mais em toda chamada só pra detectar o idioma, sem reaproveitar
  o resultado (visto no código do 1.2.1, `detect_language`). Isso dobrava o
  trabalho, e trecho curto ainda podia ser lido como inglês.
- **Retomável** (`parcial.jsonl` na pasta da sessão): cada pacote
  transcrito é salvo na hora. Se cair no meio (falta de RAM, bot
  reiniciado), a próxima transcrição pula o que já está lá e continua de
  onde parou. Linha cortada no fim (caiu escrevendo) é ignorada. O arquivo
  some quando a ata fica pronta. Antes, cada tentativa recomeçava do zero.
- **Progresso no log** a cada 10%:
  `[echo] Escriba: 2026-10-02-19h58 40% (30 de 75 min de fala, 12 min rodando, ~18 min pra acabar)`.

**O áudio vai pro faster-whisper como array, não como caminho:** o
faster-whisper 1.2.1 abre arquivo pelo PyAV, e o PyAV 19 recusa um
parâmetro que ele passa (`TypeError: ... 'metadata_errors'`, visto em
02/10/2026). `_ler_wav_como_array` lê o `.wav` e o decodificador nem é
chamado.

**Tamanho:** ~32KB por segundo **de fala** (silêncio não é gravado) ≈
115MB por hora de fala por pessoa.

**`logs/sessoes/` fica fora do git** (`.gitignore`; já coberto por `logs/`).

**Transcrever à mão** (ex: o bot reiniciou): `@Natty, transcreve a sessão`
acha a última pasta sem `ata.txt`. Pra uma pasta específica:
`python -c "from pathlib import Path; from modules.echo import service; p = Path('logs/sessoes/<pasta>'); print(service.transcrever_sessao(p, service.inicio_da_pasta(p)))"`.

**Por que mora no Echo:** a conexão de voz aceita um receptor de áudio só
(`voice_client.listen()`), e é o Echo. Não toca em Dice nem Bardo.

**Ajuste que precisou no Bardo:** "@Natty para de gravar" também chega no
Bardo, e "para" é o comando de parar dele — a música parava junto. Agora
"para de X" só para a música se X for tocar/cantar/música.

**Antes de confiar numa sessão de verdade:** testar 1-2 min com 2 pessoas
e o Bardo tocando ao mesmo tempo; conferir o tamanho dos `.wav` e a RAM
durante a transcrição.

## Pedido de música (Echo → Whisper → Bardo)

```
Mestre (voz): "NAT20, por favor, música"
Natty:        🎵 fala a música, Mestre!
Mestre (voz): "Garçom"
Natty:          ↳ 🎙️ natty toca Garçom
Natty (Bardo):      ↳ Tocando **Reginaldo Rossi - Garçom** 🎵
```

**Por que Whisper aqui e Vosk na rolagem.** Nome de música não cabe numa
lista fechada, então o Vosk (vocabulário fechado) não serve. O Whisper tem
vocabulário aberto, mas não é streaming: precisa do áudio inteiro de uma
vez. Por isso o ramo de música é estruturalmente diferente:

1. Ao entrar no pedido de música, o estado da pessoa vira "gravando"
   (`_Ouvinte.musica_pcm`, um `bytearray`). Cada pacote que chega é só
   **concatenado**, no formato cru que o Discord entrega (48kHz estéreo) —
   nada vai pro Vosk.
2. A vigia fecha a gravação como no comando: `SILENCIO_FIM_MUSICA_SEGUNDO`
   (1.5s) de silêncio depois de começar a falar, `JANELA_MUSICA_SEGUNDO`
   (5s) se ninguém falar, teto de `MUSICA_MAXIMO_SEGUNDO` (10s).
3. `await asyncio.to_thread(service.transcrever_pcm, pcm, 48000, 2, dica=None)`
   — numa thread porque leva segundos de CPU e travaria o bot. Um pedido por
   vez (`_whisper_lock`). `dica=None`: a dica da senha ("NAT20, por favor.")
   atrapalharia o nome da música. O Whisper começa a carregar assim que o
   pedido abre, enquanto a pessoa ainda está falando.
4. `limpar_pedido_de_musica()` tira pontuação e o "toca"/"natty"/"música"
   que a pessoa possa ter falado antes do nome ("Toca Song of Storms." →
   `Song of Storms`; "Música combate." → `combate`, como veio em call real).
   Custo: uma música cujo nome comece com "Música" perde essa palavra.
5. Posta `🎙️ natty toca <pedido>` como resposta ao "🎵 fala a música". O
   Bardo reage como se alguém tivesse digitado — incluindo cair na busca do
   YouTube quando não acha no dataset.

**Como chega no Bardo sem import.** Igual ao Dice: o Bardo ignorava
mensagem de bot, então passou a aceitar mensagem **da própria Natty que
comece com 🎙** (`MARCADOR_VOZ` no cog do Bardo). E o Bardo só atende
pedido que chama a Natty e tem verbo — por isso o texto é "natty toca …",
não só o nome da música. Quem "pediu", pro Bardo, é a própria Natty: ele
toca no canal de voz dela, que é o mesmo onde o Echo está escutando, pela
mesma conexão.

**Testado offline** com o Whisper real e voz sintética, até a busca do
Bardo: "Garçom" → achou a do Reginaldo Rossi; "combate de chefe" → 106
faixas. Errou "Grão de Areia" (`grande arreia`), "Triste e épica" (`3G
épica`) e "Clube da Esquina" (`Flube da esquina`) — a voz sintética
pronuncia mal; nesses o Bardo cairia na busca do YouTube. Cada pedido levou
~1-3s com o modelo carregado.

**Em call real (01/10/2026), 6 pedidos:**

| Falado | Whisper ouviu | Resultado |
|---|---|---|
| "Garçom" | `Garçom.` | ✅ tocou (7.7s de transcrição) |
| "Ela Partiu" | `Ela partiu de maio.` | ✅ tocou a do Tim Maia (3.8s) |
| "combate" | `Música combate.` | ⚠️ o "música" vazou pro pedido — corrigido depois |
| Trio Parada Dura | `Tril para a da dura.` | ❌ nome errado (9.1s) |
| nome em inglês | `leença fecha en verf, outro barrels blast.` | ❌ ilegível (7.2s) |

O **primeiro pedido da sessão levou 46s** pra transcrever: o modelo
carregou na hora, e o bot roda com prioridade abaixo do normal (padrão do
Agendador de Tarefas). Os seguintes levaram 4-9s.

**Limitações conhecidas:**
- O Whisper `base` erra nomes próprios e nomes em inglês (transcreve com
  `language="pt"`). Opções em aberto: modelo `small` (mais preciso, ~3x mais
  lento), deixar o idioma automático, ou dica com nomes do acervo.
- Primeiro pedido lento (46s). Opções em aberto: carregar o Whisper no
  "@Natty escuta" e o bot subir a própria prioridade pra normal no Windows.
- O Bardo checa pular/fila/volume/pausar/continuar antes de "tocar": uma
  música com "volta", "próxima" ou "fila" no nome ("natty toca Volta pra
  Casa") vira outro comando. É do Bardo, vale igual pra pedido digitado.

**Detecção atual: Vosk com grammar restrita**, validada em call real em
01/10/2026 (ver "Detecção com Vosk"). Substituiu a versão com Whisper,
validada em 30/09/2026 (commit `0d14914`).

## Detecção com Vosk (grammar restrita)

### Por que saiu o Whisper (e por que não Porcupine)

O Whisper transcreve fala livre, em qualquer palavra do idioma — pesado
demais só pra achar uma frase fixa. Em call real a primeira transcrição da
sessão levou 17-29s, e ele rodava em todo trecho de fala, com ou sem senha.

A primeira tentativa de troca foi o Porcupine (wake-word engine), abandonada
antes de testar: a Picovoice descontinuou o plano gratuito.

O Vosk (Kaldi, open source, offline) aceita uma **grammar**: a lista fechada
de frases que ele pode reconhecer. Em vez de procurar a melhor frase entre
todas as do português, ele só decide entre meia dúzia de opções + `[unk]`
(qualquer outra coisa). Busca bem menor = muito menos CPU. Medido com o
modelo real, pacotes de 20ms como o Discord entrega: **~2-3% de CPU do tempo
de fala** (0.1s de processamento pra 4s de áudio).

### Como funciona o streaming (`cog.py`)

1. Cada pacote de áudio (20ms, 48kHz estéreo) passa por
   `resample_para_16k_mono` (16kHz mono, o que o Vosk espera).
2. Vai direto pro `KaldiRecognizer` daquela pessoa — um por pessoa, porque
   ele guarda a frase em andamento. O modelo (31MB) é carregado uma vez e
   compartilhado.
3. `processar_chunk_vosk` devolve `None` enquanto a frase está em andamento;
   quando o **próprio Vosk** decide que ela terminou (pausa), devolve o
   texto. Não existe mais buffer esperando silêncio nem laço de checagem.
4. `tem_wake_word(texto)` — a mesma regex de antes — decide se é a senha.
   Se for, a saudação é agendada no loop do bot (`run_coroutine_threadsafe`,
   porque o áudio chega numa thread do voice-recv, fora do loop).

O Vosk roda direto na thread de áudio, sem `asyncio.to_thread`: ela já é
separada do loop do bot, e o custo por pacote é ~0.4ms.

### O "NAT" não existe no vocabulário do modelo

Grammar restrita só aceita palavras que o modelo conhece, e **"nat" não está
no vocabulário** do `vosk-model-small-pt-0.3`. Com `"nat vinte por favor"` na
grammar, o Vosk descarta o "nat" calado e sobra `"vinte por favor"` — que
dispararia com qualquer um pedindo "vinte, por favor" e ainda não passaria na
regex. Por isso o "NAT" entra por palavras existentes que soam parecido
(`PALAVRAS_PARECIDAS_COM_NAT` em `service.py`: nate, net, nata, neto,
nathan). Testado com voz sintética pt-BR:

| Falado | Vosk ouviu | Ativou? |
|---|---|---|
| "Néti vinte, por favor" | `[unk] net vinte por favor` | ✅ |
| "NAT20, por favor" | `[unk] vinte por favor` | ❌ (devia) |
| "Vinte por favor" | `vinte por favor` | ✅ não ativou |
| "Me passa o sal, por favor" | `[unk] por favor` | ✅ não ativou |
| "Nada disso, por favor" | `[unk] nata [unk]`, `por favor` | ✅ não ativou |
| "Consegui um nat 20 na rolagem" | `vinte [unk]` | ✅ não ativou |
| "Tirei um natural vinte" | `nathan vinte` | ✅ não ativou |

A voz sintética pronuncia "NAT" mal ("N-A-T"). **Com voz real (call de
01/10/2026), "NAT20, por favor" saiu `nate vinte por favor` nas 3 de 3
tentativas** — frase inteira, sem nenhum `[unk]` — e nenhum falso positivo
com conversa normal. Se outra voz/sotaque não ativar, o log `[echo]` mostra
o que o Vosk ouviu, e é só acrescentar a palavra em
`PALAVRAS_PARECIDAS_COM_NAT`. Último recurso: aceitar `[unk] vinte por
favor` como senha (com o custo de "me dá vinte, por favor" também ativar).

Outras armadilhas encontradas:
- `json.dumps` da grammar precisa de `ensure_ascii=False`, senão palavra
  acentuada vira `é` e some do vocabulário.
- A biblioteca C do Vosk **não abre caminho com acento** no Windows ("Failed
  to create a model") — e o projeto mora em `Repositórios`.
  `_caminho_ascii()` usa o caminho relativo ou o nome curto 8.3 do Windows.

### Whisper e a regex continuam no `service.py`

`transcrever`, `transcrever_pcm`, `reconhecer` e `extrair_comando` não são
mais usados pelo cog, mas ficam: vão servir no dia de entender comando livre
depois da senha ("NAT20, por favor, rola 1d20") — a arquitetura imaginada é
Vosk leve sempre ligado + Whisper só sob demanda, por poucos segundos, depois
que a senha dispara.

## Por que a senha exige "por favor" e não é só "NAT20" (histórico: era do Whisper)

Isso não é estética — foi calibrado com Whisper real, com voz sintética
pt-BR, 48kHz estéreo (mesmo formato que o Discord entrega):

| Falado | Whisper ouviu | Ativou? |
|---|---|---|
| "NAT20" (sozinho) | `24.` | ❌ (devia ativar) |
| "Nat vinte" (sozinho) | `Agunha TV` | ❌ (devia ativar) |
| "Ok pessoal, NAT20, rola iniciativa" | transcrição correta | ✅ |
| "Eu ataco o goblin com a espada" | transcrição correta | ✅ sem falso positivo |
| "Tirei um natural vinte no dado" | transcrição correta | ✅ sem falso positivo |

Frase de uma palavra só confunde o Whisper (ele "alucina" texto sem sentido
quando não tem contexto suficiente) e ainda demora mais pra transcrever (5-8s
contra ~1s de frases normais). Exigir "por favor" junto resolve dois
problemas de uma vez:

1. **Deixa de ser uma frase isolada de 1 palavra** — o mesmo motivo que fez
   "Ok pessoal, NAT20, rola iniciativa" funcionar bem.
2. **Evita falso positivo em jogo real** — jogador de D&D fala "nat 20"
   naturalmente pra comemorar um crítico ("consegui um nat 20 na
   iniciativa!"), sem nenhuma intenção de ativar a Natty. Exigir "por favor"
   junto separa "comentário de jogo" de "pedido pra Natty".

## O "NAT" que o Whisper erra: dica + regex tolerante (histórico; a regex ainda vale)

Mesmo com "por favor", o Whisper (sem ajuda) escreve o "NAT" de vários
jeitos: `NAA-20`, `Enheá-te 20`, `N-A-T20`, `INIATE 20`. Duas defesas,
em `service.py`:

1. **`DICA_WHISPER = "NAT20, por favor."`** vai como `initial_prompt` em toda
   transcrição e ensina a grafia. Com ela, a voz de teste passou a sair
   `NAT20, por favor.`. Testado que silêncio, ruído fraco/forte e estalo
   continuam saindo vazios (o Whisper não "repete a dica" sozinho).
   (A dica só com "NAT20" piorava — virava "INIATE 20"; a frase inteira não.)
2. **`_SENHA_RE` tolerante**: aceita qualquer palavra curta com "n" no lugar
   do "nat", desde que venha seguida de "20/vinte" e "por favor". Em call
   real isso pegou `Nath20, por favor.`, que a regex antiga perdia.
   Custo conhecido: "tenho 20, por favor" também ativa.

## Status

| Peça | Status |
|---|---|
| Detecção com Vosk (`service.py` + `cog.py`) | ✅ Validado em call real (01/10/2026): 3 de 3, sem falso positivo |
| Rolagem falada → Dice (dado, bônus, vantagem, CD, filtro, explosivo, teste por dado) | ✅ Validado em call real (01/10/2026) |
| Pedido de música falado → Bardo (Whisper) | ✅ Funciona em call real (01/10/2026): "Garçom", "Ela Partiu" — ⚠️ erra nomes difíceis/em inglês, 1º pedido lento (ver "Pedido de música") |
| "NAT20, por favor, saia" | ✅ Validado em call real (01/10/2026): 4 de 4 |
| "NAT20, por favor, pare" (para a música, continua na call) | ✅ Validado em call real (02/10/2026) |
| Pedido de música com idioma detectado (`idioma=None`) | ✅ "Take on me" saiu em inglês (02/10/2026) — ⚠️ palavra única pode virar outra língua ("Garçom" → `Garçon`) |
| Escutar só o dono da sessão | ⚠️ Testado offline; **falta call com mais gente** |
| Rolagem falada → Dice (reroll, moedas, nome do teste) | ⚠️ Testado offline (Vosk real + Dice real, voz sintética); em call real o reroll foi cortado na respiração — corrigido (pedaços acumulados), **falta revalidar** |
| Detecção com Whisper (substituída; código mantido no `service.py`) | ✅ Validado em call real (30/09/2026) |
| Entrar/sair da call | ✅ Validado em call real |
| `dave.py` (decifra o DAVE do áudio recebido) | ✅ Validado em call real — remendo temporário, ver abaixo |

## Criptografia DAVE do Discord (resolvido com `dave.py`)

Desde mar/2026 o Discord exige DAVE (criptografia ponta a ponta) nas calls.
O `discord.py` 2.7 + `davey` entram no grupo criptografado, mas o
`discord-ext-voice-recv` (0.5.2a179, a versão do PyPI) só tira a camada de
transporte do áudio recebido. No primeiro teste em call, o Opus recebeu
pacote ainda cifrado: `OpusError: corrupted stream` — e esse erro matava a
thread de leitura, então a Natty ficava surda sem mais nenhum aviso.

O conserto oficial é o
[PR #54](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54)
do voice-recv, ainda aberto. Em vez de instalar o fork (código de terceiros
fora do PyPI), `dave.py` faz a mesma coisa como código nosso, aplicado por
`dave.aplicar()` no `setup` do cog:

- **Decifra antes do buffer** (`PacketDecoder.push_packet`): todo frame que
  termina com o marcador DAVE `0xFAFA` passa por
  `dave_session.decrypt(user_id, MediaType.audio, ...)` com a sessão da
  própria conexão. Decifrar antes do buffer (e não na hora de decodificar,
  como o PR faz) garante que a recuperação de pacote perdido (FEC), que
  espia o próximo pacote, também receba áudio decifrado.
- **Descobre o dono do SSRC pela chave**: se o evento SPEAKING do Discord
  ainda não disse de quem é o SSRC (ou o SSRC foi reaproveitado), testa a
  chave de cada participante (`get_user_ids()`); a que decifrar é a de quem
  fala, e o mapeamento fica registrado.
- **Pacote ruim vira silêncio**, nunca derruba a escuta: falha de decifragem
  (comum por instantes quando alguém entra/sai), `PanicException` do Rust e
  `OpusError` viram perda de pacote (o Opus completa com PLC).

**Quando o PR #54 sair numa versão do PyPI, apagar `dave.py`,
`test_dave.py` e a chamada `dave.aplicar()` no cog.**

## Validação em call real (30/09/2026, versão com Whisper — histórico)

- Áudio decifrado: centenas de pacotes `decifrado`; `opus_corrompido` só
  nos primeiros instantes (troca de chaves).
- Senha: `'NAT20, por favor.'` e `'Nath20, por favor.'` ativaram (3 de 3
  tentativas). Nenhum falso positivo — nem com "Ei, NAT" numa frase comum.
- Sair da call com "@Natty, tampe os ouvidos": ok.
- **Latência**: a primeira transcrição da sessão levou 17-29s; depois,
  1-4s. Suspeitas: o modelo carregando junto das primeiras transcrições, e
  o Agendador de Tarefas do Windows rodando o bot com prioridade abaixo do
  normal. Deixou de importar pra senha (o Vosk substituiu o Whisper), mas o
  mesmo atraso voltou no pedido de música (46s) — ver "Pedido de música".

## Log de diagnóstico

Tudo do Echo aparece em `logs/natty.log` com o prefixo `[echo]`:

- `[echo] escutando em #canal (Vosk)` / `[echo] a escuta terminou`
  (ou `parou por erro: ...`).
- `[echo] <quem>: senha=True: '[unk] net vinte por favor'` — uma linha por
  frase que o Vosk fechou com algo da grammar (frases que deram só `[unk]`
  ou vazio não aparecem). `<quem>` é o id do usuário, ou `('ssrc', n)` se
  ainda não se sabe de quem é. **É essa linha que calibra
  `PALAVRAS_PARECIDAS_COM_NAT`.**
- `[echo] diagnóstico 5s: sink={...} dave={...}` — a cada 5s com áudio
  chegando, contadores por etapa. Como ler:
  - `dave.decifrado` alto: DAVE ok. `sem_dave`: pacotes sem criptografia
    (silêncio) — normal.
  - `sessao_nao_pronta`, `falha_decifrar`, `sem_dono` altos e sem
    `decifrado`: o problema está na decifragem.
  - `sink.outros`: pacotes de quem não é o dono da sessão (ou sem dono
    identificado), descartados antes do Vosk — ver "Quem ela escuta".
  - `sink.frases`: quantas frases o Vosk fechou no modo senha (inclui as só
    `[unk]`). `pacotes` > 0 e `frases` = 0 por muito tempo: o Vosk não está
    achando fim de frase.
  - `sink.senhas` / `sink.rolagens`: senhas ouvidas e rolagens postadas;
    `sink.pedidos_musica` / `sink.musicas`: pedidos de música abertos e postados.
- `[echo] <quem>: música 2.1s, transcrita em 1.4s: 'Garçom.' -> 'Garçom'` —
  o que o Whisper ouviu no pedido de música e o que foi pro Bardo.
- `[echo] <quem>: comando 'rola dado vinte mais cinco' -> 'rolo 1d20+5'` —
  o que o Vosk ouviu no modo comando e no que a normalização transformou
  (`None` = não era uma rolagem completa).

## Rolagem falada (Echo → Dice)

### O fluxo

```
Marcelo (voz): "NAT20, por favor"
Natty:         👂 fala a rolagem, Marcelo!
Marcelo (voz): "dado vinte mais cinco com vantagem"
Natty:           ↳ 🎙️ rolo 1d20+5 com vantagem
Natty (Dice):        ↳ 🎲 1d20 [~~13~~, 20] + 5 (vantagem) = 25
```

1. A senha troca o reconhecedor daquela pessoa pro **modo comando**: outro
   `KaldiRecognizer`, com o vocabulário de dados (`PALAVRAS_COMANDO_DADO`).
   É uma lista de palavras soltas, não de frases: o Vosk aceita qualquer
   sequência delas, então não precisa listar toda combinação possível.
   A frase da senha é fechada pela vigia depois de
   `SILENCIO_FIM_SENHA_SEGUNDO` (0.5s) sem voz — não pelo Vosk. Na pausa o
   Discord para de mandar pacotes, então o Vosk não "ouve" o silêncio e a
   frase ficava aberta até a pessoa voltar a falar: em call real a senha
   engolia o começo da rolagem (`'nate vinte por favor nate vinte'`).
2. A pessoa tem `JANELA_COMANDO_SEGUNDO` (5s) pra começar a falar. Depois
   que começou, `SILENCIO_FIM_COMANDO_SEGUNDO` (1s, pra caber respiração em rolagem longa) de silêncio fecha a
   rolagem — sem esperar o resto da janela. Teto de 10s. Quem mede isso é a
   vigia (`_vigiar`), porque sem fala o Discord para de mandar pacote.
   "Começou a falar" = pacote com energia de voz (`tem_voz`), senão o rabo
   silencioso do "por favor" fecharia a janela na hora.
3. `normalizar_comando_dado()` converte o texto do Vosk pro formato do Dice.
   Não é rolagem completa → "👂 não entendi a rolagem (ouvi: ...)"; janela
   passou calada → "👂 não ouvi nenhuma rolagem". Nos dois casos volta pro
   modo senha.

### Como chega no Dice sem o Echo importar nada dele

O Echo posta `🎙️ rolo 1d20+5 com vantagem` no canal, e o `on_message` do
Dice reage como se alguém tivesse digitado. Mas o Dice ignorava mensagem de
bot — inclusive da própria Natty. A solução: o Dice aceita mensagem **da
própria Natty que comece com 🎙** (`MARCADOR_VOZ` no cog do Dice). É uma
convenção de texto: nenhum módulo importa o outro. As respostas do Dice
começam com 🎲/🪙/❌, então não há laço; e as mensagens do Echo que não são
rolagem usam 👂.

**O nome de quem rolou nunca vai no texto da rolagem**: o Dice lê a
mensagem inteira, e procura "vantagem" até pelas abreviações (`vant`, `adv`,
`dis`) — um apelido "Dis" viraria desvantagem. Por isso a rolagem é postada
como **resposta** ao "👂 fala a rolagem, Fulano!": o nome aparece no
encadeamento, e o Dice só vê `🎙️ rolo ...`.

### O que entende: tudo que o Dice entende por texto

| Recurso | Falado | Vira |
|---|---|---|
| Dado + bônus | "dado vinte mais cinco" | `rolo 1d20+5` |
| Vários dados | "dado vinte mais dado seis mais três" | `rolo 1d20+1d6+3` |
| Vantagem | "dado vinte com vantagem" / "desvantagem" | `com vantagem` |
| CD | "contra quinze", "dificuldade dezoito", "cd quinze" | `contra 15` |
| Explosivo | "dois dados seis explosivo" | `2d6!` |
| Tirar menores | "quatro dados seis tirando o menor", "tiro os dois menores" | `tiro 1`, `tiro 2` |
| Manter maiores | "mantendo os três maiores", "mantenho o maior" | `mantenho 3`, `mantenho 1` |
| Teste por dado | "dez dados oito maior que cinco", "maior ou igual a dez", "menor que três", "igual a seis" | `maior que 5` etc. |
| Reroll | "dado oito se oito rola de novo", "se cair vinte rola dado cem", "se o dado seis der seis rola dado oito" | `se 8 role de novo` etc. |
| Moedas | "três moedas", "moeda setenta por cento de cara" | `rolo 3 moedas`, `70% de cara` |
| Moeda condicional | "três moedas se duas caras rola dado seis mais dois" | `se 2 caras role 1d6+2` |
| Nome do teste | "teste de ataque, dado vinte mais sete" (no começo ou no fim) | `teste de ataque: rolo 1d20+7` |

Tudo combina: "teste de ataque, rola dado vinte mais cinco com vantagem
contra quinze se vinte rola dado oito" → `teste de ataque: rolo 1d20+5 com
vantagem contra 15 se 20 role 1d8`. Os complementos vêm em qualquer ordem
depois dos dados, inclusive bônus ("dado vinte com vantagem mais dois").

**O parser é estrito de propósito** (`normalizar_comando_dado`): se sobrar
qualquer palavra que não faça parte de uma rolagem, ou um complemento
incompleto ("contra" sem número, "se oito" sem o que rolar), a resposta é
"👂 não entendi a rolagem" — melhor que rolar a coisa errada. Cada recurso
tem teste ponta a ponta contra o `roll()`/`roll_coins()` real do Dice,
conferindo o efeito (CD, filtro, operador, gatilho do reroll, peso da
moeda...), não só que o Dice aceitou.

Detalhes que vieram de teste com o Vosk:

- **Fala-se "dado vinte", não "um dê vinte".** A primeira versão usava a
  letra, e em call real o "dê" nunca chegou no texto: "rola um dê vinte"
  saiu `rola vinte`, e o resto saiu só `vinte`, `vinte um`, `oito`. A
  palavra existe no vocabulário do modelo, mas uma letra sozinha (~100ms) é
  curta demais pra ele ouvir. "dado" é palavra comum e é como a mesa fala.
- "dado" e "dados" valem com qualquer quantidade: "dois dados seis" sai
  `dois dado seis`.
- **"três" é ouvido como "treze"** ("três moedas" saiu `treze moedas`,
  "os três maiores" saiu `os treze maiores`). Em posição de **quantidade**
  (dados, moedas, quantos tirar/manter, quantas caras) 13 vira 3 — 13 dados
  é bem menos provável. Em CD, bônus e teste por dado, 13 continua 13.
- **O "e" do número some às vezes**: "contra vinte e dois" saiu `contra
  vinte dois`. Dezena + unidade junta com ou sem o "e" ("vinte e cinco" =
  "vinte cinco" = 25).
- Com "dado" no lugar do "dê", "dezesseis/dezessete/dezoito/dezenove"
  voltaram pro vocabulário (antes soavam como "dê seis/dê sete..." e
  estragavam o tamanho do dado) — "contra dezesseis/dezoito" e "mais treze"
  saíram certos.
- Tamanhos aceitos: d2, d3, d4, d6, d8, d10, d12, d20, d100 ("cem"). Lista
  fechada de propósito: "dado vinte e cinco" é mais provável ser erro que d25.
- Perícias pro nome do teste: as de D&D 5e que existem no vocabulário do
  modelo, mais ataque, iniciativa, dano, resistência e morte. **Arcanismo e
  furtividade não existem** no modelo.
- Teste com voz sintética: 23 de 23 frases (todos os recursos) saíram com o
  resultado certo. Falta validar com voz real os recursos novos.

### Fica pra depois

- Senha e rolagem de uma vez só ("NAT20, por favor, dado vinte"): hoje
  precisa de uma pausa depois da senha. A grammar da senha não tem as
  palavras de dado, então a frase emendada vira `[unk]`.
- Explosivo múltiplo (`!!`, `!!!`) e filtro colado tipo `kh3` — o explosivo
  falado é sempre `!`.
- Arcanismo e furtividade (fora do vocabulário do modelo).

## Por que não tem LLM em lugar nenhum

Todo o pipeline é regra fixa, sem custo de API:

1. **Captura de áudio**: `discord-ext-voice-recv` — extensão sobre o
   `discord.py` que já está no projeto (não troca nada do que existe).
2. **Detecção da senha**: Vosk local com grammar restrita + regex
   (`tem_wake_word`).
3. **Rolagem falada**: Vosk com o vocabulário de dados + normalização por
   regra (`normalizar_comando_dado`).
4. **Interpretação da rolagem**: o próprio Dice, pelo texto postado.
5. **Transcrição livre (futuro)**: Whisper local (`openai-whisper`, modelo
   `base`, ~140MB) — já pronto no `service.py`, não usado pelo cog.

## O que acontece com o que é falado na call

Com o Vosk e a grammar restrita, **nada do que é falado vira texto livre**:
ele só consegue devolver as frases da lista (a senha) ou `[unk]`. Conversa
normal da mesa vira `[unk]` e é descartada na hora — não é transcrita, não
é logada, não é guardada. No modo comando (só depois da senha, por poucos
segundos, só de quem falou a senha) o vocabulário é o de dados. (Com o Whisper, tudo era transcrito e só depois
filtrado.) Um futuro módulo de transcrição de sessão inteira precisaria
ligar o Whisper de propósito — ver `claude/NAT-Listing-Design.md` no
projeto pra essa discussão.

## Pendências (lista única, atualizada em 02/10/2026)

**Validar em call:**
- Escutar só o dono da sessão, com mais gente falando na sala.
- Reroll ("dado oito se oito rola de novo") depois da correção do corte na
  respiração; moedas; nome do teste.

**Melhorar:**
- **Senha dentro da janela de música:** enquanto o pedido de música está
  sendo gravado, tudo vai pro Whisper — um "NAT20, por favor, para" falado
  ali virou o pedido `Nativante para` (call real, 02/10/2026). Ideia: se o
  texto transcrito começar com algo parecido com a senha, descartar e
  avisar em vez de mandar pro Bardo.
- **Volume do Bardo por voz** ("NAT20, por favor, aumenta/abaixa"): o resto
  dos controles (próxima, repete, pausa, continua, pare) já funciona; volume
  ficou de fora. Mesmo caminho: palavra na grammar da senha → `🎙️ natty …`.
- Pedido de música: Whisper `base` erra nomes próprios; com o idioma
  detectado (02/10/2026), nome em inglês saiu certo, mas palavra única pode
  cair em outra língua ("Garçom" → `Garçon`). Primeiro pedido da sessão
  ainda leva 28-46s (modelo carregando na hora). Opções: carregar o Whisper
  no "escuta", prioridade normal do processo, e o faster-whisper `small`
  da branch `echo-transcricao` (acertou "grão de areia" e "Clube da
  esquina" em ~3s).
- Transcrição de sessão: pronta na branch `echo-transcricao` (no GitHub),
  esperando teste em call com a rede estável — o primeiro teste caiu numa
  manhã de rede instável.
- Senha e comando numa frase só ("NAT20, por favor, dado vinte"): hoje
  precisa de uma pausa depois da senha (a grammar da senha não tem as
  palavras de dado).

**Calibrar:**
- `PALAVRAS_PARECIDAS_COM_NAT` com outras vozes/sotaques da mesa — só uma
  voz foi testada até agora (ela caiu em "nate").
- Fim de frase do Vosk: se a pessoa emendar "NAT20, por favor" no meio de
  uma fala longa sem pausa, a frase inteira pode virar `[unk]`.
- Uso de CPU/RAM com o bot inteiro em call real: medido só offline (~2-3%
  do tempo de fala).

**Remendo temporário:** `dave.py` sai quando o PR #54 do
discord-ext-voice-recv for publicado no PyPI (ver "Criptografia DAVE").

## Como ativar

Já está em `MODULOS_ATIVOS` no `bot.py`. Numa máquina nova:

1. `pip install -r requirements.txt` no `.venv` (traz `vosk`,
   `openai-whisper` e `discord-ext-voice-recv`; esse último só publica
   pré-release no PyPI, então o pin no requirements.txt já cuida disso).
2. **Baixar o modelo do Vosk à mão** (não vai pro git — 31MB em muitos
   arquivos pequenos): em [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models),
   baixar o `vosk-model-small-pt-0.3.zip` e extrair em `modules/echo/assets/`,
   ficando `modules/echo/assets/vosk-model-small-pt-0.3/final.mdl` etc.
   Sem ele, "@Natty escuta" responde dizendo o que falta.
3. No Discord, entra num canal de voz e manda `@Natty escuta` no texto
   (vale a menção ao usuário ou ao cargo @Natty).
4. Fala **"NAT20, por favor"** (a frase toda, com uma pausinha depois) em
   algum momento da call — ela responde "👂 fala a rolagem". Aí fala a
   rolagem ("dado vinte mais cinco"), e ela posta pro Dice rolar.
5. Pra ela sair, fala **"NAT20, por favor, saia"** na call, ou manda
   `@Natty, tampe os ouvidos` no texto (aceita tampe/tampa/tapa/tampem,
   ouvido/ouvidos).

## Rodando os testes

```bash
python -m unittest discover -s modules/echo -t .
```

Não precisa de internet nem de modelo baixado — os testes trocam o Whisper
(`ModeloFalso`) e o `KaldiRecognizer` do Vosk (`ReconhecedorFalso`) por
dublês (mesma técnica do `test_service.py` do Dice com o RNG falso). Um
teste garante que toda frase da grammar passa na regex da senha, e que o
que o Vosk devolve pra fala fora da lista (`[unk] vinte por favor`,
`vinte por favor`) não passa.
`test_dave.py` testa o remendo DAVE com uma sessão falsa (decifrar,
descobrir dono pela chave, SSRC reaproveitado, falhas virando silêncio).

No Windows, um `NamedTemporaryFile` aberto não pode ser reaberto por outro
processo (wave/ffmpeg): `transcrever_pcm` usa `delete=False` + limpeza
manual, e os testes usam `delete_on_close=False` + `f.close()`.

## API principal

```python
from modules.echo import service

# Detecção da senha em streaming (usado pelo cog.py)
rec = service._criar_reconhecedor_vosk()             # um por pessoa
pcm16 = service.resample_para_16k_mono(pacote_discord)
texto = service.processar_chunk_vosk(rec, pcm16)     # None até a frase acabar
if texto and service.tem_wake_word(texto): ...

# Modo comando (rolagem falada)
cmd = service._criar_reconhecedor_comando_vosk()
service.normalizar_comando_dado("rola dado vinte mais cinco")  # "rolo 1d20+5"
service.finalizar_vosk(cmd)                                    # força o fim da frase

from modules.echo import reconhecer, transcrever, transcrever_pcm, tem_wake_word, extrair_comando

# Transcrição livre com Whisper (não usada pelo cog hoje; pronta pro comando depois da senha)
r = reconhecer("trecho.wav")
r.chamou_natty  # bool
r.comando       # "rola 1d20" ou None

# Peças soltas, se algum módulo futuro precisar só de uma parte
tem_wake_word("NAT20, por favor, toca Garçom")       # True
extrair_comando("NAT20, por favor, toca Garçom")     # "toca Garçom"
transcrever("arquivo.wav").texto                     # transcrição crua, sem filtro
```
