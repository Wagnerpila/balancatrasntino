// Roda dentro da aba do WhatsApp Web. A cada 2 s o fundo da extensão (fundo.js) acorda esta aba,
// que pergunta ao sistema da balança se há aviso para mandar; se houver, abre a conversa com o
// texto pronto (web.whatsapp.com/send?...) e clica em Enviar. O envio em andamento fica no
// sessionStorage porque a página recarrega. Funciona com a aba em segundo plano (ver pagina.js).
const CHAVE = 'balanca_envio';
const $ = s => document.querySelector(s);

function pedir(caminho, corpo) {
  return new Promise(ok => {
    try {
      chrome.runtime.sendMessage({caminho, corpo}, r => ok(r || {}));
    } catch (e) {  // a extensão foi atualizada: este código antigo para (F5 na aba carrega o novo)
      ok({});
    }
  });
}

function caixaTexto() { return $('footer div[contenteditable="true"]'); }

function situacao() {
  const txt = document.body ? document.body.innerText : '';
  const dialogo = [...document.querySelectorAll('[role="dialog"], [data-animate-modal-popup="true"]')].map(d => d.innerText).join(' ');
  if (/inv[aá]lid|invalid|n[aã]o est[aá] no whatsapp|isn.t on whatsapp/i.test(dialogo)) return 'invalido';
  if (!$('#side, #pane-side') && ($('canvas[aria-label], div[data-ref]')
      || /escaneie|scan the qr|conectar com n[uú]mero/i.test(txt))) return 'qr';
  const caixa = caixaTexto();
  if (caixa) return caixa.innerText.trim() ? 'pronto' : 'conversa';
  if ($('#side, #pane-side')) return 'conectado';
  return 'carregando';
}

function clicarEnviar() {
  const icone = $('footer [data-icon="send"], footer [data-icon="wds-ic-send-filled"]');
  const botao = $('footer button[aria-label="Enviar"], footer button[aria-label="Send"]')
    || (icone && icone.closest('button, [role="button"]'));
  if (botao) { botao.click(); return; }
  const caixa = caixaTexto();
  caixa.focus();
  caixa.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
}

const esperar = ms => new Promise(r => setTimeout(r, ms));
function salvar(envio, mudancas) { sessionStorage.setItem(CHAVE, JSON.stringify(Object.assign(envio, mudancas))); }

// botão Enviar da prévia de imagens (fica fora do rodapé da conversa)
// Tudo que parece "Enviar": aria-label/título, data-icon ou o <title> do desenho (svg) do ícone
const PARECE_ENVIAR = /^(enviar|send)|(^|-)send(-|$)/i;
function candidatosEnviar() {
  return [...document.querySelectorAll('[aria-label], [title], [data-icon], svg title')].filter(e => {
    const t = e.tagName.toLowerCase() === 'title' ? e.textContent
      : (e.getAttribute('aria-label') || e.getAttribute('title') || (e.dataset && e.dataset.icon) || '');
    return PARECE_ENVIAR.test((t || '').trim()) && !e.closest('footer');
  });
}
function botaoEnviarMidia() {
  const el = candidatosEnviar()[0];
  return el && (el.closest('button, [role="button"]') || el.closest('div[tabindex]') || el);
}
const descreverEnviar = () => candidatosEnviar().map(e => (e.outerHTML || '').slice(0, 120)).join(' ¦ ') || 'nenhum';

