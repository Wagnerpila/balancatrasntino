from django.shortcuts import render, redirect, get_object_or_404
from .models import Cliente, Ticket_pesagem, Veiculo_pesagem, Pesagem
from django.http import JsonResponse
import json
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.timezone import now
from django.utils import timezone
import serial, re
from .models import EventoAcesso, AccessEvents
from django.http import JsonResponse
from datetime import datetime, time
from django.conf import settings
import serial.tools.list_ports
import requests
from django.http import HttpResponse
from .forms import UserForm
import pyautogui
import time

# Configurações da API Intelbras
device_ip = '192.168.100.80'
username = 'admin'
try:  # senha fica em balanca/segredos.py (fora do Git)
    from balanca.segredos import DEVICE_PASSWORD as password
except ImportError:
    password = ''
url_base = "http://{}/cgi-bin/recordFinder.cgi".format(device_ip)
digest_auth = requests.auth.HTTPDigestAuth(username, password)

API_BASE_URL = f"http://{device_ip}/cgi-bin"
LOCAL_API_URL = "http://127.0.0.1:80/peso/?fmt=1"
FLASK_SERVER_URL = "http://localhost:3000"  # URL do servidor Flask

def get_user_by_cardno(card_no):
    url = f"http://{device_ip}/cgi-bin/AccessCard.cgi?action=list&CardNoList[0]={card_no}"
    digest_auth = requests.auth.HTTPDigestAuth(username, password)
    try:
        response = requests.get(url, auth=digest_auth, timeout=20, verify=False)
        if response.status_code == 200:
            result = {}
            for line in response.text.splitlines():
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
            return result
        return {"error": f"Erro na API: {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def user_search_view(request):
    card_no = request.GET.get("card_no")
    user_data = None
    if card_no:
        user_data = get_user_by_cardno(card_no)
    return render(request, 'pesagem/user_search.html', {'user_data': user_data})

def verificar_conexao_balanca():
    # Listar portas COM disponíveis e verificar conexão com a balança
    portas = serial.tools.list_ports.comports()
    for porta in portas:
        if "COM3" in porta.device:  
            try:
                with serial.Serial(porta.device, baudrate=9600, timeout=1) as ser:
                    return True
            except serial.SerialException:
                return False
    return False

def detectar_porta_balanca(messages_list):
    portas_disponiveis = serial.tools.list_ports.comports()
    for porta in portas_disponiveis:
        try:
            with serial.Serial(porta.device, baudrate=9600, timeout=1) as ser:
                ser.flush()
                if ser.in_waiting > 0:
                    peso = ser.readline().decode('utf-8').strip()
                    messages_list.append(f"Balança detectada na porta {porta.device}")
                    return porta.device
        except (serial.SerialException, ValueError):
            continue
    messages_list.append("Nenhuma balança detectada.")
    return None

def cadastro_view(request):
    if request.method == "POST":
        # Obter os dados do formulário
        nome = request.POST.get("cliente")
        cnpj = request.POST.get("cnpj")
        telefone = request.POST.get("telefone")
        email = request.POST.get("email")
        placa = request.POST.get("placa")
        modelo = request.POST.get("modelo")
        peso_maximo = request.POST.get("peso")
        ano_fabricacao = request.POST.get("ano")
        tipo_carga = request.POST.get("tipo-carga")
        peso_carga = request.POST.get("peso-carga")
        descricao_carga = request.POST.get("descricao-carga")
        # Dados do Card
        card_no = request.POST.get("card_no")
        user_id = request.POST.get("user_id")
        card_type = request.POST.get("card_type")
        card_name = request.POST.get("card_name")
        card_status = request.POST.get("card_status")


        # Criar um novo registro no banco
        Cliente.objects.create(
            nome=nome,
            cnpj=cnpj,
            telefone=telefone,
            email=email,
            placa=placa,
            modelo=modelo,
            peso_maximo=peso_maximo,
            ano_fabricacao=ano_fabricacao,
            tipo_carga=tipo_carga,
            peso_carga=peso_carga,
            descricao_carga=descricao_carga,
            card_no=card_no,
            user_id=user_id,
            card_type=card_type,
            card_name=card_name,
            card_status=card_status,
        )

        return redirect("cadastro_sucesso")  # Redirecionar para uma página de sucesso

    return render(request, "pesagem/cadastro.html")

def cadastro_sucesso(request):
    return render(request, "pesagem/cadastro_sucesso.html")

def listar_clientes_view(request):
    """
    Exibe a lista de clientes cadastrados.
    """
    clientes = Cliente.objects.all()
    return render(request, 'pesagem/listar_clientes.html', {'clientes': clientes})

def editar_cliente_view(request, cliente_id):
    """
    Permite editar as informações de um cliente.
    """
    cliente = get_object_or_404(Cliente, id=cliente_id)

    if request.method == "POST":
        cliente.nome = request.POST.get("nome")
        cliente.cnpj = request.POST.get("cnpj")
        cliente.telefone = request.POST.get("telefone")
        cliente.email = request.POST.get("email")
        cliente.placa = request.POST.get("placa")
        cliente.modelo = request.POST.get("modelo")
        cliente.peso_maximo = request.POST.get("peso_maximo")
        cliente.ano_fabricacao = request.POST.get("ano_fabricacao")
        cliente.tipo_carga = request.POST.get("tipo_carga")
        cliente.peso_carga = request.POST.get("peso_carga")
        cliente.descricao_carga = request.POST.get("descricao_carga")
        cliente.card_no = request.POST.get("card_no")
        cliente.user_id = request.POST.get("user_id")
        cliente.card_type = request.POST.get("card_type")
        cliente.card_name = request.POST.get("card_name")
        cliente.card_status = request.POST.get("card_status")

        cliente.save()
        return redirect('listar_clientes')

    return render(request, 'pesagem/editar_cliente.html', {'cliente': cliente})

def deletar_cliente_view(request, cliente_id):
    """
    Exclui um cliente do banco de dados.
    """
    cliente = get_object_or_404(Cliente, id=cliente_id)
    cliente.delete()
    return redirect('listar_clientes')

def ler_tag_rfid(messages_list):
    """
    Busca o último registro de acesso no dispositivo, verifica se o número do cartão
    está cadastrado no banco de dados e retorna os dados do veículo associado.
    """
    try:
        # Configuração para buscar o último registro
        offset = 0  # Sempre buscar os registros mais recentes
        count = 1   # Apenas o último registro
        url = f"http://{device_ip}/cgi-bin/recordFinder.cgi?action=find&name=AccessControlCardRec&offset={offset}&count={count}"
        
        # Requisição para a API
        response = requests.get(url, auth=digest_auth, timeout=10, verify=False)
        response.raise_for_status()
        
        # Verificar se houve resposta
        dados = response.text.strip()
        if not dados:
            messages_list.append("Nenhum registro encontrado na API.")
            return None
        
        # Processar o texto para extrair o último registro
        registros = {}
        for linha in dados.splitlines():
            if '=' in linha:
                chave, valor = linha.split('=', 1)
                registros[chave.strip()] = valor.strip()
        
        # Pegar informações do último registro
        ultimo_registro = { 
            "id": registros.get("records[0].RecNo", "N/A"),
            "data_hora": datetime.utcfromtimestamp(int(registros.get("records[0].CreateTime", "0"))).strftime('%d/%m/%Y %H:%M:%S'),
            "tipo": registros.get("records[0].Type", "N/A"),
            "cartao": registros.get("records[0].CardNo", "N/A"),
            "usuario": registros.get("records[0].CardName", "N/A"),
        }

        # Verificar se o cartão está cadastrado no banco de dados
        veiculo = Veiculo_pesagem.objects.filter(tag_rfid=ultimo_registro["cartao"]).first()
        if veiculo:
            # Adicionar informações do veículo ao registro
            ultimo_registro.update({
                "placa": veiculo.placa,
                "modelo": veiculo.modelo,
                "cor": veiculo.cor,
                "cadastrado_em": veiculo.cadastrado_em.strftime('%d/%m/%Y %H:%M:%S'),
                "user_name": veiculo.user_name,
                "user_email": veiculo.user_email,
            })
            messages_list.append(f"Veículo encontrado: {veiculo.placa} (Cartão: {ultimo_registro['cartao']})")
        else:
            messages_list.append(f"Cartão {ultimo_registro['cartao']} não está cadastrado no sistema.")
        
        return ultimo_registro

    except requests.RequestException as e:
        messages_list.append(f"Erro ao acessar a API: {str(e)}")
        return None




def ler_tag_view(request):
    messages_list = []
    
    # Obter o último registro de acesso
    ultimo_acesso = ler_tag_rfid(messages_list)
    
    return render(request, 'pesagem/sistema.html', {
        'messages': messages_list,
        'ultimo_acesso': ultimo_acesso,
    })

import requests
from django.shortcuts import render
from django.http import JsonResponse

FLASK_BASE_URL = "http://127.0.0.1:3000"  # URL do servidor Flask

def registros_recentes(request):
    """
    View para buscar registros recentes do servidor Flask e exibi-los no frontend.
    """
    try:
        # Chama o endpoint do Flask
        response = requests.get(f"{FLASK_BASE_URL}/registros_recentes")
        response.raise_for_status()
        data = response.json()  # Converte para JSON

        if data["status"] == "success":
            registros = data["data"]  # Lista de registros formatados
        else:
            registros = []
    except requests.RequestException as e:
        registros = []  # Caso haja erro na comunicação com o Flask
        print(f"Erro ao conectar ao servidor Flask: {e}")

    # Renderiza o template com os registros
    return render(request, "pesagem/registros_recentes.html", {"registros": registros})

def evento_mais_recente(request):
    """
    View para buscar o evento mais recente do servidor Flask.
    """
    try:
        # Chama o endpoint do Flask
        response = requests.get(f"{FLASK_BASE_URL}/evento_mais_recente")
        response.raise_for_status()
        data = response.json()

        if data["status"] == "success":
            evento = data["most_recent_event"]
        else:
            evento = None
    except requests.RequestException as e:
        evento = None
        print(f"Erro ao conectar ao servidor Flask: {e}")

    return JsonResponse({"evento": evento})


from django.shortcuts import render
import requests

def abrir_cancela(messages_list):
    channel = 2
    try:
        url = f"http://{device_ip}/cgi-bin/accessControl.cgi?action=openDoor&channel={channel}"
        response = requests.post(url, auth=digest_auth, timeout=10, verify=False)
        response.raise_for_status()  # Gera exceção se o status não for 2xx
        messages_list.append("Cancela de saida aberta.")
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 401:
            messages_list.append("Erro 401: Credenciais incorretas para autenticação.")
        else:
            messages_list.append(f"Erro HTTP ao abrir a cancela de saida: {http_err}")
    except requests.RequestException as e:
        messages_list.append(f"Erro de rede ao abrir a cancela de saida: {str(e)}")

#cancela de entrada
def fechar_cancela(messages_list):
    channel = 1  # Canal usado para fechar a cancela
    try:
        # Tentativa de usar openDoor no canal de fechamento
        url = f"http://{device_ip}/cgi-bin/accessControl.cgi?action=openDoor&channel={channel}"
        response = requests.post(url, auth=digest_auth, timeout=10, verify=False)
        response.raise_for_status()  # Verifica se o status da resposta é 2xx
        messages_list.append("Cancela de entrada aberta com sucesso.")
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 401:
            messages_list.append("Erro 401: Credenciais incorretas para autenticação.")
        else:
            messages_list.append(f"Erro HTTP ao abrir a cancela de entrada: {http_err}")
    except requests.RequestException as e:
        messages_list.append(f"Erro de rede ao fechar a cancela: {str(e)}")

    


def fechar_cancela_view(request):
    messages_list = []
    fechar_cancela(messages_list)
    return JsonResponse({'messages': messages_list})


def pesar_veiculo(messages_list, use_api=False):
    if use_api:
        try:
            url = LOCAL_API_URL
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok" and data.get("is_stable", False):
                peso = data.get("gross")
                if peso is not None:
                    messages_list.append(f"Peso registrado via API: {peso} {data.get('unity', 'kg')}")
                    return int(peso) if isinstance(peso, (int, float)) else None
                else:
                    messages_list.append("API retornou um peso nulo ou inválido.")
                    return None
            else:
                messages_list.append("Peso instável ou erro na resposta da API.") #se houver um erro na balanxa envie um email para wagner
                return None
        except requests.RequestException as e:
            messages_list.append(f"Erro ao acessar a API de pesagem: {str(e)}")
            return None

    else:
        porta_balanca = detectar_porta_balanca(messages_list)
        if not porta_balanca:
            messages_list.append("Falha ao detectar a porta da balança.")
            return None

        try:
            with serial.Serial(porta_balanca, baudrate=9600, timeout=1) as ser:
                ser.flush()
                if ser.in_waiting > 0:
                    peso = ser.readline().decode('utf-8').strip()
                    peso = int(peso)
                    messages_list.append(f"Peso registrado: {peso} Kg")
                    return peso
                else:
                    messages_list.append("Falha ao ler o peso da balança.")
                    return None
        except (serial.SerialException, ValueError) as e:
            messages_list.append(f"Erro na leitura da balança: {str(e)}")
            return None


def abrir_cancela_view(request):
    messages_list = []
    abrir_cancela(messages_list)
    return JsonResponse({'messages': messages_list})



def enviar_email_pesagem(veiculo, peso_inicial, peso_final, messages_list):
    if veiculo.email:
        try:
            subject = f"Pesagem Concluída para o veículo {veiculo.placa}"
            email_content = render_to_string('pesagem/sistema.html', {
                'veiculo': veiculo,
                'peso_inicial': peso_inicial,
                'peso_final': peso_final or "-",
                'data': timezone.now().strftime('%d/%m/%Y'),
                'hora': timezone.now().strftime('%H:%M:%S'),
            })

            send_mail(
                subject,
                email_content,
                settings.DEFAULT_FROM_EMAIL,  
                [veiculo.email],  
                fail_silently=False,
            )
            messages_list.append(f"E-mail enviado para {veiculo.email}")
        except Exception as e:
            messages_list.append(f"Erro ao enviar e-mail: {str(e)}")


def obter_eventos_acesso(messages_list, offset=0, count=10):
    """
    Função para obter eventos de acesso a partir do servidor Flask e armazenar no banco de dados.
    """
    try:
        # URL para obter eventos de acesso
        url = f"{FLASK_SERVER_URL}/eventos"
        
        # Dados a serem enviados no corpo da requisição
        payload = {'offset': offset, 'count': count}  # Caso o Flask suporte parametros no body do POST

        # Requisição POST ao servidor Flask
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()  # Lança exceção se o status não for 2xx

        # Processar resposta JSON do servidor Flask
        eventos_flask = response.json()
        eventos = []
        for evento in eventos_flask.get("Events", []):
            # Obter dados do evento
            rec_no = evento.get("RecNo", None)
            if not rec_no:
                continue
            
            data_hora = evento.get("UTC", None)
            data_hora = datetime.utcfromtimestamp(int(data_hora)) if data_hora else None

            # Atualizar ou criar evento no banco de dados
            evento_db = EventoAcesso.objects.update_or_create(
                rec_no=int(rec_no),
                defaults={
                    'data_hora': data_hora,
                    'tipo': evento.get("Type", "Desconhecido"),
                    'cartao': evento.get("CardNo", "N/A"),
                    'usuario': evento.get("CardName", "N/A"),
                },
            )
            eventos.append(evento_db[0])  # Adiciona o objeto retornado

        messages_list.append(f"{len(eventos)} eventos processados e salvos no banco de dados.")
        return eventos

    except requests.RequestException as e:
        messages_list.append(f"Erro ao acessar o servidor Flask: {str(e)}")
        return []



def listar_eventos_completos(request):
    try:
        url = f"{FLASK_SERVER_URL}/eventos"
        response = requests.post(url, timeout=20)
        response.raise_for_status()
        text = response.text

        # Extrai os dados dos registros usando regex.  Esta parte é crucial e depende do formato consistente da resposta.
        records_matches = re.findall(r"records\[(\d+)\]\.(\w+)=([^,]+)", text)

        # Agrupa os dados por índice de registro
        records_data = {}
        for match in records_matches:
            index = int(match[0])
            key = match[1]
            value = match[2]
            if index not in records_data:
                records_data[index] = {}
            records_data[index][key] = value

        # Encontra o registro mais recente com base em CreateTime
        most_recent_record_index = 0
        most_recent_create_time = 0

        for index, record in records_data.items():
            create_time = int(record.get("CreateTime", 0))  # Lidando com casos onde CreateTime pode não existir.
            if create_time > most_recent_create_time:
                most_recent_create_time = create_time
                most_recent_record_index = index

        # Processa o registro mais recente para salvar no banco de dados.
        if most_recent_record_index in records_data:
            most_recent_record = records_data[most_recent_record_index]

            create_time = timezone.datetime.utcfromtimestamp(int(most_recent_record["CreateTime"]))

            # Cria ou atualiza o evento no banco de dados.  Adapte os campos de acordo com seu modelo.
            access_event, created = AccessEvents.objects.update_or_create(
                rec_no=int(most_recent_record["RecNo"]), # Certifique-se de que RecNo é um inteiro.
                defaults={
                    "attendance_state": int(most_recent_record.get("AttendanceState", 0)),
                    "card_no": most_recent_record.get("CardNo"),
                    "card_type": int(most_recent_record.get("CardType", 0)),
                    "create_time": create_time,
                    "door": int(most_recent_record.get("Door", 0)),
                    "error_code": int(most_recent_record.get("ErrorCode", 0)),
                    "method": int(most_recent_record.get("Method", 0)),
                    "password": most_recent_record.get("Password", ""),
                    "reader_id": int(most_recent_record.get("ReaderID", 0)),
                    "rec_no": int(most_recent_record.get("RecNo", 0)), # adicionado para correção
                    "status": int(most_recent_record.get("Status", 0)),
                    "user_id": most_recent_record.get("UserID", ""),
                    "user_type": int(most_recent_record.get("UserType", 0)),
                    # ... outros campos ...
                }
            )
            return JsonResponse({
                "mensagem": f"Evento mais recente salvo com sucesso.",
                "dados": str(access_event)
            })
        else:
            return JsonResponse({"mensagem": "Nenhum evento encontrado."}, status=404)

    except requests.RequestException as e:
        return JsonResponse({"erro": f"Erro ao acessar o servidor Flask: {str(e)}"}, status=500)
    except Exception as e:
        return JsonResponse({"erro": f"Erro ao processar os eventos: {str(e)}"}, status=500)


def listar_eventos_acesso(request):
    """
    View para exibir os últimos 10 eventos de acesso salvos no banco de dados.
    """
    eventos = EventoAcesso.objects.order_by('-data_hora')[:10]  # Últimos 10 eventos
    return render(request, 'pesagem/eventos_acesso.html', {'eventos': eventos})


def eventos_acesso_view(request):
    """
    View para exibir os eventos de acesso obtidos do servidor Flask.
    """
    messages_list = []
    
    # Chamando a função com os parâmetros offset e count (ou os valores padrão)
    offset = int(request.GET.get('offset', 0))  # Obtém o offset da query string (padrão: 0)
    count = int(request.GET.get('count', 10))  # Obtém o count da query string (padrão: 10)

    eventos = obter_eventos_acesso(messages_list, offset=offset, count=count)

    return render(request, 'pesagem/eventos_acesso.html', {
        'messages': messages_list,
        'eventos': eventos,  # Envia eventos diretamente do banco de dados
    })

def obter_evento_mais_recente():
    """
    Função para buscar o evento mais recente do servidor Bottle.
    """
url = "http://192.168.100.39:3000/evento_mais_recente"
try:
    response = requests.get(url, timeout=5)  # Adicione timeout para evitar longas esperas
    response.raise_for_status()  # Levanta erro para códigos 4xx/5xx
    evento_mais_recente = response.json()
except requests.exceptions.RequestException as e:
    print(f"Erro na requisição: {e}")
    evento_mais_recente = None
    

def obter_peso_final(request):
    if request.method == 'GET':
        messages_list = []
        peso_final = pesar_veiculo(messages_list, use_api=True)
        if peso_final is not None:
            return JsonResponse({'status': 'success', 'peso_final': peso_final})
        else:
            return JsonResponse({'status': 'error', 'message': 'Erro ao obter o peso final.'})
    return JsonResponse({'status': 'error', 'message': 'Método não permitido.'})

from django.core.mail import send_mail
from django.conf import settings

def sistema_pesagem(request):
    messages_list = []

    if request.method == 'GET' and 'user_id' in request.GET:
        user_id = request.GET.get('user_id')
        try:
            cliente = Cliente.objects.get(user_id=user_id)
            cliente_data = {
                'nome': cliente.nome,
                'cnpj': cliente.cnpj,
                'telefone': cliente.telefone,
                'email': cliente.email,
                'placa': cliente.placa,
                'modelo': cliente.modelo,
                'peso_maximo': cliente.peso_maximo,
                'ano_fabricacao': cliente.ano_fabricacao,
                'tipo_carga': cliente.tipo_carga,
                'descricao_carga': cliente.descricao_carga,
            }
            
            return JsonResponse({'status': 'success', 'cliente': cliente_data})
        except Cliente.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Cliente não encontrado.'})
        

    if request.method == 'POST':
        peso_final = request.POST.get('peso_final')
        user_id = request.POST.get('user_id')
        cliente = get_object_or_404(Cliente, user_id=user_id)

        try:
            peso_final = float(peso_final)
        except ValueError:
            messages_list.append("Peso final inválido.")
            return render(request, 'pesagem/ticket_pesagem.html', {'messages': messages_list})
        
        
        # Calcula o peso líquido
        peso_liquido = peso_final - cliente.peso_maximo

        # Obtém a data e hora atual
        data_hora_atual = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        # Criando uma instância de Veiculo_pesagem
        pesagem = Pesagem.objects.create(
            placa=cliente.placa,
            tag_rfid="TAG_NAO_DISPONIVEL",  # Ajustar para obter o valor correto caso necessário
            modelo=cliente.modelo,
            cor="COR_NAO_DISPONIVEL",  # Ajustar para obter o valor correto caso necessário
            user_name=cliente.nome,
            user_email=cliente.email,
            peso_final=peso_final,
            peso_liquido=peso_liquido,
            peso_maximo=cliente.peso_maximo
        )

        # Envio do e-mail com os dados de pesagem
        if cliente.email:
            subject = f"Relatório de Pesagem - {cliente.nome}"
            email_body = (
            f"Olá {cliente.nome},\n\n"
            f"Segue o relatório da sua pesagem realizada:\n\n"
            f"Data e Hora do Envio: {data_hora_atual}\n"
            f"Placa do Veículo: {cliente.placa}\n"
            f"Modelo: {cliente.modelo}\n"
            f"Peso Tara: {cliente.peso_maximo} kg\n"
            f"Peso Final Registrado: {peso_final} kg\n"
            f"Peso Líquido: {peso_liquido} kg\n\n"
            f"Obrigado por utilizar nossos serviços.\n\n"
            f"Atenciosamente,\n"
            f"Sistema de Pesagem Balança Transtino"
        )
            try:
                send_mail(
                    subject,
                    email_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [cliente.email],
                    fail_silently=False,
                )
            except Exception as e:
                messages_list.append(f"Erro ao enviar e-mail: {str(e)}")
        else:
            messages_list.append("Cliente não possui e-mail cadastrado.")

        # Mensagem de confirmação
        context = {
            'cliente': cliente,
            'peso_final': peso_final,
            'peso_liquido': peso_liquido,
            'data_hora': data_hora_atual,
            'messages': messages_list,
        }
        return render(request, 'pesagem/ticket_pesagem.html', context)
# abrir cancela para saida do caminhao 
    return render(request, 'pesagem/ticket_pesagem.html', {'messages': messages_list})

from django.db.models import Q
from xhtml2pdf import pisa

def relatorios(request, pesagem_id=None):
    # Obtem todas as pesagens
    todas_pesagens = Pesagem.objects.all().order_by('-data_pesagem')

    # Detalhes de uma pesagem específica
    detalhe_pesagem = None
    if pesagem_id:
        detalhe_pesagem = get_object_or_404(Pesagem, id=pesagem_id)

    # Verifica se há pesagens no contexto
    if not todas_pesagens.exists():
        print("Nenhuma pesagem encontrada no banco de dados.")

       # Obtém o valor da pesquisa do formulário
    search_query = request.GET.get('search', '')

    # Filtra as pesagens com base na pesquisa (placa, nome ou data) ou obtém todas se não houver pesquisa
    todas_pesagens = Pesagem.objects.all().order_by('-data_pesagem')
    if search_query:
        todas_pesagens = todas_pesagens.filter(
            Q(user_name__icontains=search_query) |
            Q(placa__icontains=search_query) |
            Q(data_pesagem__icontains=search_query)
        )

    # Detalhes de uma pesagem específica
    detalhe_pesagem = None
    if pesagem_id:
        detalhe_pesagem = get_object_or_404(Pesagem, id=pesagem_id)

    # Passa os dados para o template
    context = {
        'todas_pesagens': todas_pesagens,
        'detalhe_pesagem': detalhe_pesagem,
        'search_query': search_query,  # Opcional, caso queira preencher o campo de busca no template
    }

    # Verificando se algum detalhe foi solicitado
    detalhe_pesagem = None
    if 'detalhe_id' in request.GET:
        detalhe_id = request.GET['detalhe_id']
        detalhe_pesagem = Pesagem.objects.filter(id=detalhe_id).first()

        return render(request, 'relatorios_pesagens.html', {
        'todas_pesagens': todas_pesagens,
        'detalhe_pesagem': detalhe_pesagem
    })

    return render(request, 'pesagem/relatorios.html', context)

def relatorio_pdf_multiplo(request):
    if request.method == 'POST':
        # Obtém os IDs selecionados do formulário
        pesagem_ids = request.POST.getlist('pesagem_ids')

        if not pesagem_ids:
            return HttpResponse('Nenhuma pesagem selecionada.', status=400)

        # Busca as pesagens correspondentes
        pesagens = Pesagem.objects.filter(id__in=pesagem_ids)

        if not pesagens.exists():
            return HttpResponse('Nenhuma pesagem encontrada.', status=404)

        # Renderiza o HTML para o PDF
        html_content = render_to_string('pesagem/pdf_template.html', {'pesagens': pesagens})

        # Cria o arquivo PDF
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="relatorio_pesagens.pdf"'

        # Converte o HTML para PDF
        pisa_status = pisa.CreatePDF(html_content, dest=response)

        if pisa_status.err:
            return HttpResponse('Erro ao gerar o PDF', status=400)

        return response
    

def relatorio_pdf(request, pesagem_id):
    # Obtém os detalhes da pesagem específica
    detalhe_pesagem = get_object_or_404(Pesagem, id=pesagem_id)

    # Gera o HTML renderizado com o contexto
    html_content = render_to_string('pesagem/relatorio_pesagem_pdf.html', {'detalhe_pesagem': detalhe_pesagem})

    # Cria o arquivo PDF a partir do HTML
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="relatorio_pesagem_{pesagem_id}.pdf"'

    # Converte o HTML para PDF
    pisa_status = pisa.CreatePDF(html_content, dest=response)

    if pisa_status.err:
        return HttpResponse('Erro ao gerar o PDF', status=400)

    return response

def sistema(request):
    messages_list = []
    data_atual = now()
    context = {
        'data': data_atual.strftime('%d/%m/%Y'),
        'hora': data_atual.strftime('%H:%M:%S'),
    }

        
        # Adicione isso ao início do método sistema, antes de montar o contexto
    evento_mais_recente = obter_evento_mais_recente()
    if evento_mais_recente:
        messages_list.append("Evento mais recente carregado com sucesso.")
    else:
        messages_list.append("Não foi possível carregar o evento mais recente.")

    # Obter eventos completos do servidor Flask
    try:
        eventos_completos_response = listar_eventos_completos(request)
        eventos_completos = eventos_completos_response.content.decode('utf-8')
        eventos_completos = json.loads(eventos_completos).get("dados_completos", [])
    except Exception as e:
        eventos_completos = []
        messages_list.append(f"Erro ao obter eventos completos: {str(e)}")

        response = listar_eventos_completos(request)  # Chama a função diretamente
        if response.status_code == 200: # Verifique o status code da resposta
            eventos_completos = response.json().get("dados", []) # Assumindo que 'dados' agora é a chave para a lista
        else:
            eventos_completos = []
            messages_list.append(f"Erro ao obter eventos completos: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        eventos_completos = []
        messages_list.append(f"Erro de rede ao obter eventos completos: {str(e)}")
    except json.JSONDecodeError as e:
        eventos_completos = []
        messages_list.append(f"Erro ao decodificar JSON dos eventos completos: {str(e)}")
    except Exception as e:
        eventos_completos = []
        messages_list.append(f"Erro inesperado ao obter eventos completos: {str(e)}")




    # Verificar conexão com a balança
    balanca_conectada = verificar_conexao_balanca()
    if not balanca_conectada:
        messages_list.append("Balança não conectada. Usando API para registro de peso.")
        
    # Obter o último acesso
    ultimo_acesso = ler_tag_rfid(messages_list)

    if request.method == 'POST':
        # 1. Identificar veículo via RFID
        rfid_data = ler_tag_rfid(messages_list)
        if not rfid_data or 'cartao' not in rfid_data:
            messages_list.append("Veículo não identificado. Por favor, tente novamente.")
            fechar_cancela(messages_list)
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})

        veiculo = Veiculo_pesagem.objects.filter(tag_rfid=rfid_data['cartao']).first()
        if not veiculo:
            messages_list.append("Veículo não cadastrado. Cadastro necessário.")
            fechar_cancela(messages_list)
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})

        # 2. Registrar peso inicial
        peso_inicial = pesar_veiculo(messages_list, use_api=True)
        if peso_inicial is None:
            messages_list.append("Falha ao registrar o peso inicial. Processo interrompido.")
            fechar_cancela(messages_list)
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})
        else:
            print(f"DEBUG: Peso inicial obtido: {peso_inicial} Kg")
        
        # 3. Abrir cancela para entrada
        abrir_cancela(messages_list, canal=2)
        # 4. Registrar peso final
        peso_final = pesar_veiculo(messages_list, use_api=True)
        if peso_final is None:
            messages_list.append("Falha ao registrar o peso final. Processo interrompido.")
            fechar_cancela(messages_list)
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})
        else:
            print(f"DEBUG: Peso final obtido: {peso_final} Kg")
        
        # 5. Abrir cancela para saída
        abrir_cancela(messages_list, canal=2)

        # 6. Criar ticket de pesagem
        ticket = Ticket_pesagem.objects.create(
            veiculo=veiculo,
            peso_inicial=peso_inicial,
            peso_final=peso_final,
            registrado_em=timezone.now()
        )
        messages_list.append(f"Ticket gerado com sucesso! ID do Ticket: {ticket.id}")

        # 7. Enviar e-mail de confirmação, se aplicável
        if veiculo.email:
            subject = f"Pesagem Concluída para o veículo {veiculo.placa}"
            email_content = render_to_string('pesagem/sistema.html', {
                'veiculo': veiculo,
                'peso_inicial': peso_inicial,
                'peso_final': peso_final,
                'data': data_atual.strftime('%d/%m/%Y'),
                'hora': data_atual.strftime('%H:%M:%S'),
            })
            send_mail(
                subject,
                email_content,
                settings.DEFAULT_FROM_EMAIL,
                [veiculo.email],
                fail_silently=False,
            )

        fechar_cancela(messages_list)  # Fechar cancela após todo o processo

    # Renderizar página com informações atualizadas
    return render(request, 'pesagem/sistema.html', {
        'ultimo_acesso': ultimo_acesso,
        'evento_mais_recente': evento_mais_recente,
        'eventos_completos': eventos_completos,
        'messages': messages_list,
        'balanca_conectada': balanca_conectada,
        'data': data_atual.strftime('%d/%m/%Y'),
        'hora': data_atual.strftime('%H:%M:%S'),
    })

