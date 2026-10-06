# Módulo Dice

Rolagem de dados em linguagem natural: a Natty lê o chat e responde quando alguém rola, e também tem o comando `/rolar`. Não depende de nada além da stdlib (`random`, `re`).

## Arquivos

| Arquivo | Papel |
|---|---|
| `service.py` | Lógica pura: `roll(texto)` interpreta e rola. Sem discord.py. |
| `conditional_rerolls.py` | Rerolls condicionais ("se 8 role de novo"): parse e aplicação. Sem discord.py. |
| `coins.py` | Moedas: `flip_coin()`, moeda ponderada e parse do condicional ("se cara role 1d20"). Sem discord.py. |
| `detector.py` | Decide se uma mensagem do chat é um pedido de rolagem. |
| `format.py` | Transforma o `RollResult` em texto para o Discord. |
| `cog.py` | Listener de mensagens e comando `/rolar`. Só traduz e chama o serviço. |
| `test_*.py` | Testes (`unittest`). |

## No Discord

**Automático, no chat.** A Natty rola quando:

- a mensagem tem dados **e** uma palavra de rolagem (`rolo`, `rola`, `rolar`, `rolando`, `rolei`, `rolou`, `roll`, `teste`): "eu rolo 1d20+5", "Teste de Ataque: 1d20+5 vs CD 13";
- ou a mensagem é **só** a rolagem: "1d20", "2d6+3 com vantagem vs 15".

Ela **não** rola quando:

- os dados aparecem soltos numa frase: "a espada dá 1d8 de dano";
- a mensagem começa com `!` (comando do Avrae, que já rola sozinho);
- quem escreveu é um bot (a própria Natty, o Avrae etc.).

**Comando.** `/rolar dados:1d20+5 com vantagem vs 15`. Os erros aparecem só para quem rolou.

**Resposta:**

```
🎲 Ataque: 1d20 [~~4~~, 17] + 5 (vantagem) = **22** · CD 15 ✅ Sucesso
```

O d20 descartado pela vantagem ou desvantagem aparece riscado.

## O que o `roll()` entende

