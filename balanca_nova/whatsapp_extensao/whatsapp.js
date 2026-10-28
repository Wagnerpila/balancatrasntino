// Roda dentro da aba do WhatsApp Web. A cada 2 s pergunta ao sistema da balança se há aviso
// para mandar; se houver, abre a conversa com o texto pronto (web.whatsapp.com/send?...) e
// clica em Enviar. O envio em andamento fica no sessionStorage porque a página recarrega.
const CHAVE = 'balanca_envio';
const $ = s => document.querySelector(s);

function pedir(caminho, corpo) {
  return new Promise(ok => chrome.runtime.sendMessage({caminho, corpo}, r => ok(r || {})));
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

async function terminar(envio, ok, erro) {
  sessionStorage.removeItem(CHAVE);
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
      if (Date.now() - envio.desde > 90000) return terminar(envio, false, 'o WhatsApp Web não abriu a conversa a tempo');
      if (est === 'invalido') return terminar(envio, false, 'número não está no WhatsApp ou é inválido');
      if (est === 'qr') return terminar(envio, false, 'WhatsApp Web desconectado (precisa escanear o QR code)');
      if (est === 'pronto' && !envio.clicou) {
        envio.clicou = Date.now(); sessionStorage.setItem(CHAVE, JSON.stringify(envio));
        await new Promise(r => setTimeout(r, 800));
        clicarEnviar();
      } else if (envio.clicou && est === 'conversa') {
        return terminar(envio, true);
      } else if (envio.clicou && Date.now() - envio.clicou > 15000) {
        return terminar(envio, false, 'a mensagem ficou na caixa de texto e não foi enviada');
      }
      return;
    }
    const livre = ['conectado', 'conversa', 'pronto'].includes(est);
    // com um aviso guardado só avisa o sistema que a aba está viva; senão pede o próximo
    const r = await pedir('whatsapp/proximo?estado=' + est + (guardado || !livre ? '&so_estado=1' : ''));
    const prox = guardado || (r.id ? r : null);
    if (!prox || !livre) return;
    // não atrapalha quem está digitando: espera até 1 minuto a caixa de texto ficar vazia
    if (est === 'pronto' && (esperandoDesde ||= Date.now()) > Date.now() - 60000) { guardado = prox; return; }
    guardado = null; esperandoDesde = 0;
    sessionStorage.setItem(CHAVE, JSON.stringify({id: prox.id, desde: Date.now()}));
    location.href = 'https://web.whatsapp.com/send?phone=' + prox.numero + '&text=' + encodeURIComponent(prox.texto);
  } finally {
    ocupado = false;
  }
}
setInterval(ciclo, 2000);