# Função de automação a ser chamada
def executar_automacao():
    try:
                
        # clicar no navegador do InContrl
        pyautogui.click(377,20,duration=3)

        # clicar no id da pagina de logs
        pyautogui.doubleClick(1279,192,duration=3)
        #esperar um tempo
        time.sleep(1)
        # copiar id da pagina de logs
        pyautogui.hotkey('ctrl', 'c')
        # clicar no navegador do sistema de pesagem
        pyautogui.click(158,26,duration=2)
        # clicar em user id
        pyautogui.click(547,216,duration=2)
        # colar user id
        pyautogui.hotkey('ctrl', 'v')
        # clicar em buscar
        pyautogui.click(532,262, duration=2)
        #aguardar 1 segundo
        time.sleep(1)
        #abrir funcionalidade de impressao
        pyautogui.hotkey('ctrl', 'p')
        #clicar em numero de impressoes
        pyautogui.doubleClick(1033,280, duration=1)
        #aguardar um segundo
        time.sleep(1)
        #inserir quantidade de copias
        pyautogui.typewrite('3')
        #clicar em imprimir 
        pyautogui.click(1056,700, duration=1)
        #esperar
        time.sleep(2)
        #clicar na barra de rolagem
        pyautogui.click(1431,289,duration=1)
        time.sleep(1)
        #arrastar para baixo
        pyautogui.drag(0,300,duration=1)
        # registar peso
        pyautogui.click(555,710,duration=2)


    except Exception as e:
        print(f"ërro ao executar automacao: {str(e)}")

# Função para monitorar a balança e chamar a automação
def monitorar_balanca(intervalo_segundos=2):
    """
    Função que monitora a API da balança e chama a função executar_automacao 
    quando um peso estável é detectado.
    
    :param intervalo_segundos: Tempo em segundos entre as requisições.
    """
    print("Iniciando monitoramento da balança...")
    while True:
        try:
            # Consulta a API da balança
            response = requests.get(LOCAL_API_URL, timeout=5)
            response.raise_for_status()  # Lança exceção se a resposta for erro
            data = response.json()

            # Verifica se o peso está estável
            if data.get("status") == "ok" and data.get("is_stable", False):
                peso = data.get("gross")
                if peso is not None:
                    print(f"Peso estável detectado: {peso} {data.get('unity', 'kg')}")
                    executar_automacao(peso)  # Chama a função de automação
                else:
                    print("API retornou um peso nulo ou inválido.")
            else:
                print("Peso instável ou erro na resposta da API.")

        except requests.RequestException as e:
            print(f"Erro ao acessar a API de pesagem: {str(e)}")

        # Aguarda antes da próxima verificação
        time.sleep(intervalo_segundos)
