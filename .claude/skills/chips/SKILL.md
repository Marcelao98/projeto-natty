---
name: chips
description: Adiciona uma franquia (playlist do YouTube) ao dataset de músicas do Bardo — extrai, tagueia os temas de cada faixa, mescla no musicas.json e testa. Usar quando pedirem pra colocar trilha de um jogo/anime/filme novo no Bardo, ou pra classificar faixas "não classificado" que já estão no dataset.
---

# chips — nova franquia no dataset do Bardo

Pipeline em quatro passos. Uma franquia = um arquivo de staging = um
pipeline; não misturar franquias no mesmo staging. `staging/` está no
`.gitignore` — só o `modules/bardo/dataset/musicas.json` vai pro commit.

## 1. Extrair

```
python scripts/bardo_extrair_playlist.py "<url da playlist>" \
    --origem-nome "Hollow Knight" --origem-tipo jogo \
    --saida staging/hollow_knight.json
```

- Aceita URL de playlist ou de vídeo com `&list=`. Precisa do `yt_dlp`
  (`python -m yt_dlp --version`; o executável `yt-dlp` pode não estar no PATH).
- Antes, confira que a playlist é a certa:
  `python -m yt_dlp --flat-playlist --print "%(playlist_title)s" -I 1 "<url>"`.
- O script limpa o título do YouTube ("<Jogo> OST - ", "01 ", "【Audio】",
  "(... Original Soundtrack)") e gera o `id` como `<origem>-<nome>` em slug.
  Confira os nomes no staging; ajuste à mão o que ficou estranho.
- Toda faixa sai com `"temas": ["não classificado"]`.

## 2. Tagueiar

Trocar `["não classificado"]` por **2 a 5 temas** por faixa.

- **Reusar o vocabulário existente**, nunca inventar sinônimo. Ver os temas
  em uso (com contagem):

  ```
  python -c "import json,collections;d=json.load(open('modules/bardo/dataset/musicas.json',encoding='utf-8'));print(collections.Counter(t for m in d['musicas'] for t in m['temas']).most_common())"
  ```

  As categorias de busca (`triste`, `chefe`, `masmorra`...) saem dos temas
  via `modules/bardo/dataset/vocabulario.json` — um tema que já está lá ou
  no dataset é o que faz a faixa aparecer nas buscas.
- **Contexto de jogo conta tanto quanto clima**: onde a faixa toca
  (`boss fight`, `hub`, `exploração`, `masmorra`, `cidade`, `menu`,
  `final`, `descanso`) é o que o mestre pede na mesa.
- `vocal` quando a faixa tem voz; `final` pra créditos/finais.
- **Nome não-óbvio → pesquisar** onde a faixa toca antes de tagueiar
  (wiki da franquia, lista de uso do OST). Sem fonte confiável, deixa
  `["não classificado"]` — tag chutada polui a busca mais que faixa sem tag.
- Pra conferir que nenhum tema é novo, compare contra o snippet acima
  (normalizando acento/maiúscula).
- `escopo`: quase sempre `"faixa_individual"`. `"album_completo"` só pra
  uma entrada única que representa o álbum inteiro (raro — a ideia do
  dataset é granularidade por faixa).
- `comentario_pessoal`: fica `""`. É a opinião do mestre sobre a faixa, não
  descrição gerada; só preencher se ele disser algo sobre aquela faixa.

## 3. Mesclar

```
python scripts/bardo_mesclar_dataset.py staging/<franquia>.json --dry-run
python scripts/bardo_mesclar_dataset.py staging/<franquia>.json
```

- O dry-run mostra quantas entram, quais são duplicadas e quais ficaram
  `não classificado`. Conferir a contagem antes de rodar de verdade.
- Duplicada = mesmo vídeo, mesmo `id`, ou mesmo nome na mesma origem (a
  faixa pode já estar no dataset com outro upload). Essas são puladas.
- As `categorias` das faixas novas são preenchidas pelo vocabulário. Se
  mexer no `vocabulario.json` depois, rodar `python scripts/categorizar_musicas.py`.

## Reclassificar faixas "não classificado" que já estão no dataset

Não precisa do pipeline: editar o `temas` da faixa direto no
`musicas.json` (achar pelo `id` ou `nome`), com as mesmas regras do passo 2
(reusar vocabulário, sem fonte não chuta). Depois rodar
`python scripts/categorizar_musicas.py` pra atualizar as categorias.

## 4. Testar e commitar

```
python -m unittest discover -s modules/bardo -t .
```

Commitar só o `musicas.json` (e os scripts, se mudaram). Antes, `git status`
pra confirmar que `.env` e `credentials.json` não estão staged. Depois do
merge, reiniciar a Natty (`scripts/reiniciar_natty.ps1`) pra ela recarregar
o dataset.

## No final

Fechar explicando em português o que entrou e por quê: quantas faixas por
franquia, as decisões de tagueamento (por que essa tag, de onde veio a
fonte) e, separado, a lista das que ficaram `não classificado` e o motivo.
Essas dependem da memória/opinião do mestre — wiki raramente documenta
clima faixa a faixa.
