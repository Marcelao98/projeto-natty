"use strict";
// Painel da Natty: login, servidor, estado do Bardo ao vivo por WebSocket.
// Sem build e sem biblioteca. Nada de innerHTML com texto vindo de fora:
// títulos de música são texto de terceiros.

const $ = (id) => document.getElementById(id);
let ws = null, guildAtual = null, estado = null, podeControlar = false, tentativas = 0, relogio = null;

function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "dataset") Object.assign(e.dataset, v); else e[k] = v;
  }
  for (const f of filhos) e.append(f);
  return e;
}

function tempo(s) {
  if (s == null || !isFinite(s)) return "";
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function avisar(texto, erro = false) {
  const a = $("aviso");
  a.textContent = texto || "";
  a.classList.toggle("erro", !!erro);
}

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, { credentials: "same-origin", ...opcoes });
  if (r.status === 401) { mostrarLogin(); throw new Error("login"); }
  return r;
}

function mostrarLogin() {
  $("tela-login").hidden = false;
  $("tela-painel").hidden = true;
  $("usuario").hidden = true;
}

async function iniciar() {
  let eu;
  try { eu = await (await api("/api/me")).json(); } catch { return; }
  $("usuario").hidden = false;
  $("nome").textContent = eu.nome;
  if (eu.avatar) $("avatar").src = eu.avatar; else $("avatar").hidden = true;
  const guilds = await (await api("/api/guilds")).json();
  $("tela-painel").hidden = false;
  const sel = $("servidor");
  sel.replaceChildren(...guilds.map((g) => el("option", { value: g.id, textContent: g.nome })));
  if (!guilds.length) { avisar("A Natty não está em nenhum servidor seu.", true); return; }
  const salvo = localStorageGet("natty.guild");
  if (salvo && guilds.some((g) => g.id === salvo)) sel.value = salvo;
  sel.addEventListener("change", () => { localStorageSet("natty.guild", sel.value); conectar(sel.value); });
  conectar(sel.value);
}

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* sem storage */ } }

