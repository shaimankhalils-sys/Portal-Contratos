/**
 * Portal de Contratos · índice das minutas no Google Drive
 * ---------------------------------------------------------
 * Roda DENTRO da conta institucional (script.google.com). Uma vez por dia:
 *   1. percorre a pasta "MINUTAS DE CONTRATOS" (e todas as subpastas);
 *   2. reconhece o contrato pelo nome do arquivo:
 *        2-435-2024.pdf          -> contrato 2-435-2024
 *        1TA-2-435-2024.pdf      -> 1º termo aditivo do contrato 2-435-2024
 *   3. envia o índice (nome, ID, tamanho e data de cada arquivo) para o GitHub,
 *      no arquivo data/minutas.json. Os PDFs NÃO saem do Drive.
 *
 * Configuração (uma vez):
 *   - Projeto > Configurações do projeto > Propriedades do script:
 *       GITHUB_TOKEN = (token "fine-grained" do GitHub, só para o repositório
 *                       Portal-Contratos, permissão "Contents: Read and write")
 *   - Execute a função instalarGatilhoDiario() e autorize.
 *   - Para testar na hora: execute atualizarMinutas() e veja o "Registro de execução".
 */

const CONFIG = {
  PASTA_ID: '1DX7chOsUEijvc-8dh5yU9tL_fsQXOnEi',   // MINUTAS DE CONTRATOS
  REPO: 'shaimankhalils-sys/Portal-Contratos',
  CAMINHO: 'data/minutas.json',
  BRANCH: 'main',
  HORA: 7,                                        // atualização diária às 7h
};

// NTA- (opcional) + unidade - sequencial - ano
const PADRAO = /^\s*(?:contrato\s*(?:n\.?\s*[º°o]?\.?)?\s*)?(?:(\d{1,2})\s*[ºo°]?\s*T\.?\s*A\.?\s*[-_ ]\s*)?(\d)\s*[-_]\s*0*(\d{1,5})\s*[-_/]\s*(\d{4})(?!\d)/i;

function atualizarMinutas() {
  const inicio = Date.now();
  const docs = {};
  const semContrato = [];
  let total = 0;

  percorrer_(DriveApp.getFolderById(CONFIG.PASTA_ID), '', (arq, pasta) => {
    total++;
    const nome = arq.getName();
    const m = nome.match(PADRAO);
    if (!m) { semContrato.push({ nome, pasta, id: arq.getId() }); return; }
    const termo = m[1] ? parseInt(m[1], 10) : 0;
    const chave = `${m[2]}-${parseInt(m[3], 10)}-${m[4]}`;   // sem zeros à esquerda
    (docs[chave] = docs[chave] || []).push({
      nome: termo ? `${termo}º Termo Aditivo` : 'Contrato',
      ordem: termo,
      arquivo: nome,
      id: arq.getId(),
      tam: arq.getSize(),
      mod: Utilities.formatDate(arq.getLastUpdated(), 'America/Bahia', 'yyyy-MM-dd'),
      pasta,
    });
  });

  Object.values(docs).forEach(l => l.sort((a, b) => a.ordem - b.ordem || a.arquivo.localeCompare(b.arquivo)));
  const indice = {
    atualizado_em: Utilities.formatDate(new Date(), 'America/Bahia', "yyyy-MM-dd'T'HH:mm"),
    pasta_raiz: CONFIG.PASTA_ID,
    chave: 'normalizada',            // unidade-sequencial-ano, sem zeros à esquerda
    total_arquivos: total,
    docs,
    sem_contrato: semContrato,
  };
  const enviado = enviarGitHub_(JSON.stringify(indice));
  console.log(`${total} arquivos | ${Object.keys(docs).length} contratos com documentos | ` +
              `${semContrato.length} arquivos sem nº de contrato reconhecido | ` +
              `${enviado ? 'índice enviado ao GitHub' : 'sem mudanças'} | ${Math.round((Date.now() - inicio) / 1000)}s`);
}

function percorrer_(pasta, caminho, fn) {
  const arquivos = pasta.getFiles();
  while (arquivos.hasNext()) {
    const a = arquivos.next();
    if (a.isTrashed()) continue;
    fn(a, caminho || pasta.getName());
  }
  const subpastas = pasta.getFolders();
  while (subpastas.hasNext()) {
    const p = subpastas.next();
    if (p.isTrashed()) continue;
    percorrer_(p, caminho ? `${caminho} / ${p.getName()}` : p.getName(), fn);
  }
}

function enviarGitHub_(conteudo) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Defina GITHUB_TOKEN em Configurações do projeto > Propriedades do script.');
  const url = `https://api.github.com/repos/${CONFIG.REPO}/contents/${CONFIG.CAMINHO}`;
  const cab = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' };

  // conteúdo atual (para obter o "sha" e evitar enviar se nada mudou)
  let sha = null, atual = null;
  const r = UrlFetchApp.fetch(`${url}?ref=${CONFIG.BRANCH}`, { headers: cab, muteHttpExceptions: true });
  if (r.getResponseCode() === 200) {
    const j = JSON.parse(r.getContentText());
    sha = j.sha;
    if (j.content) atual = Utilities.newBlob(Utilities.base64Decode(j.content.replace(/\n/g, ''))).getDataAsString();
  }
  const semData = s => s ? s.replace(/"atualizado_em":"[^"]*",?/, '') : s;
  if (atual && semData(atual) === semData(conteudo)) return false;

  const corpo = {
    message: `Atualiza índice das minutas (Drive) ${Utilities.formatDate(new Date(), 'America/Bahia', 'yyyy-MM-dd HH:mm')}`,
    content: Utilities.base64Encode(conteudo, Utilities.Charset.UTF_8),
    branch: CONFIG.BRANCH,
    committer: { name: 'minutas-drive-bot', email: 'minutas-drive-bot@users.noreply.github.com' },
  };
  if (sha) corpo.sha = sha;
  const p = UrlFetchApp.fetch(url, { method: 'put', headers: cab, contentType: 'application/json',
                                     payload: JSON.stringify(corpo), muteHttpExceptions: true });
  if (p.getResponseCode() >= 300) throw new Error(`GitHub respondeu ${p.getResponseCode()}: ${p.getContentText().slice(0, 300)}`);
  return true;
}

function instalarGatilhoDiario() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'atualizarMinutas')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('atualizarMinutas').timeBased().everyDays(1).atHour(CONFIG.HORA).create();
  console.log(`Gatilho diário instalado (por volta das ${CONFIG.HORA}h).`);
}