| Item | Exemplos | Regra |
|---|---|---|
| Dados | `1d20`, `d20`, `2d6+3d8`, `1d20-1d4` | Sem quantidade vale 1. Termos repetidos (`1d20+1d20`) somam normalmente. |
| Explosivo / filtro | `1d6!`, `4d6t1`, `4d6 mantenho 3` | Ver [Explosivos e tira/mantém](#explosivos-e-tiramantém). |
| Bônus | `+5`, `-2` | Soma os números fixos da expressão. Pode ser negativo. |
| Vantagem | `vantagem`, `vant`, `advantage`, `adv` | Rola 2d20 e fica com o maior. |
| Desvantagem | `desvantagem`, `desvant`, `disadvantage`, `dis` | Rola 2d20 e fica com o menor. |
| CD | `vs 15`, `contra 15`, `dc 15`, `cd 15`, `vs DC 15` | Compara o total: `total >= CD` é sucesso. |
| Teste | `Teste de Ataque`, `teste destreza` | Só aparece como título na resposta. |

Regras de D&D aplicadas:

- A vantagem ou desvantagem vale só para o **primeiro `1d20`** da expressão. Se a rolagem não tem `1d20`, ela é ignorada e a resposta avisa.
- "sem vantagem" e "sem desvantagem" não ativam o modificador.
- **Crítico:** se o d20 que ficou (depois da vantagem ou desvantagem) é 20 natural e há CD, o resultado é `crítico`, seja qual for o total. Na desvantagem, isso só acontece se os dois dados derem 20.
- Sem CD, o resultado não é avaliado (`resultado = None`).

**Limites.** Quem passa deles recebe um erro em vez da rolagem. Eles existem porque uma rolagem gigante travaria o processo e derrubaria o NAT-CORE junto.

| Limite | Valor |
|---|---|
| Dados por rolagem | 100 (`MAX_DADOS`) |
| Lados por dado | 1000 (`MAX_LADOS`) |
| Termos na expressão | 20 (`MAX_TERMOS`) |

Com esses limites, a maior resposta possível ainda cabe numa mensagem do Discord (2000 caracteres).

## Explosivos e tira/mantém

| Mensagem | Efeito |
|---|---|
| `rolo 1d6!` | Se cair 6, rola mais 1d6 e soma. |
| `rolo 2d10!!` | Cada dado pode explodir até 2 vezes em cadeia (`!!!` = 3). |
| `rolo 4d6 tiro 1`, `4d6t1`, `4d6 tiro o menor` | Tira o menor. |
| `rolo 4d6t2`, `4d6 tiro os 2 menores` | Tira os 2 menores. |
| `rolo 4d6 mantenho 3`, `4d6m3`, `4d6kh3`, `4d6k3` | Mantém os 3 maiores. |
| `rolo 4d6! tiro 1`, `4d6!t1`, `2d10!!kh1` | Combina: explode primeiro, depois filtra. |

Regras:

- O `!` colado no dado **sempre** explode: "rolo 1d20!" é um d20 explosivo (explode no 20), não pontuação.
- O número de `!` é o limite de explosões **por dado**, em cadeia: em `1d6!` um 6 rola mais um dado, mas se esse também der 6 para aí.
- Ordem em cada dado: rola → vantagem (só no 1d20) → explode → tira/mantém. As explosões entram no conjunto que é filtrado.
- "tiro N" / "mantenho N" por extenso valem para o **último** dado da expressão (`1d20+4d6 tiro 1` filtra o 4d6). Sem número depois ("o dano do tiro"), não filtra nada.
- Tem que sobrar pelo menos 1 dado: `4d6t4`, `1d6 tiro 1` e `4d6m5` dão erro.
- Vantagem continua valendo só para o 1d20. `8d6 tiro 2 com vantagem` rola normalmente e avisa que a vantagem foi ignorada.
- O limite de 100 dados conta o pior caso das explosões: `40d6!!` pode virar 120 dados e dá erro antes de rolar.
- O reroll condicional ("se 6 role de novo") olha só os dados que contam: os tirados pelo filtro não ativam, as explosões ativam.

```
🎲 4d6!t1 [4, 6, 5, 3, ~~💥2~~] = **18**
```

💥 marca os dados que vieram de explosão, e os riscados são os tirados pelo filtro (ou o d20 descartado pela vantagem). No `Termo`: `explosoes`, `filtro` (`"t"`/`"m"`), `filtro_qtd`, `removidos` e `mantidos`.

## Teste por dado (sucessos)

Compara **cada dado** com um valor e mostra quais passaram:

| Mensagem | Sucesso quando o dado é |
|---|---|
| `rolo 10d8, maior que 5`, `10d8 > 5` | > 5 |
| `rolo 10d8, menor que 3`, `< 3` | < 3 |
| `rolo 20d6, igual a 6`, `= 6` | = 6 |
| `rolo 15d20, maior ou igual 10`, `>= 10`, `≥ 10` | ≥ 10 |
| `rolo 5d20, menor ou igual a 4`, `<= 4`, `≤ 4` | ≤ 4 |

```
🎲 10d8 [3, 6, 2, 8, 4, 7, 5, 1, 8, 6] · maior que 5
✅ Sucessos (>5): [6, 8, 7, 8, 6]
❌ Falhas (≤5): [3, 2, 4, 5, 1]
📊 **5 sucessos de 10** (50%)
```

Regras:

- Entra no fim da ordem: rola → vantagem → explode → tira/mantém → teste. Conta só os dados mantidos (as explosões entram, os tirados e o d20 descartado não).
- Os bônus fixos (`+5`) não entram no teste, porque ele compara dado por dado. A resposta avisa.
- A condição tem que vir **depois** dos dados; assim, uma menção (`<@123>`) antes deles não vira "< 123".
- Com mais de 20 dados (`MAX_LISTA_LIMIAR`), a resposta mostra só a contagem. Os dados continuam na primeira linha.
- Dá pra combinar com CD: `rolo 2d6 > 3 vs 8` mostra a contagem e também o total contra a CD.
- No resultado: `r.threshold` (`ThresholdTest`: `operador`, `valor`, `dados`, `sucessos`, `falhas`, `success_count`, `failure_count`, `percentual`), ou `None`.

## Rerolls condicionais

O jogador pode pedir um reroll na própria mensagem:

| Mensagem | Efeito |
|---|---|
| `rolo 1d8 se 8 role de novo` | Se cair 8, rola mais 1d8. |
| `rolo 1d20 se 20 role 1d100` | Se cair 20, rola 1d100. |
| `rolo 2d6 se 6 role de novo` | Se **algum** d6 der 6, rola mais 1d6. |
| `rolo 1d20+1d6 se o d6 der 6 role 1d8` | Só checa os d6. |
| `rolo 1d20 com vantagem se 20 role de novo` | Combina com vantagem/desvantagem. |

Regras:

- Aceita `role`/`rola`/`rolo`/`rerola` e `de novo`/`novamente`/`outra vez`.
- "De novo" repete **um** dado igual ao que ativou (ex: `2d6` → `1d6`). Uma notação (`1d100`, `2d6`) rola exatamente aquilo.
- Ativa **uma vez só**, sem cascata: se o reroll também cair no gatilho, não rola de novo.
- Com vantagem/desvantagem, só o d20 que ficou conta; o descartado não ativa.
- O reroll soma no total **antes** da CD, e conta nos limites de dados/lados.

```
🎲 1d20 [20] + ✨ 1d100 [67] = **87**
-# ✨ Reroll ativado (20)
```

Uso direto: `roll(texto, conditional_reroll=parse_conditional_reroll(texto))`. O resultado fica em `r.conditional_reroll_result` (`RerollResult`, ou `None` se não ativou).

## Moedas

| Mensagem | Efeito |
|---|---|
| `rolo uma moeda`, `jogo a moeda`, `moeda` | Cara ou Coroa. |
| `rolo 5 moedas` | 5 resultados + contagem de caras e coroas. |
| `moeda ponderada 70% cara`, `3 moedas com 25% de cara` | Cada moeda dá cara com essa chance. |
| `rolo moeda se cara role 1d20` | Se der cara, rola 1d20. |
| `rolo 3 moedas se 2 caras role 1d100` | Se der **pelo menos** 2 caras, rola 1d100. |
| `rolo moeda se cara role 1d20+5 com vantagem vs 15` | A rolagem depois de "role" aceita tudo que o `roll()` aceita. |

Regras:

- A Natty só joga moedas quando a mensagem **começa** com a moeda (`moeda 70% cara`, `2 moedas se 2 caras role 1d6`) ou quando ela vem logo depois de um verbo (`rolo`, `jogo`, `lanço`, `tiro`, `flip`...). "Comprei uma moeda" não joga nada.
- Se a mensagem tem dados fora do condicional ("rolo 1d20 e perco uma moeda"), quem rola são os dados.
- Quantidade: número ou `um`/`uma`/`dois`/`duas`/`três`. Sem quantidade vale 1. Máximo de 100 moedas (`MAX_MOEDAS`).
- O condicional é checado **antes** de jogar: pedir mais caras do que moedas ("rolo moeda se 2 caras...") ou uma rolagem inválida dá erro sempre, não só quando cai cara.

```
🪙 2 moedas = [Cara, Coroa]
**1 cara** · 1 coroa
❌ Condição não ativada (1 cara, precisava 2)
```

Uso direto: `roll_coins(extract_coin_pattern(texto), extract_coin_conditional(texto))` retorna um `CoinRollResult` (`flip`, `target_heads`, `reroll`), e o `reroll` é o `RollResult` da rolagem, ou `None` se não ativou. Para jogar só as moedas: `flip_coin(3, bias=0.7)`.

## Uso por outros módulos

```python
from modules.dice import roll, describe_roll_compact

r = roll("Eu rolo 1d20+1d6, Teste de Ataque vs DC 12")
r.final       # total
r.natural     # valor do d20 usado (ou None)
r.resultado   # "sucesso" | "falha" | "crítico" | None
r.termos      # lista de Termo(expressao, sinal, rolagens, descartado, subtotal)
describe_roll_compact(r)
```

O `roll()` recebe a frase inteira: acha a expressão, o modificador, a CD e o teste sozinho. Ele levanta `ValueError`, com uma mensagem pronta para mostrar ao jogador, quando não encontra dados ou quando a rolagem passa dos limites. Para testes, passe um `rng` próprio: `roll("1d20", rng=random.Random(42))`.

## Rolagem falada (mensagens da própria Natty com 🎙)

O listener ignora mensagens de bots (Avrae, a própria Natty), para não rolar em cima das respostas deles. A exceção: mensagem **da própria Natty** que começa com 🎙 (`MARCADOR_VOZ` no `cog.py`). É assim que a rolagem falada numa call chega aqui: o módulo Echo converte a fala em texto (`🎙️ rolo 1d20+5 com vantagem`), posta no canal e o Dice rola normalmente. Nenhum dos dois importa o outro; é só essa convenção de texto. As respostas do Dice começam com 🎲, 🪙 ou ❌, então ele nunca reage a si mesmo. Ver `modules/echo/README.md`, seção "Rolagem falada".

## Requisito: Message Content Intent

O listener precisa ler o texto das mensagens. Por isso o `bot.py` liga `intents.message_content`, e a opção **Message Content Intent** precisa estar ligada no [Discord Developer Portal](https://discord.com/developers/applications) (aplicação da Natty → Bot → Privileged Gateway Intents). Se ela estiver desligada no portal, o bot **não conecta** (`PrivilegedIntentsRequired`).

## Testes

Da raiz do projeto:

```
python -m unittest discover -s modules/dice -t .
```

Os testes usam um rng falso com valores fixos, então verificam resultados exatos (vantagem, CD, crítico, formatação).
