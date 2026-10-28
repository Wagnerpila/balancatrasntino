# Sistema de Pesagem – Balança Transtino (versão nova)

## Como abrir
Dê **dois cliques em `INICIAR.bat`** (ou no atalho "Pesagem Transtino" da Área de Trabalho).
O navegador abre sozinho em **http://127.0.0.1:8090/**. Para encerrar, feche a janela preta.

Não precisa de VS Code, do venv nem de `python manage.py runserver`; só do Python que já está instalado.
O sistema antigo (Django, porta 8000) continua funcionando ao mesmo tempo.

## O que aproveita do projeto antigo
| Item | Onde fica | Como o sistema novo usa |
|---|---|---|
| Cadastros (veículo + motorista) | `balanca/db.sqlite3` → tabela `pesagem_cliente` | Lê e edita direto (aba **Cadastros**) |
| TARA do veículo | campo `peso_maximo` do cadastro | Botão "Usar TARA do cadastro" |
| Tag do motorista | `user_id` = nome no InControl (ex.: `DOMINGOS - 41`), `card_no` = número (41) | Campo "Identificar" e leitura automática |
| Peso da balança | API local do indicador WT3000: `http://127.0.0.1:80/peso/?fmt=1` | Display ao vivo + botões "⚖ Balança" |
| Histórico | tabela `pesagem_pesagem` | Aba **Histórico antigo**; tickets encerrados também são gravados lá |

Os tickets novos ficam na tabela `nova_ticket` do mesmo banco.

