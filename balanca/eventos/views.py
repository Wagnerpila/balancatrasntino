from rest_framework.decorators import api_view
from rest_framework.response import Response
import json
import ast

@api_view(['POST'])
def notification(request):
    if request.method == 'POST':
        res = request.body  # Obter o corpo da requisição
        data_list = res.split(b"--myboundary\r\n")  # Dividir o conteúdo por "boundary"

        # Processar os dados recebidos
        text_data = None
        for a_info in data_list:
            if b"Content-Type" in a_info:
                lines = a_info.split(b"\r\n")
                a_type = lines[0].split(b": ")[1]
                if a_type == b"image/jpeg":
                    image_data = b"\r\n".join(lines[3:-3])  # Dados de imagem (não usado aqui)
                else:
                    text_data = b"\r\n".join(lines[3:-1])  # Dados de texto

            if text_data is None:
                return Response({"message": "Nenhum dado de texto encontrado", "code": "400", "auth": False}, status=400)


        # Converter os dados de texto para dicionário
        evento_str = text_data.decode("utf-8")
        evento_dict = ast.literal_eval(evento_str.replace("--myboundary--", " "))
        
        # Processar o evento
        event_code = evento_dict.get("Events")[0].get('Code')
        print(f"Evento recebido: {event_code}")

        if event_code == "AccessControl":
            # Extração dos dados
            event_data = evento_dict.get("Events")[0].get('Data')
            user_id = event_data.get('UserID')
            card_no = event_data.get('CardNo')

            # Regras personalizadas
            if user_id == 6:
                return Response({"message": "Pagamento não realizado!", "code": "200", "auth": False})
            elif card_no in ["EC56D271", "09201802"]:
                return Response({"message": "Bem vindo!", "code": "200", "auth": True})

        elif event_code == "DoorStatus":
            door_status = evento_dict.get("Events")[0].get('Data').get('Status')
            print(f"Status da Porta: {door_status}")

        elif event_code == "BreakIn":
            door_name = evento_dict.get("Events")[0].get('Data').get('Name')
            print(f"Arrombament detectado na porta: {door_name}")

        return Response({"message": "", "code": "200", "auth": False})

@api_view(['GET'])
def keepalive(request):
    return Response("OK")