function conectar(guildId) {
  guildAtual = guildId;
  if (ws) { ws.onclose = null; ws.close(); }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?guild=${encodeURIComponent(guildId)}`);
  selo("conectando…", false);
  ws.onopen = () => { tentativas = 0; selo("ao vivo", true); };
  ws.onmessage = (ev) => receber(JSON.parse(ev.data));
  ws.onclose = (ev) => {
    selo("desconectado", false);
    if (ev.code === 4403) { avisar("Você perdeu o acesso a esse servidor.", true); return; }
    if (guildAtual !== guildId) return;
    const espera = Math.min(30000, 1000 * 2 ** tentativas++);
    setTimeout(() => guildAtual === guildId && conectar(guildId), espera);
  };
}

function selo(texto, on) { const s = $("conexao"); s.textContent = texto; s.classList.toggle("on", on); }

let pendentes = new Map(), proximoId = 1;
function comando(cmd, args = {}) {
  if (!ws || ws.readyState !== WebSocket.OPEN) { avisar("Sem conexão com a Natty.", true); return Promise.resolve(null); }
  const id = proximoId++;
  ws.send(JSON.stringify({ id, cmd, args }));
  return new Promise((ok) => pendentes.set(id, ok));
}

function receber(msg) {
  if (msg.tipo === "estado") { estado = msg.estado; podeControlar = msg.pode_controlar; desenhar(); document.dispatchEvent(new CustomEvent("natty:estado", { detail: msg })); }
  else if (msg.tipo === "resposta") {
    avisar(msg.texto, !msg.ok);
    const ok = pendentes.get(msg.id); pendentes.delete(msg.id); if (ok) ok(msg);
  } else if (msg.tipo === "erro") avisar(msg.texto, true);
}

function desenhar() {
  const e = estado;
  document.body.classList.toggle("leitura", !podeControlar);
  $("leitura").hidden = podeControlar;
  $("canal").textContent = e.conectado && e.canal ? `· ${e.canal}` : "";
  $("titulo").textContent = e.tocando ? e.tocando.titulo : (e.conectado ? "Nada tocando" : "Fora da call");
  $("duracao").textContent = e.tocando ? tempo(e.tocando.duracao) : "";
  $("btn-pausa").textContent = e.pausado ? "▶" : "⏸";
  $("btn-rep-faixa").classList.toggle("ligado", e.repetir);
  $("btn-rep-fila").classList.toggle("ligado", e.repetir_fila);
  if (document.activeElement !== $("volume")) $("volume").value = e.volume;
  $("volume-num").textContent = `${e.volume}%`;
  $("fila-info").textContent = e.proximas.length ? `· ${e.proximas.length}/${e.max_fila}` : "";
  const fila = $("fila");
  if (!e.proximas.length) fila.replaceChildren(el("li", { className: "vazio", textContent: "A fila está vazia." }));
  else fila.replaceChildren(...e.proximas.map((m, i) => el("li", {},
    el("span", { className: "pos", textContent: `${i + 1}.` }),
    el("span", { className: "nome", textContent: m.titulo }),
    el("span", { className: "dur", textContent: tempo(m.duracao) }),
    el("button", { className: "discreto so-mestre", type: "button", textContent: "✕", title: "Tirar da fila",
      dataset: { cmd: "remover", posicao: String(i + 1) } }))));
  clearInterval(relogio);
  atualizarProgresso();
  relogio = setInterval(atualizarProgresso, 1000);
}

function atualizarProgresso() {
  const e = estado;
  if (!e || !e.tocando || !e.desde) { $("barra").style.width = "0"; $("decorrido").textContent = ""; return; }
  const passou = e.pausado ? null : Date.now() / 1000 - e.desde;
  $("decorrido").textContent = passou == null ? "pausado" : tempo(passou);
  if (e.tocando.duracao && passou != null) $("barra").style.width = `${Math.min(100, (100 * passou) / e.tocando.duracao)}%`;
}

async function carregarPlaylists() {
  const r = await comando("playlists");
  const lista = $("playlists");
  const itens = (r && r.ok && r.dados) || [];
  if (!itens.length) { lista.replaceChildren(el("li", { className: "vazio", textContent: "Nenhuma playlist salva." })); return; }
  lista.replaceChildren(...itens.map((p) => el("li", {},
    el("span", { className: "nome", textContent: `${p.nome} (${p.quantas})` }),
    el("button", { type: "button", textContent: "▶ tocar", dataset: { cmd: "tocar_playlist", nome: p.nome } }))));
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-cmd]");
  if (!b) return;
  const d = b.dataset;
  if (d.cmd === "pausar_continuar") return comando(estado && estado.pausado ? "continuar" : "pausar");
  if (d.cmd === "repetir") {
    const ligado = d.modo === "fila" ? estado.repetir_fila : estado.repetir;
    return comando("repetir", { modo: ligado ? "desligar" : d.modo });
  }
  if (d.cmd === "remover") return comando("remover", { posicao: Number(d.posicao) });
  if (d.cmd === "tocar_playlist") return comando("tocar_playlist", { nome: d.nome });
  if (d.cmd === "parar" && !confirm("Parar a música e limpar a fila?")) return;
  if (d.cmd === "limpar_fila" && !confirm("Limpar a fila?")) return;
  return comando(d.cmd);
});

let volumeTimer = null;
document.addEventListener("DOMContentLoaded", () => {
  $("volume").addEventListener("input", (ev) => {
    $("volume-num").textContent = `${ev.target.value}%`;
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(() => comando("volume", { nivel: Number(ev.target.value) }), 150);
  });
  $("form-tocar").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const pedido = $("pedido").value.trim();
    if (!pedido) return;
    avisar("Procurando…");
    const r = await comando("tocar", { pedido });
    if (r && r.ok) $("pedido").value = "";
  });
  $("form-salvar").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const nome = $("nome-playlist").value.trim();
    if (!nome) return;
    const r = await comando("salvar_playlist", { nome });
    if (r && r.ok) { $("nome-playlist").value = ""; carregarPlaylists(); }
  });
  $("sair").addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    location.reload();
  });
  document.addEventListener("natty:estado", () => { if (podeControlar && !carregadas) { carregadas = true; carregarPlaylists(); } });
  iniciar();
});
let carregadas = false;