## Como as tags funcionam
1. O caminhão passa pela leitora e o controlador Intelbras CT-3000 lê a tag RFID.
2. O InControl (https://localhost:4445) registra o evento no **Log de Eventos** com o nome do usuário, ex.: `DOMINGOS - 41`.
3. No cadastro, esse mesmo texto está em `user_id`. Antes, o `automacao.py` copiava esse nome com o mouse e colava no ticket.

No sistema novo há duas formas de identificar:
- **Manual:** cole ou digite `DOMINGOS - 41`, `41`, a placa ou o nome e clique em **Identificar**.
- **Automática:** em **Configurações → Leitura de tags**, marque a opção, informe usuário e senha do InControl e clique em **Testar leitura**.
  A API é `https://localhost:4441/v1/` (login em `/v1/auth/`, eventos em `/v1/evento/`).

## Empresas com vários caminhões
Cada caminhão é um cadastro próprio, e o nome termina com um número (`JOAO ARTUR ARGENTA 07`, `ROBERTO BETO - 86`).
O sistema tira esse número e agrupa os cadastros pela empresa.
- Escolha a empresa em **"Empresas com vários caminhões"** ou digite o nome dela na busca (aparece com 🏢).
- Abre a grade de caminhões da empresa: clique no que vai pesar agora. Dá para filtrar por placa, modelo ou motorista.
- Caminhão com **"NO PÁTIO"** já tem a 1ª pesagem: ao clicar nele, abre o ticket para finalizar.
- Depois de identificar pela tag, o botão **"Trocar caminhão"** mostra os outros caminhões da mesma empresa.
- Quando o caminhão tem **empresa vinculada** (veja abaixo), ele é agrupado por ela. Sem vínculo, vale o agrupamento automático pelo nome.

## Motorista × Empresa × Cobrança
- **Motoristas** (aba Motoristas): um cadastro por motorista/caminhão. Cada um pode ter uma **empresa vinculada**, escolhida do cadastro de empresas (não é texto livre).
  Também define **quem paga**: *a empresa* (o motorista presta serviço para ela) ou *o próprio motorista*.
- **Empresas** (aba Empresas): nome, CNPJ/CPF, telefone, e-mail, contato, endereço e tabela de valor. A empresa pode ser desativada.
- **Na pesagem**, ao escolher o motorista:
  - a empresa vinculada aparece em destaque (🏢 MARCOS GERALDO SPELTZ) e vem selecionada, junto com "Cobrar de: Empresa";
  - dá para trocar a empresa ou cobrar do motorista **só naquela pesagem**. Aparece o aviso "trocada só nesta pesagem".
- **O ticket** registra o par motorista + empresa e quem paga. No ticket impresso:
  - "EMPRESA / CLIENTE" e "Cobrança" ficam em destaque no alto;
  - o motorista aparece em campo separado.
- **Tickets antigos** (feitos antes desta versão) seguem a empresa do cadastro do caminhão.

## Valores (tabela de preços)
Aba **Valores**. Há três tipos:
- **Por pesagem:** valor fixo a cada pesagem.
- **Por tonelada:** valor × toneladas de peso líquido.
- **Pacote mensal:** mensalidade com N pesagens incluídas (0 = ilimitado). Cada pesagem além disso paga o "valor excedente".

Quem não tem tabela própria usa a tabela marcada como **padrão**. A tabela pode ser ligada à empresa ou ao motorista que paga por conta própria.

Na pesagem, o campo **Valor da pesagem (R$)** permite digitar um valor manual. Ele vale só para aquela pesagem e não conta na franquia do pacote.

## Faturamento
Aba **Faturamento**: escolha o período e o sistema monta um bloco por **quem paga** (empresa ou motorista).
- Cada bloco mostra:
  - os motoristas que trabalharam para ela, com placas, pesagens, kg e valor;
  - as mensalidades do pacote;
  - cada pesagem com o valor e a regra usada.
- **Imprimir fechamento** gera uma folha A4 com espaço para assinatura. **Excel (CSV)** exporta tudo.
- **Gerar fatura** grava a fatura:
  - as pesagens dela ficam marcadas e não entram de novo no "a faturar";
  - em "Faturas geradas" dá para reimprimir, **marcar como paga** ou excluir (as pesagens voltam para o "a faturar");
  - pacotes mensais: uma mensalidade por mês do período.
- Em **Relatórios** também dá para filtrar e agrupar por **empresa, motorista ou quem paga**.

## Organizar cadastros antigos
Na aba **Empresas → Organizar cadastros antigos**. Antes de cada ação o sistema faz um backup do banco. Nada é apagado.
1. **Empresa escrita junto do nome** (ex.: `PAULO GOTE ( DOMINGOS )`, `MARCOS GERALDO SPELTZ` com cartão `DOMINGOS`):
   - o sistema sugere quem é o motorista e quem é a empresa, usando o nome do cartão/tag;
   - confira (⇄ inverte) e clique em **Separar**;
   - o nome original fica guardado, e **Desfazer** volta como era.
2. **Mesmo caminhão cadastrado mais de uma vez** (mesma placa):
   - escolha qual cadastro fica (normalmente o que tem a tag) e, se quiser, a empresa;
   - os outros ficam **ocultos** (aba Motoristas → "mostrar ocultos" → Reativar);
   - campos vazios do cadastro que fica (tag, TARA…) são completados com os dados do outro;
   - se a placa trocou de dono, clique em "São diferentes".
3. **Frotas sem empresa** (ex.: JOAO ARTUR ARGENTA 07, 08…): cria a empresa e vincula todos os caminhões de uma vez.

**Banco de dados:**
- As tabelas do Django não mudam de estrutura.
- Tabelas novas: `nova_empresa`, `nova_motorista` (vínculo, quem paga, cadastro oculto, nome original), `nova_plano`, `nova_fatura`, `nova_fatura_item` e `nova_migracao_ignorar`.
- A tabela `nova_ticket` ganhou as colunas `empresa_id`, `empresa_nome`, `pagador`, `pagador_nome` e `valor_manual`.
- Ao abrir esta versão pela primeira vez é feito um backup `..._antes_atualizacao`.

## Pesagem
- **Pesagem completa agora:** identifique o veículo, preencha o peso inicial (balança, TARA do cadastro ou digitado) e o final, depois clique em **Encerrar e imprimir**.
- **Em duas etapas (entrada/saída):** salve a 1ª pesagem (o ticket fica **aberto**). Na saída, abra o ticket em **Tickets abertos**, capture o peso final e encerre.
- **Peso líquido** = maior peso − menor peso (bruto − tara), calculado na hora.
- **Diferença de origem:** informe o peso da NF para ver a diferença em kg e %.

## Dashboard
Aba **Dashboard**: painel com tudo do sistema, para os períodos de 7 dias, 30 dias, 90 dias ou 12 meses. Atualiza sozinho a cada minuto.
- **Indicadores:**
  - peso líquido e pesagens no período, com a variação em relação ao período anterior;
  - média por pesagem, hoje, este mês e caminhões no pátio;
  - total de cadastros e empresas, e o total desde o início.
- **Gráficos:**
  - peso líquido por dia;
  - toneladas por mês (12 meses);
  - mapa de calor com os horários de pico (dia da semana × hora);
  - rankings de empresas, itens e caminhões.

  Passe o mouse para ver os valores. O botão **Tabela** mostra os números do gráfico.
- **Sistema:** situação da balança, das tags, do backup e do banco.
- **Qualidade dos cadastros:** cadastros sem TARA, placas repetidas e cadastros sem número de tag. O botão **Ver** abre o cadastro.
- **Pátio:** clique num caminhão que está no pátio para finalizar o ticket dele.

## Relatórios
Aba **Relatórios**: filtro por período (atalhos Hoje, Ontem, 7 dias, Este mês, Mês passado e 30 dias), por **empresa** e por placa, motorista ou item.
- Mostra os totais, um resumo por empresa (clique numa empresa para filtrar), um resumo por dia e a lista de pesagens.
- Junta as pesagens do sistema antigo e os tickets do novo, sem contar duas vezes.
- **Imprimir relatório** imprime em A4. **Exportar Excel (CSV)** gera um arquivo que abre direto no Excel, com acentos e colunas certas.

## Editar e excluir
- **Tickets:** na aba Tickets (e nos cartões de Tickets abertos) há os botões **✏️ Editar** e **🗑️ Excluir**.
  Na edição dá para corrigir placa, motorista, item, pesos, datas, operadores, NF, local e observação. O peso líquido é recalculado.
  Se o ticket estiver encerrado, a cópia dele no histórico antigo é corrigida junto, e há o botão "Salvar e reimprimir".
  Excluir apaga o ticket e a cópia no histórico antigo. Os números de ticket não são reaproveitados.
- **Cadastros:** na aba Cadastros, os botões **✏️ Editar**, **⚖ Pesar** e **🗑️ Excluir** ficam na primeira coluna. Clicar em qualquer parte da linha também abre a edição.
  Dá para editar nome, placa, empresa, nome e número da tag, motorista, modelo, TARA, ano, tipo e descrição da carga, CNPJ, telefone e e-mail. Na tela de pesagem, o botão **✏️ Editar cadastro** abre o cadastro do caminhão selecionado.
  Excluir um cadastro não apaga os tickets já feitos com ele.
- **Histórico antigo:** cada pesagem tem **✏️ Editar** e **🗑️ Excluir**. Dá para corrigir placa, data e hora, nome, modelo, e-mail, TARA e peso final.
  O líquido é recalculado como peso final − TARA, a mesma conta do sistema antigo, e a mudança aparece também nos relatórios do Django.
  Se a pesagem foi gerada por um ticket do sistema novo ("sistema novo" na coluna Origem), os botões abrem o próprio ticket, para os dois não ficarem diferentes.

## Backup automático
- Fica **ligado** por padrão. Faz uma cópia de `balanca\db.sqlite3` **ao abrir o sistema** (se o último backup já passou do intervalo) e depois **a cada 6 horas**.
  A cópia usa a API de backup do SQLite, segura mesmo com o sistema em uso. Depois de cada backup o arquivo é conferido.
- Os arquivos ficam em `balanca_nova\backups\` com o nome `db_AAAA-MM-DD_HH-MM-SS.sqlite3`.
  **Recomendado:** em Configurações → Backup, apontar a pasta para outro disco ou pendrive (ex.: `D:\Backups\Balanca`).
  Assim os backups não se perdem se o disco do computador estragar.
- São guardados os **60 automáticos** mais recentes (cerca de 15 dias). Os **"Antes de restaurar"** guardam os 10 últimos. Os **manuais** nunca são apagados.
- O indicador **Backup** no topo fica verde quando está em dia, amarelo quando está atrasado e vermelho quando deu erro. Clicar nele abre o painel.
- No painel: **Fazer backup agora**, **⬇ Baixar**, **↩ Restaurar** e **🗑️ Excluir**.
  Antes de restaurar, o sistema confere se o arquivo é um banco válido e faz um backup do estado atual, para poder desfazer.
- Como o backup roda dentro deste sistema, ele só acontece com o sistema aberto.

## Câmera da balança e leitura de placa
- Câmera Ekaza em `192.168.100.29` (é uma câmera Tuya, a mesma do app Smart Life). O sistema pega o vídeo dela por **RTSP**.
- **Leitor de placas:** fast-alpr (gratuito, código aberto). Roda **neste computador**, sem internet, sem limite de leituras.
  A câmera só manda o vídeo. Lê as placas antigas (ABC1234) e as Mercosul (ABC1D23).
  A placa Mercosul acha o cadastro da placa antiga do mesmo caminhão (APZ9B71 = APZ-9171).
- Instalação: dois cliques em `INSTALAR_CAMERA.bat` (cria a pasta `lpr_venv`; já foi instalado em 28/10/2026).
- Ligar em **Configurações → Câmera da balança**: endereço RTSP, usuário e senha, depois **Testar câmera**.
- Como funciona na pesagem:
  1. O peso passa de **100 kg** (ajustável), a câmera aparece embaixo do display da balança.
  2. A placa é lida. Se há ticket aberto dessa placa, ele é carregado para a 2ª pesagem; se não, o cadastro é puxado.
  3. Com **Pesagem automática** ligada: quando o peso fica **ESTÁVEL** por 3 segundos, o peso é capturado.
     O sistema mostra uma contagem de **5 segundos** com o botão **✋ Cancelar automático**.
     Depois **encerra o ticket sozinho**. Ele não imprime, a menos que "Imprimir o ticket na pesagem automática" esteja marcado.
- Depois de encerrar sozinho, a pesagem **fica na tela**, travada e com o botão "🖨️ Imprimir ticket", até o veículo sair da balança.
  Quando um veículo sobe, o sistema vai sozinho para a aba Pesagem.
- **Foto no ticket:** ao encerrar um ticket com a câmera ligada, a imagem dela é guardada em `balanca_nova\fotos\ticket_<nº>.jpg`.
  Por padrão a foto **não sai na impressão**. Para sair, marque **📷 Imprimir com a foto** (ao lado de "Encerrar e imprimir")
  ou use o botão **📷 Com foto** na aba Tickets. A pasta `fotos` não entra no backup do banco.
- **Impressão automática:** ao encerrar sozinha, a pesagem é impressa **direto na impressora** escolhida em Configurações → Geral (EPSON L395 Series), sem abrir janela.
  O número de cópias segue "Vias por impressão". Por dentro, o Chrome sem tela monta a imagem do ticket e o `imprimir_ticket.ps1` manda para a impressora.
  Liga e desliga em Configurações → Câmera → "Imprimir o ticket na pesagem automática".
- **Alertas para o operador** (faixa vermelha com bip no alto da tela de pesagem). Em todos os casos a pesagem é finalizada à mão:
  placa não lida depois de 20 tentativas, câmera fora do ar, placa sem cadastro, cadastro sem TARA,
  peso que não estabiliza em 90 s, pesagem que não salvou e ticket que não imprimiu.
- **Log de falhas:** tudo isso é gravado em `balanca_nova\logs\falhas.log` e aparece em Configurações → "Log de falhas".
- **Cadastro sincronizado com a pesagem:** ao salvar o cadastro do caminhão que está na tela de pesagem, em qualquer aba,
  a pesagem é atualizada na hora: placa, motorista, empresa, cobrança, item e TARA. O líquido é recalculado e o peso já capturado continua.
  Se o automático tinha parado por placa sem cadastro ou cadastro sem TARA, ele volta sozinho enquanto o veículo estiver na balança.
  Uma pesagem já encerrada (travada na tela) não muda.
- **Pesagem única** (padrão; desliga em Configurações → Geral): a TARA vem do cadastro e o peso da balança já é o final.
  Líquido = peso − TARA, sem 2ª pesagem. Cadastro sem TARA: o sistema captura o peso e espera o operador informar a TARA.
  Os tickets que já estavam abertos continuam sendo finalizados normalmente (pelo quadro "No pátio" ou pela câmera).
  4. Placa sem cadastro: preenche a placa e busca, e o operador termina à mão. Nada é salvo sozinho.
  5. Se a tela já tem outra placa preenchida, a câmera não apaga nada e mostra o botão **Usar placa lida**.
     Se for a mesma placa, segue o automático.
- **No pátio:** a tela de pesagem lista os tickets abertos, que estão esperando a 2ª pesagem.
  **✅ Finalizar** carrega o ticket ali mesmo e já pega o peso, se o caminhão estiver na balança.
- **Faturas:** em Faturamento → Faturas geradas, use **✏️ Editar** para mudar valores, situação e observação.
  Desmarcar uma pesagem tira ela da fatura, e ela volta para o "a faturar". **🗑️ Excluir** apaga a fatura e as pesagens também voltam.
- **Faturamento (abrindo um pagador):** cada pesagem tem **✏️** (editar) e **🗑️** (excluir).
  A exclusão fica bloqueada se a pesagem já estiver numa fatura; nesse caso, tire-a da fatura antes.
- **Histórico antigo → PDF para o cliente:** marque as pesagens (☑) na lista. A seleção continua mesmo trocando a busca.
  Na barra azul, confira o nome do cliente e o valor, depois clique em **📄 Gerar PDF das selecionadas**.
- **Cobrança pelo histórico:** na aba Histórico antigo, digite a empresa, o motorista ou a placa e escolha o período.
  Marque as pesagens e use **📄 Gerar PDF de cobrança** (na janela de impressão, escolha "Salvar como PDF").
  A empresa vem do cadastro da placa. Essa cobrança não cria fatura.
- Funcionamento por dentro: `servidor.py` inicia o programa `camera_lpr.py` (porta 8092, só neste computador).
  Esse programa fecha sozinho quando o sistema é fechado.

## Impressão
Usa a impressora padrão do Windows pela janela de impressão do navegador. O ticket segue o modelo manual,
com uma via por folha (o número de vias fica em Configurações).
Para imprimir **sem abrir a janela**, marque "Impressão direta" em Configurações e reinicie o sistema
(o Chrome passa a abrir com `--kiosk-printing` e imprime direto na impressora padrão).

## Configuração
Fica em `config.json`: porta, caminho do banco, URL da balança, nome da empresa, vias e InControl.
