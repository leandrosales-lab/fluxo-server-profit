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
  return spawn("python", ["-X", "utf8", "main.py", "--asset", "PETR4", "--modo", "replay",
    "--arquivo", "replay/exemplo_petr4.csv", "--velocidade", "6", "--port", String(PORTA)],
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
  await page.waitForFunction(() => document.getElementById("status-texto").textContent.includes("exemplo_petr4.csv"));
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

verificacoes.push(["operar: busca de papel com autocompletar", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("f-ultimo")?.textContent !== "—", null, { timeout: 30000 });
  checar(await page.locator("#busca").isHidden(), "caixa de busca começa fechada");
  await page.click("#f-ativo");
  checar(await page.locator("#busca").isVisible(), "clicar no ticker abre a busca");
  await page.fill("#busca-in", "pet");
  await page.waitForSelector("#busca-lista li");
  const itens = await page.$$eval("#busca-lista li", (l) => l.map((x) => x.textContent));
  checar(itens.length > 0 && itens.every((t) => t.startsWith("PET")) && itens.includes("PETR4"), `digitar "pet" sugere ${itens.join(", ")}`);
  checar(await page.inputValue("#busca-in") === "PET", "texto vira maiúsculo");
  await page.keyboard.press("ArrowDown");
  checar(await page.getAttribute("#busca-lista li[aria-selected='true']", "id") === "busca-op-1", "seta para baixo move a seleção");
  await page.screenshot({ path: path.join(SAIDA, "operar-busca.png") });
  await page.keyboard.press("Escape");
  checar(await page.locator("#busca").isHidden(), "Esc fecha a busca");
  await page.keyboard.press("/");
  checar(await page.locator("#busca").isVisible(), "tecla / abre a busca");
  let corpo = null;
  await page.route("**/operar/ativo", (r) => { corpo = r.request().postData(); r.fulfill({ status: 200, contentType: "application/json", body: '{"ativo":"PETR4","historico":false}' }); });
  await page.fill("#busca-in", "PETR4");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => performance.getEntriesByType("navigation").length > 0 && document.getElementById("f-ativo"), null, { timeout: 5000 });
  await esperar(800);
  checar(corpo && JSON.parse(corpo).ativo === "PETR4", `Enter envia POST /operar/ativo com o papel (${corpo})`);
  await page.unroute("**/operar/ativo");
}]);

verificacoes.push(["operar: reset com o replay rodando (mercado aberto)", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.click('#filtros [data-filtro="todos"]');   // o padrão é só iceberg; aqui vale qualquer sinal
  // precisa já haver sinal na tela: senão "0 hoje" seria verdade antes do reset e o teste não provaria nada
  await page.waitForFunction(() => /^[1-9]\d* hoje$/.test(document.getElementById("sinais-meta").textContent),
    null, { timeout: 60000 });
  const antes = await page.evaluate(() => fetch("/state").then((r) => r.json()).then((e) => e.geracao));
  await page.evaluate(() => fetch("/reset", { method: "POST" }));
  // o /state seguinte já pode ter negócios novos; a tela tem que perceber pela geração e zerar os sinais
  await page.waitForFunction(() => document.getElementById("sinais-meta").textContent === "0 hoje", null, { timeout: 3000 });
  const depois = await page.evaluate(() => fetch("/state").then((r) => r.json()).then((e) => e.geracao));
  checar(depois === antes + 1, `reset com negócios chegando: tela zera os sinais (geração ${antes} → ${depois})`);
}]);

verificacoes.push(["operar: painéis", async (page) => {
  await page.goto(`${BASE}/operar`);
  checar(await page.getAttribute('#filtros [data-filtro="Iceberg"]', "aria-pressed") === "true", "filtro padrão é só iceberg");
  await page.click('#filtros [data-filtro="todos"]');
  await page.waitForFunction(() => document.getElementById("m-titulo").textContent !== "Nenhum sinal ainda hoje",
    null, { timeout: 60000 });
  const titulo = await page.textContent("#m-titulo");
  checar(/(compradora?|vendedora?|comprador|vendedor)$/.test(titulo), `manchete do sinal: ${titulo}`);
  checar((await page.textContent("#m-preco")).startsWith("em "), "manchete mostra \"em {preço}\"");
  const n1 = await page.locator("#tt tr").count();
  await esperar(2000);
  const n2 = await page.locator("#tt tr").count();
  checar(n2 > 0 && n2 >= n1, `Times & Trades com ${n2} linhas`);
  checar((await page.textContent("#defesas-nota")).length > 0, `defesas: ${await page.textContent("#defesas-nota")}`);
  checar((await page.textContent("#book-spread")).length > 0, `book: ${await page.textContent("#book-spread")}`);
  checar(await page.locator("#saldo tr").count() > 0, "saldo das corretoras preenchido");
  await page.screenshot({ path: path.join(SAIDA, "operar-com-sinal.png") });
}]);