// Põe as imagens na conversa. Tenta, nesta ordem: o campo de arquivo do menu Anexar
// (Fotos e vídeos), arrastar e soltar na conversa e colar (Ctrl+V).
const FORMAS = ['anexar', 'soltar', 'colar'];
// item "Fotos e vídeos" do menu Anexar (não usar "Nova figurinha": mandaria como figurinha)
function itemFotos() {
  const el = [...document.querySelectorAll('[role="menu"] *')]
    .filter(e => /^(fotos e v[ií]deos|photos (&|and) videos)$/i.test((e.innerText || '').trim()))
    .pop();  // o mais interno
  return el && (el.closest('[role="menuitem"], li, [role="button"], div[tabindex], button') || el);
}
function botaoAnexar() {
  const el = [...document.querySelectorAll('footer [aria-label], footer [title], footer [data-icon], footer svg title')].find(e => {
    const t = e.tagName.toLowerCase() === 'title' ? e.textContent
      : (e.getAttribute('aria-label') || e.getAttribute('title') || (e.dataset && e.dataset.icon) || '');
    return /anexar|attach|clip|plus/i.test(t || '');
  });
  return el && (el.closest('button, [role="button"]') || el);
}
async function porArquivos(arquivos, forma) {
  const dt = new DataTransfer();
  arquivos.forEach(f => dt.items.add(f));
  if (forma === 'anexar') {  // Anexar → Fotos e vídeos; pagina.js entrega as imagens no lugar da janela do Windows
    const anexar = botaoAnexar();
    if (!anexar) return false;
    window.postMessage({balancaArquivos: arquivos}, '*');
    anexar.click();
    await esperar(1200);
    const item = itemFotos();
    if (!item) return false;
    item.click();
    await esperar(1500);
    // se o WhatsApp usou um campo já existente (sem chamar .click()), entrega direto nele
    const campo = [...document.querySelectorAll('input[type="file"]')].find(i => /video/.test(i.accept || ''));
    if (campo && !botaoEnviarMidia()) {
      campo.files = dt.files;
      campo.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return true;
  }
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));  // fecha o menu Anexar
  if (forma === 'soltar') {
    const alvo = document.querySelector('#main') || caixaTexto();
    for (const tipo of ['dragenter', 'dragover', 'drop'])
      alvo.dispatchEvent(new DragEvent(tipo, {dataTransfer: dt, bubbles: true, cancelable: true}));
    return true;
  }
  const caixa = caixaTexto();
  caixa.focus();
  caixa.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return true;
}
// lista os botões da conversa e o que aparece ao clicar em Anexar (não envia nada)
function rotulos(raiz) {
  return [...(raiz || document).querySelectorAll('button, [role="button"], [data-icon], input[type="file"], [aria-label], [title]')].slice(0, 80)
    .map(e => [e.tagName.toLowerCase(), e.getAttribute('aria-label') || '', e.title || '', e.dataset.icon || '',
               e.type === 'file' ? 'accept=' + e.accept : '', (e.closest('footer') ? 'footer' : '')].filter(Boolean).join('|'));
}
async function diagnostico() {
  const main = document.querySelector('#main');
  const html = e => e ? (e.outerHTML || '').replace(/<path[^>]*>/g, '').slice(0, 300) : null;
  const d = {url: location.href, situacao: situacao(), tem_main: !!main, caixa: !!caixaTexto(),
             rodape: rotulos(document.querySelector('footer')), inputs: rotulos(document.body).filter(x => x.includes('accept=')),
             enviar_antes: candidatosEnviar().map(html), anexar: html(botaoAnexar())};
  const anexar = botaoAnexar();
  if (anexar) {
    anexar.click();
    await esperar(1500);
    d.menu = [...document.querySelectorAll('[role="menu"], [role="application"], ul')].map(html).slice(0, 5);
    d.itens = [...document.querySelectorAll('li, [role="menuitem"], [role="button"]')].map(e => (e.innerText || '').trim())
      .filter(t => t && t.length < 40).slice(0, 40);
    d.inputs_menu = rotulos(document.body).filter(x => x.includes('accept='));
    d.enviar_menu = candidatosEnviar().map(html);
    document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true}));
  }
  return d;
}


// liga/desliga o "modo visível" da aba durante o envio (pagina.js)
function modoEnvio(ligado) {
  if (ligado) document.documentElement.dataset.balancaEnviando = '1';
  else delete document.documentElement.dataset.balancaEnviando;
}

async function terminar(envio, ok, erro) {
  sessionStorage.removeItem(CHAVE);
  modoEnvio(false);
  await pedir('whatsapp/resultado', {id: envio.id, ok, erro});
}

