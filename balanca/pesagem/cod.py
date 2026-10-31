from django.shortcuts import render, redirect
from .models import Ticket, Veiculo, Ticket_pesagem, Veiculo_pesagem
from django.http import JsonResponse
import json
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.timezone import now
from .services import fetch_intelbras_data
from django.utils import timezone
import serial
import time
from django.http import JsonResponse
from datetime import datetime
from django.conf import settings
import serial.tools.list_ports
import requests

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
LOCAL_API_URL = "http://127.0.0.1:8090/peso/?fmt=1"  # o sistema novo lê a COM3 e serve o peso (antes: Gateway Virtual na porta 80)

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

from .models import Veiculo_pesagem

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

        
def get_cancela_status(request):
# Obtem o status das cancelas para os canais 1 e 2
    statuses = {}
    for channel in [1, 2]:
        url = f"http://{device_ip}/cgi-bin/accessControl.cgi?action=getDoorStatus&channel={channel}"
        try:
            response = requests.get(url, auth=digest_auth, timeout=20, verify=False)
            response.raise_for_status()
            statuses[f"canal_{channel}"] = response.text.strip()  # Adiciona o status da resposta
        except requests.RequestException as e:
            statuses[f"canal_{channel}"] = f"Erro: {str(e)}"
    
    return JsonResponse(statuses)



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
                messages_list.append("Peso instável ou erro na resposta da API.")
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

def vehicle_list(request):
    # Sincronizar veículos com a API
    fetch_intelbras_data()  # Certifique-se de que esta função retorna ou atualiza os veículos

    vehicles = Veiculo_pesagem.objects.all()
    return render(request, 'pesagem/sistema.html', {'vehicles': vehicles})

def sync_with_api(request):
    data = fetch_intelbras_data('192.168.100.80', 'admin', 'intelbras')
    if data:
            for line in data.splitlines():
                # Pule linhas vazias
                if not line.strip():
                    continue

                # Divida os dados da linha
                fields = line.split(',')

                # Valide o número de campos antes de processar
                if len(fields) < 4:
                    print(f"Skipped line due to insufficient fields: {line}")
                    continue

                # Atualize ou crie o veículo no banco de dados
                Veiculo_pesagem.objects.update_or_create(
                    tag_id=fields[0].strip(),  # Ajuste conforme o formato real dos dados
                    defaults={
                        'license_plate': fields[1].strip(),
                        'vehicle_type': fields[2].strip(),
                        'user_name': fields[3].strip(),
                    }
                )
    return vehicle_list(request)


from django.shortcuts import render

def ticket_pesagem_view(request, ticket_id):
    try:
        ticket = Ticket_pesagem.objects.get(id=ticket_id)
        context = {
            'ticket': ticket,
            'data': ticket.criado_em.strftime('%d/%m/%Y'),
            'hora': ticket.criado_em.strftime('%H:%M:%S'),
            'peso_inicial': ticket.peso_inicial,
            'peso_final': ticket.peso_final or "-",
            'peso_liquido': ticket.peso_liquido() or "-",
            'veiculo': ticket.veiculo,
            'placa': ticket.veiculo.placa,
            'usuario': request.user.username,  # Assumindo que o usuário está logado
        }
        return render(request, 'pesagem/ticket.html', context)
    except Ticket_pesagem.DoesNotExist:
        return render(request, 'pesagem/error.html', {'message': 'Ticket não encontrado.'})



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






# Outras views para o sistema
def operacional(request):
    return render(request, 'pesagem/operacional.html')

def relatorios(request):
    return render(request, 'pesagem/relatorios.html')

def ticket_pesagem(request):
    tickets = Ticket.objects.all()
    return render(request, 'pesagem/tickets.html', {'tickets': tickets})

def cadastro(request):
    return render(request, 'pesagem/cadastro.html')

def pesagem_final(request):
    return render(request, 'pesagem/sistema2.html')

def sistema(request):
    messages_list = []
    
    data_atual = now()
    context = {
        'data': data_atual.strftime('%d/%m/%Y'),
        'hora': data_atual.strftime('%H:%M:%S'),
    }

    # Sincronizar veículos automaticamente
    fetch_intelbras_data('192.168.100.80', 'admin', 'intelbras')

    vehicles = Veiculo_pesagem.objects.all()

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
        'vehicles': vehicles,
        'ultimo_acesso': ultimo_acesso,
        'messages': messages_list,
        'balanca_conectada': balanca_conectada,
        'data': data_atual.strftime('%d/%m/%Y'),
        'hora': data_atual.strftime('%H:%M:%S'),
    })



def obter_eventos_acesso(messages_list, offset=0, count=10):
    """
    Função para obter eventos de acesso usando a API Intelbras.
    """
    try:
        # URL para buscar os eventos de acesso
        url = f"http://{device_ip}/cgi-bin/recordFinder.cgi?action=find&name=AccessControlCardRec&offset={offset}&count={count}"
        
        # Requisição para a API
        response = requests.get(url, auth=digest_auth, timeout=20, verify=False)
        response.raise_for_status()  # Gera exceção se o status não for 2xx

        # Parse dos dados recebidos (assumindo que sejam texto estruturado ou JSON)
        eventos = response.text.strip()  # Ou `response.json()` se o retorno for JSON
        
        messages_list.append("Eventos de acesso obtidos com sucesso.")
        return eventos  # Retornar os dados brutos para processamento adicional
    except requests.RequestException as e:
        messages_list.append(f"Erro ao obter eventos de acesso: {str(e)}")
        return None

