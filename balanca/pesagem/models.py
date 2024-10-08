from django.db import models

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
