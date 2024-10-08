from django.urls import path
from . import views 


urlpatterns = [
    path("", views.sistema, name='sistema'),
    path('pesagem_final', views.pesagem_final, name='pesagem_final'),
    path('operacional', views.operacional, name='operacional'),
    path('relatorios' , views.relatorios, name='relatorios'),
    path('ticket_pesagem', views.ticket_pesagem, name='ticket_pesagem'),
    path('cadastro', views.cadastro, name='cadastro')
]
