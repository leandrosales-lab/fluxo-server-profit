// Acesso à API do Fluxo Server: JSON com timeout, laço de consulta e o relógio do "sem resposta".
let ultimoSucesso = Date.now();

/** Segundos desde a última resposta do servidor (qualquer status HTTP conta como resposta). */
export function segundosSemResposta() { return (Date.now() - ultimoSucesso) / 1000; }

async function pedir(url, opcoes, timeoutMs) {
  const controle = new AbortController();
  const relogio = setTimeout(() => controle.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...opcoes, signal: controle.signal, cache: "no-store" });
    ultimoSucesso = Date.now();
    const dados = await r.json().catch(() => ({}));
    return { status: r.status, dados };
  } finally {
    clearTimeout(relogio);
  }
}

export async function getJSON(url, timeoutMs = 2500) {
  const { status, dados } = await pedir(url, {}, timeoutMs);
  if (status >= 400) throw new Error(dados.error || `HTTP ${status}`);
  return dados;
}

export function postJSON(url, corpo = {}, timeoutMs = 5000) {
  return pedir(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) }, timeoutMs);
}

/** Chama `passo` a cada `intervalo` ms, um de cada vez (nunca sobrepõe). Falha de rede não para o laço. */
export function laco(passo, intervalo = 500) {
  let parado = false;
  async function rodar() {
    if (parado) return;
    const inicio = performance.now();
    try {
      await passo();
    } catch (e) {
      // rede fora/servidor parado: o aviso "sem resposta" do cabeçalho já informa
      if (!(e instanceof TypeError) && e.name !== "AbortError") console.warn(e.message);
    }
    setTimeout(rodar, Math.max(0, intervalo - (performance.now() - inicio)));
  }
  rodar();
  return () => { parado = true; };
}
