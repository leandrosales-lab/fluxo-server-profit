// QA no navegador das telas Operar e Conexão contra o replay de exemplo.
// Usa o Playwright já instalado em C:/Projetos/urnalytics-marcelo (nada é instalado neste repositório).
// Uso: node tools/qa_telas.js   → sobe o replay na porta 5077 e salva as capturas em qa-telas/
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const { chromium } = require(process.env.PLAYWRIGHT_DIR || "C:/Projetos/urnalytics-marcelo/node_modules/playwright");

const RAIZ = path.resolve(__dirname, "..");
const PORTA = 5077;
const BASE = `http://127.0.0.1:${PORTA}`;
const SAIDA = path.join(RAIZ, "qa-telas");
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

function subirServidor() {
  return spawn("python", ["-X", "utf8", "main.py", "--asset", "WDOFUT", "--modo", "replay",
    "--arquivo", "replay/exemplo_wdo.csv", "--tick-size", "0.5", "--velocidade", "6", "--port", String(PORTA)],
    { cwd: RAIZ, env: { ...process.env, PYTHONIOENCODING: "utf-8" }, stdio: "ignore" });
}
async function esperarSaude() {
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(`${BASE}/health`)).ok) return; } catch { /* ainda subindo */ }
    await esperar(250);
  }
  throw new Error("servidor não respondeu /health");
}
/** Espera o replay acabar: o último negócio fica igual por 6 s seguidos (máx. 2 min). */
async function esperarFimReplay() {
  let anterior = null, iguais = 0;
  for (let i = 0; i < 240 && iguais < 12; i++) {
    const r = await (await fetch(`${BASE}/trades?limit=1`)).json();
    const ts = r.trades.at(-1)?.timestamp ?? null;
    iguais = ts !== null && ts === anterior ? iguais + 1 : 0;
    anterior = ts;
    await esperar(500);
  }
}
function checar(condicao, msg) {
  if (!condicao) throw new Error(msg);
  console.log(`  ✓ ${msg}`);
}

const verificacoes = [];   // [nome, async (page) => {}] — as tarefas de cada tela acrescentam as suas

verificacoes.push(["barra e atalhos", async (page) => {
  await page.goto(`${BASE}/operar`);
  // o /health chega em paralelo ao 1º /state: espera o status já com o nome da fonte
  await page.waitForFunction(() => document.getElementById("status-texto").textContent.includes("exemplo_wdo.csv"));
  checar(await page.locator('.aba[aria-current="page"]').textContent() === "Operar", "aba Operar marcada");
  checar(true, "status mostra a fonte do replay");
  checar((await page.textContent("#modo")).includes("replay"), "modo replay no cabeçalho");
  checar((await page.textContent("#aviso-exemplo")).startsWith("Dados de exemplo"), "rodapé avisa que são dados de exemplo");
  await page.keyboard.press("F2");
  await page.waitForURL("**/conexao");
  checar(true, "F2 abre a Conexão");
  await page.keyboard.press("F1");
  await page.waitForURL("**/operar");
  checar(true, "F1 volta ao Operar");
  const antes = await page.evaluate(() => document.documentElement.dataset.tema);
  await page.keyboard.press("t");
  const depois = await page.evaluate(() => document.documentElement.dataset.tema);
  checar(antes !== depois, `T alterna o tema (${antes} → ${depois})`);
  await page.reload();
  checar(await page.evaluate(() => document.documentElement.dataset.tema) === depois, "tema persiste ao recarregar");
}]);

verificacoes.push(["operar: faixa e gráfico", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("f-ultimo")?.textContent !== "—", null, { timeout: 30000 });
  checar(/\d/.test(await page.textContent("#f-ultimo")), `faixa mostra o último preço (${await page.textContent("#f-ultimo")})`);
  checar(/mi|mil|R\$/.test(await page.textContent("#f-fin")), "volume financeiro formatado");
  checar(await page.locator("#grafico canvas").count() > 0, "gráfico desenhado");
  await page.click('#tfs [data-tf="300"]');
  checar(await page.getAttribute('#tfs [data-tf="300"]', "aria-pressed") === "true", "timeframe de 5 min selecionado");
  await page.click('#tfs [data-tf="60"]');
  for (const tema of ["escuro", "claro"]) {
    await page.evaluate((t) => localStorage.setItem("fluxo.tema", t), tema);
    await page.reload();
    await page.waitForFunction(() => document.getElementById("f-ultimo").textContent !== "—");
    await esperar(1500);
    await page.screenshot({ path: path.join(SAIDA, `operar-${tema}.png`) });
  }
  checar(true, "capturas operar-escuro.png e operar-claro.png salvas");
}]);

