"use strict";
// Mesa de som do painel: pads de efeito, ambientes com volume, músicas
// enviadas, cenas, volume geral, ducking, upload e pré-escuta.
// Usa comando(), el(), avisar(), estado e guildAtual do app.js.

let sons = [], cenas = [], ultimaColecao = null;

async function carregarSons() {
  const r = await comando("sons");
  sons = (r && r.ok && r.dados) || [];
  const c = await comando("cenas");
  cenas = (c && c.ok && c.dados) || [];
  desenharMixer();
}

function botaoOuvir(som) {
  return el("button", { type: "button", className: "discreto", textContent: "🎧", title: "Ouvir aqui (só pra você)",
    dataset: { acao: "ouvir", nome: som.nome } });
}

function desenharMixer() {
  if (!estado) return;
  const mx = estado.mixer || { master: 100, ducking: 60, ambientes: [] };
  for (const [id, valor] of [["master", mx.master], ["ducking", mx.ducking]]) {
    if (document.activeElement !== $(id)) $(id).value = valor;
    $(`${id}-num`).textContent = `${valor}%`;
  }
  const ligados = new Map(mx.ambientes.map((a) => [a.som, a]));

  const efeitos = sons.filter((s) => s.tipo === "efeito");
  $("pads").replaceChildren(...(efeitos.length ? efeitos.map((s, i) => el("button",
    { type: "button", className: "pad", title: `Disparar ${s.nome}`, dataset: { acao: "pad", nome: s.nome } },
    el("span", { className: "tecla", textContent: i < 9 ? String(i + 1) : "" }),
    el("span", { textContent: s.nome }))) : [el("p", { className: "vazio", textContent: "Nenhum efeito. Envia um aí embaixo." })]));

  const ambientes = sons.filter((s) => s.tipo === "ambiente");
  $("ambientes").replaceChildren(...(ambientes.length ? ambientes.map((s) => {
    const ligado = ligados.get(s.nome_chave);
    const volume = ligado ? ligado.volume : s.volume;
    return el("li", { className: ligado ? "ambiente-ligado" : "" },
      el("button", { type: "button", className: ligado ? "ligado" : "", textContent: ligado ? "■" : "▶",
        title: ligado ? "Desligar" : "Ligar", dataset: { acao: ligado ? "ambiente-off" : "ambiente-on", nome: s.nome } }),
      el("span", { className: "nome", textContent: s.nome }),
      el("input", { type: "range", min: 0, max: 100, step: 5, value: volume, title: "Volume",
        dataset: { acao: "som-volume", nome: s.nome } }),
      botaoOuvir(s));
  }) : [el("li", { className: "vazio", textContent: "Nenhum ambiente guardado." })]));

  const musicas = sons.filter((s) => s.tipo === "musica");
  $("musicas-enviadas").replaceChildren(...(musicas.length ? musicas.map((s) => el("li", {},
    el("button", { type: "button", textContent: "＋ fila", dataset: { acao: "pad", nome: s.nome } }),
    el("span", { className: "nome", textContent: s.nome }),
    botaoOuvir(s))) : [el("li", { className: "vazio", textContent: "Nenhuma música enviada." })]));

  $("cenas").replaceChildren(...(cenas.length ? cenas.map((c) => el("li", {},
    el("button", { type: "button", textContent: "▶ aplicar", dataset: { acao: "cena", nome: c.nome } }),
    el("span", { className: "nome", textContent: c.nome }),
    el("button", { type: "button", className: "discreto", textContent: "✕", title: "Apagar cena",
      dataset: { acao: "cena-apagar", nome: c.nome } }))) : [el("li", { className: "vazio", textContent: "Nenhuma cena salva." })]));
}

function piscar(botao) {
  botao.classList.add("disparou");
  setTimeout(() => botao.classList.remove("disparou"), 250);
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-acao]");
  if (!b || b.tagName === "INPUT") return;
  const { acao, nome } = b.dataset;
  if (acao === "pad") { piscar(b); return comando("som_tocar", { nome }); }
  if (acao === "ambiente-on") return comando("som_tocar", { nome });
  if (acao === "ambiente-off") return comando("som_parar", { nome });
  if (acao === "ambientes-off") return comando("som_parar", {});
  if (acao === "cena") return comando("cena_aplicar", { nome });
  if (acao === "cena-apagar") {
    if (!confirm(`Apagar a cena ${nome}?`)) return;
    await comando("cena_apagar", { nome });
    return carregarSons();
  }
  if (acao === "ouvir") {
    const audio = $("pre-escuta");
    const url = `/api/g/${encodeURIComponent(guildAtual)}/ouvir?nome=${encodeURIComponent(nome)}`;
    if (!audio.paused && audio.dataset.nome === nome) { audio.pause(); return; }
    audio.src = url; audio.dataset.nome = nome;
    audio.play().catch(() => avisar("Não deu pra tocar aqui no navegador.", true));
  }
});

const temporizadores = {};
function depois(chave, fn, ms = 150) { clearTimeout(temporizadores[chave]); temporizadores[chave] = setTimeout(fn, ms); }

document.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.id === "master" || t.id === "ducking") {
    $(`${t.id}-num`).textContent = `${t.value}%`;
    depois(t.id, () => comando(t.id, { nivel: Number(t.value) }));
  } else if (t.dataset.acao === "som-volume") {
    depois(`v:${t.dataset.nome}`, () => comando("som_volume", { nome: t.dataset.nome, nivel: Number(t.value) }));
  }
});

document.addEventListener("keydown", (ev) => {
  if (!podeControlar || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (!/^[1-9]$/.test(ev.key)) return;
  const pad = document.querySelectorAll("#pads .pad")[Number(ev.key) - 1];
  if (pad) { ev.preventDefault(); pad.click(); }
});

document.addEventListener("natty:estado", () => {
  if (!podeControlar) return;
  // Recarrega as listas quando troca de servidor ou quando alguém salva/apaga algo (mixer.colecao muda).
  const colecao = `${guildAtual}:${estado.mixer ? estado.mixer.colecao : 0}`;
  if (ultimaColecao !== colecao) { ultimaColecao = colecao; carregarSons(); }
  else desenharMixer();
});

document.addEventListener("DOMContentLoaded", () => {
  $("form-cena").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const nome = $("nome-cena").value.trim();
    if (!nome) return;
    const pads = sons.filter((s) => s.tipo === "efeito").map((s) => s.nome);
    const r = await comando("cena_salvar", { nome, pads });
    if (r && r.ok) { $("nome-cena").value = ""; carregarSons(); }
  });
  $("form-upload").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const arquivo = $("up-arquivo").files[0];
    if (!arquivo) return;
    if (arquivo.size > 20 * 1024 * 1024) { avisar("Arquivo grande demais (máximo 20 MB).", true); return; }
    const dados = new FormData();
    dados.append("nome", $("up-nome").value.trim());
    dados.append("tipo", $("up-tipo").value);
    dados.append("arquivo", arquivo);
    avisar("Enviando…");
    const r = await fetch(`/api/g/${encodeURIComponent(guildAtual)}/som`, { method: "POST", body: dados, credentials: "same-origin" });
    const resposta = await r.json().catch(() => ({ ok: false, texto: "Erro no envio." }));
    avisar(resposta.texto, !resposta.ok);
    if (resposta.ok) { $("form-upload").reset(); carregarSons(); }
  });
});
