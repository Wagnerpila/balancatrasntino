from django.shortcuts import render, redirect
from .models import Ticket, Veiculo
from django.http import JsonResponse
from django.contrib import messages
import random
import time

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
def ler_tag_rfid(messages_list):
    # Simulação da leitura da tag RFID
    veiculo = Veiculo.objects.filter(placa='BBB-1111').first()
    if veiculo:
        messages_list.append(f"Veículo identificado: {veiculo.placa}")
        return veiculo
    return None

def abrir_cancela(messages_list):
    # Simulação de abertura de cancela
    messages_list.append("Cancela de entrada aberta.")

def fechar_cancela(messages_list):
    # Simulação de fechamento de cancela
    messages_list.append("Cancela de entrada fechada.")

def pesar_veiculo(messages_list):
    # Simulação de pesagem de veículo
    import random
    peso = random.randint(10000, 30000)
    messages_list.append(f"Peso registrado: {peso} Kg")
    return peso

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
