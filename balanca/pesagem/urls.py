from django.urls import path
from . import views 


urlpatterns = [
    path("", views.sistema, name='sistema'),
   # path('pesagem_final', views.pesagem_final, name='pesagem_final'),
   # path('operacional', views.operacional, name='operacional'),
    path('relatorios/', views.relatorios, name='relatorios'),
    path('relatorios/<int:pesagem_id>/', views.relatorios, name='detalhe_pesagem'),
    path('relatorio_pdf/<int:pesagem_id>/', views.relatorio_pdf, name='relatorio_pdf'),
    path('relatorio/pdf-multiplo/', views.relatorio_pdf_multiplo, name='relatorio_pdf_multiplo'),
    path('cadastro', views.cadastro_view, name='cadastro'),
    path('abrir_cancela/', views.abrir_cancela_view, name='abrir_cancela'),
    path('fechar_cancela/', views.fechar_cancela_view, name='fechar_cancela'),
   # path('', views.vehicle_list, name='vehicle_list'),
   # path('sync/', views.sync_with_api, name='sync_with_api'),
    path('eventos-acesso/', views.listar_eventos_acesso, name='eventos_acesso'),
    path('', views.ler_tag_view, name='ultimo_acesso'),
    path('users/', views.user_search_view, name='get_all_users'),
    path('cadastro', views.cadastro_view, name='cadastro'),
    path('cadastro-sucesso', views.cadastro_sucesso, name='cadastro_sucesso'),
    path('clientes/', views.listar_clientes_view, name='listar_clientes'),
    path('clientes/editar/<int:cliente_id>/', views.editar_cliente_view, name='editar_cliente'),
    path('clientes/deletar/<int:cliente_id>/', views.deletar_cliente_view, name='deletar_cliente'),
    path('ticket_pesagem/', views.sistema_pesagem, name='ticket_pesagem'),
    path('registros/', views.registros_recentes, name='regis'),
    path('obter-peso-final/', views.obter_peso_final, name='obter_peso_final'),



]
