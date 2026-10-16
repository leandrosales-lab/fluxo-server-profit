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
