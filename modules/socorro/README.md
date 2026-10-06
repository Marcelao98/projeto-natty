# Módulo Socorro

A Natty se apresenta e explica, em versão curta, o que cada módulo faz.

## No Discord

| Pedido | Resposta |
|---|---|
| `@Natty socorro`, `@Natty ajuda`, `/socorro` | Apresentação e lista dos módulos |
| `@Natty socorro dice` (ou `dados`, `rolagem`), `/socorro modulo:dice` | Mini-guia do Dice |
| `@Natty socorro bardo` (ou `música`), `/socorro modulo:bardo` | Mini-guia do Bardo |
| `@Natty socorro core` (ou `personagens`, `registrar`, `ficha`), `/socorro modulo:core` | Mini-guia do Core |
| `@Natty socorro voz` (ou `echo`, `call`, `escuta`, `nat20`), `/socorro modulo:voz` | Mini-guia dos comandos falados (módulo Echo) |

A palavra de ajuda (`socorro`, `ajuda`, `help`, `comandos`) tem que vir logo
depois da menção: "@Natty toca isso, socorro" não é pedido de ajuda. A menção
tem que ser de verdade (@Natty ou o cargo) — "natty socorro" só escrito não
chama mais a Natty (desde 02/10/2026).

## Arquivos

| Arquivo | Papel |
|---|---|
| `service.py` | Textos de ajuda e `interpretar_pedido()`. Sem discord.py. |
| `cog.py` | Listener do chat e `/socorro`. |
| `test_service.py` | Testes (`python -m unittest discover -s modules/socorro -t .`). |

## Manutenção

Os textos de cada módulo ficam em `service.py` e **não** são gerados a partir
dos outros módulos. Quando Dice, Bardo, Core ou Echo (voz) ganharem ou
perderem comandos, atualize o texto correspondente. O tópico do Echo se chama
"voz", não "echo", porque é assim que a mesa pensa nele. Módulo novo: adicione um apelido em
`_APELIDOS`, um texto em `_TEXTOS`, uma linha no `_GERAL` e a opção no
`/socorro` do `cog.py`.