// Book com dados SINTÉTICOS de teste, injetados pela rota (o replay de exemplo só tem o topo)
function bookSintetico(n) {
  const nomes = ["UBS", "XP", "BTG PACTUAL", "JP MORGAN", "AGORA", "ITAU"];
  const lado = (base, dir) => Array.from({ length: n }, (_, i) => ({ price: +(base + dir * 0.01 * i).toFixed(2),
    qty: 500 + ((i * 7919) % 9) * 1100, ordens: 1 + (i * 3) % 9,
    corretoras: [[nomes[i % 6], 3000], [nomes[(i + 2) % 6], 2000], [nomes[(i + 4) % 6], 900]] }));
  return { depth: "full", fonte: "ofertas", bids: lado(59.05, -1), asks: lado(59.07, 1), updated: 1 };
}
verificacoes.push(["operar: book", async (page) => {
  let dados = bookSintetico(20);
  await page.route("**/book", (r) => r.fulfill({ json: dados }));
  for (const [w, h] of [[1920, 1080], [1536, 864], [1280, 720]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`${BASE}/operar`);
    await page.waitForFunction(() => document.querySelectorAll("#book-asks tr").length > 0, null, { timeout: 10000 });
    const m = await page.evaluate(() => {
      const d = document.documentElement, b = document.getElementById("book"), g = document.getElementById("grafico");
      const num = (t) => +t.replace(/\./g, "").replace(",", ".");
      const bids = [...document.querySelectorAll("#book-bids tr")], asks = [...document.querySelectorAll("#book-asks tr")];
      const pb = bids.map((r) => num(r.cells[3].textContent)), pa = asks.map((r) => num(r.cells[0].textContent));
      const lados = [...document.querySelectorAll(".book-lado")];
      return { sw: d.scrollWidth, w: innerWidth, asks: asks.length, bids: bids.length, bw: b.clientWidth, cw: g.clientWidth,
        cortado: lados.some((l) => l.scrollHeight > l.clientHeight + 1),
        // compra à esquerda (preço encostado no centro, melhor bid na 1ª linha), venda à direita (melhor ask na 1ª linha)
        bidsDesc: pb.every((v, i) => i === 0 || v < pb[i - 1]), asksAsc: pa.every((v, i) => i === 0 || v > pa[i - 1]),
        alinhadas: bids.every((r, i) => !asks[i] || Math.abs(r.getBoundingClientRect().top - asks[i].getBoundingClientRect().top) < 1),
        esquerda: bids[0].cells[3].getBoundingClientRect().right <= asks[0].cells[0].getBoundingClientRect().left + 1,
        fonte: document.getElementById("book-fonte").textContent, spread: document.getElementById("book-spread").textContent,
        ordens: asks[0].cells[2].textContent, ordensB: bids[0].cells[1].textContent,
        corr: asks[0].cells[3].textContent, corrB: bids[0].cells[0].textContent,
        tot: document.getElementById("book-tot-bids").textContent,
        rotulos: [...document.querySelectorAll(".book-tab[aria-label]")].length };
    });
    checar(m.sw <= m.w, `book ${w}×${h}: sem rolagem horizontal`);
    checar(m.asks >= 8 && m.asks <= 20 && m.asks === m.bids, `book ${w}×${h}: ${m.asks} níveis por lado, sem rolagem`);
    checar(!m.cortado, `book ${w}×${h}: nenhum nível cortado`);
    checar(m.bidsDesc && m.asksAsc && m.esquerda, `book ${w}×${h}: compra à esquerda (decrescente) e venda à direita (crescente)`);
    checar(m.alinhadas, `book ${w}×${h}: níveis de compra e venda alinhados na mesma linha`);
    checar(m.fonte === "livro completo" && m.spread === "spread 0,02", `book ${w}×${h}: fonte "${m.fonte}", ${m.spread}`);
    checar(/^\d+$/.test(m.ordens) && /^\d+$/.test(m.ordensB) && m.corr.length > 0 && m.corrB.length > 0 && m.rotulos === 2 && m.tot.length > 0, `book ${w}×${h}: ordens, corretoras, total e aria-label`);
    checar(m.cw >= 320, `book ${w}×${h}: gráfico ainda com ${m.cw}px`);
    for (const tema of ["escuro", "claro"]) {
      await page.evaluate((t) => { document.documentElement.dataset.tema = t; }, tema);
      await page.screenshot({ path: path.join(SAIDA, `book-${w}x${h}-${tema}.png`) });
    }
  }
  // formato antigo (só topo, sem ordens/corretoras) e fonte sem livro
  dados = { depth: "top", fonte: "topo", bids: [{ price: 59.05, qty: 7900, broker: "" }], asks: [{ price: 59.07, qty: 5100, broker: "" }], updated: 1 };
  await page.waitForFunction(() => document.getElementById("book-fonte").textContent === "só topo", null, { timeout: 5000 });
  checar(await page.locator("#book-asks tr").count() === 1, "só topo: um nível por lado");
  checar((await page.locator("#book-asks tr").first().locator("td").nth(3).textContent()) === "—" && (await page.locator("#book-bids tr").first().locator("td").nth(0).textContent()) === "—", "só topo: corretoras como — nos dois lados");
  dados = { depth: "none", bids: [], asks: [], updated: 0 };
  await page.waitForFunction(() => document.getElementById("book-fonte").textContent === "sem livro nesta fonte", null, { timeout: 5000 });
  checar(await page.locator("#book-asks tr").count() === 0 && await page.isVisible("#book-msg"), "sem livro: níveis somem e a mensagem aparece");
  await page.unroute("**/book");
  await page.setViewportSize({ width: 1920, height: 1080 });
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

// Notebook 15,6" Full HD com o Windows em 125% / 150% → área útil de 1536×864 / 1280×720
verificacoes.push(["telas cabem no notebook", async (page) => {
  for (const [w, h] of [[1536, 864], [1280, 720]]) {
    await page.setViewportSize({ width: w, height: h });
    for (const rota of ["operar", "conexao", "radar", "leilao"]) {
      await page.goto(`${BASE}/${rota}`);
      await esperar(2500);
      const m = await page.evaluate(() => {
        const d = document.documentElement, f = document.querySelector(".faixa");
        const cortados = [...document.querySelectorAll(".secao")].filter((s) =>
          getComputedStyle(s).overflowY !== "auto" && s.scrollHeight > s.clientHeight + 1).length;
        return { sw: d.scrollWidth, sh: d.scrollHeight, w: innerWidth, h: innerHeight,
                 faixa: f.scrollWidth - f.clientWidth, cortados };
      });
      checar(m.sw <= m.w && m.sh <= m.h, `${rota} ${w}×${h}: sem rolagem (${m.sw}×${m.sh})`);
      checar(m.faixa <= 1, `${rota} ${w}×${h}: faixa de números inteira (sobra ${m.faixa}px)`);
      checar(m.cortados === 0, `${rota} ${w}×${h}: nenhuma seção com conteúdo escondido (${m.cortados})`);
      await page.screenshot({ path: path.join(SAIDA, `${rota}-${w}x${h}.png`) });
    }
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
}]);

verificacoes.push(["radar sem --radar", async (page) => {
  await page.goto(`${BASE}/radar`);
  await page.waitForFunction(() => !document.getElementById("radar-vazio").hidden);
  checar((await page.textContent("#radar-vazio")).includes("Radar desligado"), "radar avisa que está desligado");
  checar(await page.locator('.aba[aria-current="page"]').textContent() === "Radar", "aba Radar marcada");
  await page.keyboard.press("F1");
  await page.waitForURL("**/operar");
  await page.keyboard.press("F3");
  await page.waitForURL("**/radar");
  checar(true, "F3 abre o Radar");
  await page.screenshot({ path: path.join(SAIDA, "radar-desligado.png") });
}]);

verificacoes.push(["leilão sem --leilao", async (page) => {
  await page.goto(`${BASE}/leilao`);
  await page.waitForFunction(() => !document.getElementById("lista-vazio").hidden);
  checar((await page.textContent("#lista-vazio")).includes("Leilão desligado"), "leilão avisa que está desligado");
  checar(await page.locator('.aba[aria-current="page"]').textContent() === "Leilão", "aba Leilão marcada");
  await page.keyboard.press("F1");
  await page.waitForURL("**/operar");
  await page.keyboard.press("F4");
  await page.waitForURL("**/leilao");
  checar(true, "F4 abre o Leilão");
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
