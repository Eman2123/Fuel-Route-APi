from django.db import models


class City(models.Model):
    name = models.CharField(max_length=100)          # lowercase, normalized
    state = models.CharField(max_length=2)
    lat = models.FloatField()
    lng = models.FloatField()
    population = models.IntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["name", "state"])]


class Station(models.Model):
    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    lat = models.FloatField()
    lng = models.FloatField()
    price = models.FloatField()                      # USD per gallon

    class Meta:
        indexes = [models.Index(fields=["lat", "lng"])]