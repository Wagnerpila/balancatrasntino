from django.db import models
from django.utils.timezone import now


class Veiculo(models.Model):
    placa = models.CharField(max_length=10)
    cadastrado = models.BooleanField(default=False)

    def __str__(self):
        return self.placa

class Ticket(models.Model):
    veiculo = models.ForeignKey(Veiculo, on_delete=models.CASCADE)
    peso_inicial = models.IntegerField()
    peso_final = models.IntegerField(null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket {self.id} - {self.veiculo.placa}"
    

class Veiculo_pesagem(models.Model):
    placa = models.CharField(max_length=10, unique=True, verbose_name="Placa do Veículo")
    tag_rfid = models.CharField(max_length=50, unique=True, verbose_name="Tag RFID")
    modelo = models.CharField(max_length=50, verbose_name="Modelo do Veículo", null=True, blank=True)
    cor = models.CharField(max_length=20, verbose_name="Cor do Veículo", null=True, blank=True)
    cadastrado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")
    user_name = models.CharField(max_length=100, default="Desconhecido")
    user_email = models.CharField(max_length=100, default="Desconhecido")


    def __str__(self):
        return f"{self.placa} - {self.modelo}"

class Ticket_pesagem(models.Model):
    veiculo = models.ForeignKey(Veiculo_pesagem, on_delete=models.CASCADE, related_name="tickets")
    peso_inicial = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Peso Inicial (kg)")
    peso_final = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Peso Final (kg)", null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data e Hora de Entrada")
    finalizado_em = models.DateTimeField(null=True, blank=True, verbose_name="Data e Hora de Saída")
    ponto_controle = models.CharField(max_length=50, default="Ponto de Controle")
    operacao = models.CharField(max_length=50, default="Operação de Pesagem")
    tag_rfid = models.CharField(max_length=50, unique=True, verbose_name="Tag RFID", default="Desconhecido")


    def peso_liquido(self):
        if self.peso_final:
            return self.peso_final - self.peso_inicial
        return None
    
class AccessEvent(models.Model):
    card_no = models.CharField(max_length=50, null=True, blank=True)
    card_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="Nome do Usuário")
    create_time = models.DateTimeField(verbose_name="Data e Hora do Acesso")
    door = models.IntegerField(verbose_name="Porta", null=True, blank=True)
    status = models.IntegerField(verbose_name="Status do Acesso", null=True, blank=True)
    access_type = models.CharField(max_length=20, verbose_name="Tipo de Acesso (Entrada/Saída)", null=True, blank=True)
    user_id = models.CharField(max_length=50, verbose_name="ID do Usuário", null=True, blank=True)

    def __str__(self):
        return f"{self.card_no} - {self.create_time.strftime('%d/%m/%Y %H:%M:%S')}"

class EventoAcesso(models.Model):
    rec_no = models.IntegerField(unique=True)  # Identificador único do evento
    data_hora = models.DateTimeField()         # Data e hora do evento
    tipo = models.CharField(max_length=50)     # Tipo de evento (ex.: acesso)
    cartao = models.CharField(max_length=50)   # Número do cartão
    usuario = models.CharField(max_length=100) # Nome do usuário (se disponível)
    criado_em = models.DateTimeField(default=now)

    def __str__(self):
        return f"Evento {self.rec_no} - {self.data_hora}"
    

class AccessEvents(models.Model):
    attendance_state = models.IntegerField()
    card_name = models.CharField(max_length=100, blank=True, null=True)
    card_no = models.CharField(max_length=100, blank=True, null=True)
    card_type = models.IntegerField()
    create_time = models.DateTimeField()
    door = models.IntegerField()
    error_code = models.IntegerField()
    mask = models.IntegerField()
    method = models.IntegerField()
    notes = models.TextField(blank=True, null=True)
    password = models.CharField(max_length=100, blank=True, null=True)
    reader_id = models.IntegerField()
    rec_no = models.IntegerField(unique=True)
    remaining_times = models.IntegerField()
    reserved_int = models.IntegerField()
    reserved_string = models.CharField(max_length=100, blank=True, null=True)
    room_number = models.CharField(max_length=100, blank=True, null=True)
    status = models.IntegerField()
    event_type = models.CharField(max_length=50)  # Entry/Exit
    url = models.URLField(blank=True, null=True)
    user_id = models.CharField(max_length=100, blank=True, null=True)
    user_type = models.IntegerField()

    def __str__(self):
        return f"Access Event {self.rec_no} - {self.event_type} at Door {self.door}"    
    
class AlarmEvent(models.Model):
    dev_addrs = models.IntegerField()
    event_code = models.CharField(max_length=100)
    index_num = models.IntegerField()
    rec_no = models.IntegerField(unique=True)
    time = models.DateTimeField()
    user_id = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"Event {self.rec_no} - {self.event_code} at {self.time}"


from django.db import models

class Cliente(models.Model):
    # Dados do cliente
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18)
    telefone = models.CharField(max_length=15)
    email = models.EmailField()

    # Dados do caminhão
    placa = models.CharField(max_length=8)
    modelo = models.CharField(max_length=255)
    peso_maximo = models.FloatField()
    ano_fabricacao = models.IntegerField()

    # Dados da carga
    tipo_carga = models.CharField(max_length=50)
    peso_carga = models.FloatField()
    descricao_carga = models.TextField()

    # Dados do Card (relacionado à funcionalidade de filtro)
    card_no = models.CharField(max_length=50, blank=True, null=True)
    user_id = models.CharField(max_length=255, blank=True, null=True)
    card_type = models.IntegerField(blank=True, null=True)
    card_name = models.CharField(max_length=255, blank=True, null=True)
    card_status = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.nome} - {self.placa}"


class Pesagem(models.Model):
    id = models.AutoField(primary_key=True)
    placa = models.CharField(max_length=10, verbose_name="Placa do Veículo")
    tag_rfid = models.CharField(max_length=50, verbose_name="Tag RFID")
    modelo = models.CharField(max_length=50, verbose_name="Modelo do Veículo", null=True, blank=True)
    cor = models.CharField(max_length=20, verbose_name="Cor do Veículo", null=True, blank=True)
    cadastrado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")
    user_name = models.CharField(max_length=100, default="Desconhecido")
    user_email = models.CharField(max_length=100, default="Desconhecido")
    peso_final = models.FloatField(null=True)
    peso_maximo = models.FloatField(null=True)
    peso_liquido = models.FloatField(null=True)
    data_pesagem = models.DateTimeField(auto_now_add=True, null=True , verbose_name="data e hora da pesagem!")

    def __str__(self):
        return f"{self.user_name} - {self.data_pesagem} - {self.placa}"