def eventos_acesso_view(request):
    messages_list = []
    
    # Obter os eventos de acesso
    eventos = obter_eventos_acesso(messages_list)
    
    # Processar os eventos: divida os dados em listas, se necessário
    eventos_processados = []
    if eventos:
        for linha in eventos.splitlines():  # Assume que cada evento está em uma linha
            eventos_processados.append(linha.split(','))  # Divide por vírgula
    
    return render(request, 'pesagem/eventos_acesso.html', {
        'messages': messages_list,
        'eventos': eventos_processados,  # Envie os eventos processados
    })


def handle_event(request):
    if request.method == "POST":
        try:
            # Processar o corpo da requisição multipart-mixed
            boundary = b"--myboundary"
            raw_data = request.body
            parts = raw_data.split(boundary)
            
            for part in parts:
                if b"Content-Type" in part:
                    lines = part.split(b"\r\n")
                    content_type = lines[0].split(b": ")[1].strip()

                    if content_type == b"text/plain":
                        # Processar o JSON do evento
                        json_data = b"\r\n".join(lines[3:-1]).decode('utf-8')
                        event_data = json.loads(json_data)
                        print("Evento recebido:", event_data)
                    elif content_type == b"image/jpeg":
                        # Salvar imagem recebida
                        with open(f"event_image_{time.time()}.jpg", "wb") as img_file:
                            img_file.write(b"\r\n".join(lines[3:-3]))
        except Exception as e:
            print("Erro ao processar o evento:", e)
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

        return JsonResponse({"status": "success"}, status=200)

    return JsonResponse({"status": "invalid_method"}, status=405)


def format_access_records(device_ip, username, password, offset=0, count=10):
    url = f"http://{device_ip}/cgi-bin/recordFinder.cgi?action=find&name=AccessControlCardRec&offset={offset}&count={count}"
    digest_auth = requests.auth.HTTPDigestAuth(username, password)

    try:
        # Realiza a requisição à API
        response = requests.get(url, auth=digest_auth, timeout=20, verify=False)

        if response.status_code == 200:
            raw_data = response.text
            records = {}
            
            # Processa os dados de resposta
            for line in raw_data.splitlines():
                if line.startswith("found"):
                    records["found"] = int(line.split("=")[1])
                elif line.startswith("records"):
                    key, value = line.split("=")
                    record_index, field_name = key.replace("records[", "").replace("]", "").split(".")
                    if record_index not in records:
                        records[record_index] = {}
                    records[record_index][field_name] = value

            formatted_records = []
            
            # Formata e imprime os registros
            for idx, record in records.items():
                if isinstance(record, dict):
                    timestamp = int(record.get("CreateTime", 0))
                    if timestamp != 0:
                        formatted_record = {
                            "timestamp": datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S'),
                            "user": record.get("CardName", "Desconhecido"),
                            "access_point": f"CT 3000-{record.get('Door', 'Desconhecido')}",
                            "detail": "Acesso liberado" if record.get("Status") == "1" else "Acesso negado",
                            "direction": "Entrada" if record.get("Type") == "Entry" else "Saída",
                            "event_type": "Acesso Liberado" if record.get("Status") == "1" else "Acesso Negado",
                        }
                        
                        # Imprime os dados no terminal
                        print(f"Timestamp: {formatted_record['timestamp']}")
                        print(f"Usuário: {formatted_record['user']}")
                        print(f"Ponto de Acesso: {formatted_record['access_point']}")
                        print(f"Detalhe: {formatted_record['detail']}")
                        print(f"Sentido: {formatted_record['direction']}")
                        print(f"Tipo de Evento: {formatted_record['event_type']}")
                        print("-" * 40)  # Linha separadora para clareza
                        
                        formatted_records.append(formatted_record)

            # Ordena os registros, mais recente primeiro
            formatted_records.sort(key=lambda x: datetime.strptime(x['timestamp'], '%d/%m/%Y %H:%M:%S'), reverse=True)
            return formatted_records

        else:
            raise Exception(f"Erro na API: {response.status_code} - {response.reason}")

    except requests.RequestException as e:
        raise Exception(f"Erro na requisição: {e}")

# Função para obter e imprimir registros
def get_formatted_access_records(request):
    device_ip = '192.168.100.80'  # IP do dispositivo
    username = 'admin'  # Usuário do dispositivo
    try:  # senha fica em balanca/segredos.py (fora do Git)
        from balanca.segredos import DEVICE_PASSWORD as password
    except ImportError:
        password = ''
    offset = int(request.GET.get('offset', 0))
    count = int(request.GET.get('count', 10))

    try:
        # Chama a função para obter os registros e imprimi-los no terminal
        records = format_access_records(device_ip, username, password, offset, count)
        return JsonResponse(records, safe=False)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