let ocupado = false, esperandoDesde = 0, guardado = null;
async function ciclo() {
  if (ocupado) return;
  ocupado = true;
  try {
    const est = situacao();
    const envio = JSON.parse(sessionStorage.getItem(CHAVE) || 'null');
    if (envio) {  // continua o envio depois de a página recarregar
      modoEnvio(true);
      pedir('whatsapp/proximo?estado=enviando&so_estado=1');  // o sistema sabe que a aba está viva
      const limite = envio.arquivos ? 180000 : 90000;
      if (Date.now() - envio.desde > limite) return terminar(envio, false, 'tempo esgotado (' + (envio.etapa || 'abrindo a conversa') + ')');
      if (est === 'invalido') return terminar(envio, false, 'número não está no WhatsApp ou é inválido');
      if (est === 'qr') return terminar(envio, false, 'WhatsApp Web desconectado (precisa escanear o QR code)');
      if (!envio.clicou) {
        if (est !== 'pronto') return;
        salvar(envio, {clicou: Date.now(), etapa: 'enviando o texto'});
        await esperar(800);
        clicarEnviar();
        return;
      }
      if (!envio.textoOk) {
        if (est === 'conversa') return envio.arquivos ? salvar(envio, {textoOk: Date.now(), etapa: 'colando as imagens'}) : terminar(envio, true);
        if (Date.now() - envio.clicou > 15000) return terminar(envio, false, 'a mensagem ficou na caixa de texto e não foi enviada');
        return;
      }
      if (!envio.colou || (!envio.midiaClicou && !botaoEnviarMidia() && Date.now() - envio.colou > 7000)) {  // imagens do ticket e da câmera
        const n = envio.colou ? (envio.forma || 0) + 1 : 0;
        if (n >= FORMAS.length) return terminar(envio, false, 'não achei o botão Enviar da prévia das imagens (botões: ' + rotulos(document.body).filter(x => /envi|send/i.test(x)).join(' ¦ ').slice(0, 600) + ')');
        await esperar(1000);
        const lista = await pedir('whatsapp/arquivos?id=' + envio.id);
        if (!Array.isArray(lista) || !lista.length) return terminar(envio, false, 'imagens não encontradas no sistema');
        await porArquivos(lista.map(a => new File([Uint8Array.from(atob(a.dados), c => c.charCodeAt(0))], a.nome, {type: a.tipo})), FORMAS[n]);
        return salvar(envio, {colou: Date.now(), forma: n, etapa: 'abrindo a prévia das imagens (' + FORMAS[n] + ')'});
      }
      if (!envio.midiaClicou) {
        const botao = botaoEnviarMidia();
        if (botao) {
          await esperar(1000);
          botao.click();
          return salvar(envio, {midiaClicou: Date.now(), etapa: 'enviando as imagens'});
        }
        return;
      }
      if (!botaoEnviarMidia()) return terminar(envio, true);  // a prévia fechou: imagens enviadas
      if (Date.now() - envio.midiaClicou > 30000) return terminar(envio, false, 'as imagens ficaram na prévia e não foram enviadas');
      return;
    }
    const livre = ['conectado', 'conversa', 'pronto'].includes(est);
    // com um aviso guardado só avisa o sistema que a aba está viva; senão pede o próximo
    const r = await pedir('whatsapp/proximo?estado=' + est + (guardado || !livre ? '&so_estado=1' : ''));
    if (r.diag) return pedir('whatsapp/diag', await diagnostico());
    const prox = guardado || (r.id ? r : null);
    if (!prox || !livre) return;
    // não atrapalha quem está digitando: espera até 1 minuto a caixa de texto ficar vazia
    if (est === 'pronto' && (esperandoDesde ||= Date.now()) > Date.now() - 60000) { guardado = prox; return; }
    guardado = null; esperandoDesde = 0;
    sessionStorage.setItem(CHAVE, JSON.stringify({id: prox.id, arquivos: prox.arquivos || 0, desde: Date.now()}));
    modoEnvio(true);
    location.href = 'https://web.whatsapp.com/send?phone=' + prox.numero + '&text=' + encodeURIComponent(prox.texto);
  } finally {
    ocupado = false;
  }
}
// o fundo da extensão chama a cada 2 s (os relógios da própria aba atrasam em segundo plano)
chrome.runtime.onMessage.addListener((m, _de, responder) => {
  if (m.tipo !== 'ciclo') return;
  ciclo().finally(() => responder(true));
  return true;
});
