from django.shortcuts import render, redirect
from .models import Ticket, Veiculo
from django.http import JsonResponse
from django.contrib import messages
import serial
import requests
import random
import time


# Configurações básicas da API (alterar conforme necessário)
API_BASE_URL = "https://intelbras-caco-api-ct3000.intelbras.com.br"


def sistema(request):
    messages_list = []  # Lista para exibir mensagens no frontend
    peso_inicial = None
    peso_final = None

    if request.method == 'POST':
        # 1. Identificação via Tag RFID
        veiculo = ler_tag_rfid(messages_list)
        if veiculo is None:
            messages_list.append("Veículo não identificado. Por favor, tente novamente.")
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})

        # 2. Verificar se o veículo está cadastrado
        if not veiculo.cadastrado:
            messages_list.append(f"Veículo {veiculo.placa} não cadastrado. Cadastro necessário.")
            fechar_cancela(messages_list)  # Fechar cancela se não for cliente cadastrado
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})

        # 3. Abrir cancela de entrada
        abrir_cancela(messages_list)

        # 4. Registrar pesagem inicial
        peso_inicial = pesar_veiculo(messages_list)
        if not peso_inicial:
            messages_list.append("Falha ao registrar o peso inicial.")
            fechar_cancela(messages_list)  # Fechar cancela em caso de falha na pesagem
            return render(request, 'pesagem/sistema.html', {'messages': messages_list})

        # 5. Criar ticket de pesagem
        ticket = Ticket.objects.create(
            veiculo=veiculo,
            peso_inicial=peso_inicial
        )
        messages_list.append(f"Ticket gerado com sucesso! ID do Ticket: {ticket.id}")

        # 6. Fechar cancela de entrada
        fechar_cancela(messages_list)

        # Simulação de pesagem final para outro momento
        if request.POST.get('finalizar'):
            abrir_cancela(messages_list)  # Abrir cancela para saída

            # 7. Registrar pesagem final
            peso_final = pesar_veiculo(messages_list)
            if peso_final:
                ticket.peso_final = peso_final
                ticket.save()
                messages_list.append(f"Pesagem final registrada. Peso final: {peso_final} Kg")

            # 8. Fechar cancela de saída
            fechar_cancela(messages_list)

    # Renderizar o template com as mensagens e as informações do peso
    return render(request, 'pesagem/sistema.html', {
        'messages': messages_list,
        'peso_inicial': peso_inicial,
        'peso_final': peso_final
    })

# Funções auxiliares para lidar com RFID, cancela, e pesagem
# Função para ler a tag RFID
def ler_tag_rfid(messages_list):
    try:
        # Chamada para o endpoint que lê o RFID
        response = requests.get(f"{API_BASE_URL}/rfid/read")
        response.raise_for_status()  # Verifica erros na requisição
        
        data = response.json()
        placa = data.get('placa')  # Assume que a resposta da API contém um campo 'placa'

        # Busca o veículo no banco de dados
        veiculo = Veiculo.objects.filter(placa=placa).first()
        if veiculo:
            messages_list.append(f"Veículo identificado: {veiculo.placa}")
            return veiculo
        else:
            messages_list.append("Veículo não encontrado no cadastro.")
            return None

    except requests.RequestException as e:
        messages_list.append(f"Erro na leitura do RFID: {str(e)}")
        return None

# Função para abrir a cancela
def abrir_cancela(messages_list):
    try:
        # Chamada para o endpoint que abre a cancela
        response = requests.post(f"{API_BASE_URL}/gate/open")
        response.raise_for_status()  # Verifica erros na requisição
        messages_list.append("Cancela de entrada aberta.")
    except requests.RequestException as e:
        messages_list.append(f"Erro ao abrir a cancela: {str(e)}")

# Função para fechar a cancela
def fechar_cancela(messages_list):
    try:
        # Chamada para o endpoint que fecha a cancela
        response = requests.post(f"{API_BASE_URL}/gate/close")
        response.raise_for_status()  # Verifica erros na requisição
        messages_list.append("Cancela de entrada fechada.")
    except requests.RequestException as e:
        messages_list.append(f"Erro ao fechar a cancela: {str(e)}")

def pesar_veiculo(messages_list):
    try:
        # Configurar a comunicação serial com a porta COM1
        with serial.Serial('COM1', baudrate=9600, timeout=1) as ser:
            ser.flush()  # Limpar o buffer de entrada
            # Ler dados da balança
            if ser.in_waiting > 0:
                peso = ser.readline().decode('utf-8').strip()
                peso = int(peso)  # Converter para inteiro, se o peso estiver em formato numérico

                messages_list.append(f"Peso registrado: {peso} Kg")
                return peso
            else:
                messages_list.append("Falha ao ler o peso da balança.")
                return None
    except (serial.SerialException, ValueError) as e:
        messages_list.append(f"Erro na leitura da balança: {str(e)}")
        return None

# View para realizar a pesagem final e liberar o veículo
def pesagem_final(request):
    messages = []
    peso_final = None
    peso_liquido = None

    if request.method == 'POST':
        ticket_id = request.POST.get('ticket_id')
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            messages.append("Ticket não encontrado")
            return render(request, 'pesagem/sistema2.html', {'messages': messages})

        # 1. Abrir cancela para pesagem final
        abrir_cancela(messages)

        # 2. Registrar o peso final
        peso_final = pesar_veiculo(messages)
        ticket.peso_final = peso_final
        ticket.save()

        # 3. Calcular o peso líquido
        peso_liquido = peso_final - ticket.peso_inicial
        messages.append(f"Peso líquido calculado: {peso_liquido:.2f} kg")

        # 4. Fechar cancela de saída
        fechar_cancela(messages)

    return render(request, 'pesagem/sistema2.html', {
        'messages': messages,
        'peso_final': peso_final,
        'peso_liquido': peso_liquido
    })

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
