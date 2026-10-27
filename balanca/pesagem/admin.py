from django.contrib import admin
from .models import Veiculo_pesagem, Ticket_pesagem, Cliente, Pesagem

@admin.register(Veiculo_pesagem)
class VeiculoAdmin(admin.ModelAdmin):
    list_display = ('placa', 'tag_rfid', 'modelo', 'cor', 'cadastrado_em')
    search_fields = ('placa', 'tag_rfid')

@admin.register(Ticket_pesagem)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('veiculo', 'peso_inicial', 'peso_final', 'criado_em', 'finalizado_em')
    search_fields = ('veiculo__placa', 'veiculo__tag_rfid')


admin.site.register(Cliente)


admin.site.register(Pesagem)