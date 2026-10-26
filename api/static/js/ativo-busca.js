// Busca de papel com autocompletar na faixa da tela Operar: digitou PET -> PETR3, PETR4, ... (Enter troca o papel).
import { getJSON, postJSON } from "./api.js";

/** Até `max` papéis que casam com o texto: os que COMEÇAM pelo texto primeiro, depois os que o contêm. */
export function sugerirAtivos(lista, texto, max = 8) {
  const t = String(texto || "").trim().toUpperCase();
  if (!t) return [];
  const comeca = [], contem = [];
  for (const a of lista) {
    if (a.startsWith(t)) comeca.push(a);
    else if (a.includes(t)) contem.push(a);
    if (comeca.length >= max) break;
  }
  return comeca.concat(contem).slice(0, max);
}

export function montarBuscaAtivo() {
  const $ = (id) => document.getElementById(id);
  const rotulo = $("f-ativo"), caixa = $("busca"), entrada = $("busca-in"), ul = $("busca-lista"), msg = $("busca-msg");
  let lista = [], sugestoes = [], ativa = -1, ocupado = false;
  getJSON("/api/ativos").then((d) => { lista = d.ativos || []; }).catch(() => { /* sem lista: só o que for digitado */ });

  function desenhar() {
    ul.replaceChildren(...sugestoes.map((a, i) => {
      const li = document.createElement("li");
      li.id = `busca-op-${i}`; li.setAttribute("role", "option"); li.setAttribute("aria-selected", String(i === ativa));
      li.textContent = a; li.className = "mono";
      li.addEventListener("mousedown", (ev) => { ev.preventDefault(); trocar(a); });
      return li;
    }));
    ul.hidden = !sugestoes.length;
    entrada.setAttribute("aria-expanded", String(sugestoes.length > 0));
    entrada.setAttribute("aria-activedescendant", ativa >= 0 ? `busca-op-${ativa}` : "");
  }
  document.body.appendChild(caixa);           // fora da faixa: ela corta o que passa da sua altura
  function abrir() {
    const r = rotulo.getBoundingClientRect();
    caixa.style.left = `${Math.max(8, r.left - 8)}px`; caixa.style.top = `${r.bottom + 6}px`;
    caixa.hidden = false; msg.textContent = ""; entrada.value = ""; sugestoes = []; ativa = -1; desenhar();
    entrada.focus({ preventScroll: true });
  }
  function fechar() { caixa.hidden = true; sugestoes = []; desenhar(); }
  async function trocar(ticker) {
    const t = String(ticker || "").trim().toUpperCase();
    if (!t || ocupado) return;
    ocupado = true; msg.textContent = `Trocando para ${t}…`;
    try {
      const { status, dados } = await postJSON("/operar/ativo", { ativo: t });
      if (status < 400) { location.reload(); return; }
      msg.textContent = dados.error || `não foi possível trocar (HTTP ${status})`;
    } catch { msg.textContent = "sem resposta do servidor"; }
    ocupado = false;
  }

  rotulo.addEventListener("click", abrir);
  rotulo.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); } });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && caixa.hidden && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) { ev.preventDefault(); abrir(); }
  });
  entrada.addEventListener("input", () => {
    entrada.value = entrada.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
    sugestoes = sugerirAtivos(lista, entrada.value); ativa = sugestoes.length ? 0 : -1; msg.textContent = ""; desenhar();
  });
  entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (sugestoes.length) { ativa = (ativa + (ev.key === "ArrowDown" ? 1 : -1) + sugestoes.length) % sugestoes.length; desenhar(); }
    } else if (ev.key === "Enter") {
      ev.preventDefault(); trocar(ativa >= 0 ? sugestoes[ativa] : entrada.value);
    } else if (ev.key === "Escape") { fechar(); rotulo.focus(); }
  });
  document.addEventListener("mousedown", (ev) => { if (!caixa.hidden && !caixa.contains(ev.target) && ev.target !== rotulo) fechar(); });
}
