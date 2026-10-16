// Tabela que reaproveita as linhas <tr> e só reescreve as células que mudaram (rolagem estável, pouco reflow).

/**
 * linhas: dados na ordem de exibição.
 * montar(dado) → { classe: "classe da <tr>", celulas: [{ t: "texto", c: "classe da <td>", barra: { pct, lado } }] }
 * Uma célula com `barra` desenha um <span class="barra compra|venda"> com largura pct% (sem texto).
 */
export function atualizarLinhas(tbody, linhas, montar) {
  while (tbody.rows.length > linhas.length) tbody.deleteRow(-1);
  linhas.forEach((dado, i) => {
    const tr = tbody.rows[i] || tbody.insertRow();
    const { classe = "", celulas } = montar(dado);
    if (tr.className !== classe) tr.className = classe;
    while (tr.cells.length > celulas.length) tr.deleteCell(-1);
    celulas.forEach((cel, j) => {
      const td = tr.cells[j] || tr.insertCell();
      const c = cel.c || "";
      if (td.className !== c) td.className = c;
      if (cel.barra) {
        let s = td.firstElementChild;
        if (!s) { td.textContent = ""; s = td.appendChild(document.createElement("span")); }
        const largura = `${Math.max(1, Math.min(100, cel.barra.pct))}%`;
        if (s.style.width !== largura) s.style.width = largura;
        const cls = `barra ${cel.barra.lado}`;
        if (s.className !== cls) s.className = cls;
      } else if (td.textContent !== cel.t) {
        td.textContent = cel.t;
      }
    });
  });
}