verificacoes.push(["operar: painéis", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("m-titulo").textContent !== "Nenhum sinal ainda hoje",
    null, { timeout: 60000 });
  const titulo = await page.textContent("#m-titulo");
  checar(/(compradora?|vendedora?|comprador|vendedor)$/.test(titulo), `manchete do sinal: ${titulo}`);
  checar((await page.textContent("#m-preco")).startsWith("em "), "manchete mostra \"em {preço}\"");
  const n1 = await page.locator("#tt tr").count();
  await esperar(2000);
  const n2 = await page.locator("#tt tr").count();
  checar(n2 > 0 && n2 >= n1, `Times & Trades com ${n2} linhas`);
  checar((await page.textContent("#livro-nota")).length > 0, `livro: ${await page.textContent("#livro-nota")}`);
  checar(await page.locator("#saldo tr").count() > 0, "saldo das corretoras preenchido");
  await page.screenshot({ path: path.join(SAIDA, "operar-com-sinal.png") });
}]);

verificacoes.push(["operar: reset com a tela aberta", async (page) => {
  await esperarFimReplay();
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("f-ultimo").textContent !== "—");
  await page.evaluate(() => fetch("/reset", { method: "POST" }));
  // a faixa e a manchete se atualizam no mesmo ciclo, mas a manchete só depois das consultas de T&T e livro
  await page.waitForFunction(() => document.getElementById("f-ultimo").textContent === "—"
    && document.getElementById("m-titulo").textContent === "Nenhum sinal ainda hoje", null, { timeout: 5000 });
  checar(true, "reset limpa faixa e manchete sem recarregar");
}]);

verificacoes.push(["conexão", async (page) => {
  await page.goto(`${BASE}/conexao`);
  await page.waitForFunction(() => document.querySelectorAll("#log tr").length > 0, null, { timeout: 10000 });
  checar(true, `log com ${await page.locator("#log tr").count()} eventos`);
  checar(await page.isHidden("#reconectar"), "sem botão Reconectar fora do modo dll");
  checar((await page.textContent("#c-agregado")).includes("Sem ProfitDLL"), "faixa explica a fonte sem DLL");
  // o replay de exemplo só gera INFO: o filtro "info" é o que tem linhas para provar a filtragem
  await page.click('#log-filtros [data-nivel="info"]');
  await esperar(700);
  const niveis = await page.locator("#log tr td:nth-child(2)").allTextContents();
  checar(niveis.length > 0 && niveis.every((n) => n === "info"), `filtro "info" mostra só info (${niveis.length})`);
  await page.click('#log-filtros [data-nivel="erro"]');
  await esperar(700);
  checar(await page.locator("#log tr").count() === 0, "filtro \"erro\" esconde as linhas de info");
  await page.click('#log-filtros [data-nivel="todos"]');
  for (const tema of ["escuro", "claro"]) {
    await page.evaluate((t) => localStorage.setItem("fluxo.tema", t), tema);
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll("#log tr").length > 0);
    await page.screenshot({ path: path.join(SAIDA, `conexao-${tema}.png`) });
  }
  checar(true, "capturas conexao-escuro.png e conexao-claro.png salvas");
}]);

// ── as tarefas 8, 9 e 10 acrescentam verificações acima desta linha ──

async function main() {
  fs.mkdirSync(SAIDA, { recursive: true });
  let servidor = subirServidor();
  const navegador = await chromium.launch();
  const erros = [];
  try {
    await esperarSaude();
    const contexto = await navegador.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: "dark" });
    const page = await contexto.newPage();
    page.on("console", (m) => { if (m.type() === "error") erros.push(m.text()); });
    page.on("pageerror", (e) => erros.push(String(e)));
    for (const [nome, verificar] of verificacoes) {
      console.log(`→ ${nome}`);
      await verificar(page);
    }
    checar(erros.length === 0, `nenhum erro no console${erros.length ? ": " + erros.join(" | ") : ""}`);

    // Por último (gera erros de rede de propósito): servidor cai → aviso; volta → aviso some
    console.log("→ servidor parado e de volta");
    await page.goto(`${BASE}/operar`);
    await page.waitForFunction(() => document.getElementById("status-texto").textContent !== "—");
    servidor.kill();
    await page.waitForSelector("#sem-resposta:not([hidden])", { timeout: 8000 });
    checar((await page.textContent("#sem-resposta")).includes("sem resposta do servidor"), "aviso de servidor parado aparece");
    servidor = subirServidor();
    await esperarSaude();
    await page.waitForSelector("#sem-resposta[hidden]", { state: "attached", timeout: 8000 });
    checar(true, "aviso some quando o servidor volta");
    console.log(`\nQA das telas: tudo certo. Capturas em ${SAIDA}`);
  } finally {
    await navegador.close();
    servidor.kill();
  }
}
main().catch((e) => { console.error(`✗ ${e.message}`); process.exitCode = 1; });
