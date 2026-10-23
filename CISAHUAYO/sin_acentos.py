"""Búsquedas que ignoran los acentos (pedido del 2026-10-23): «excursion» encuentra «excursión» en todos los buscadores.

En vez de cambiar cada filtro, el `icontains` de los campos de texto se reemplaza por uno que compara los dos lados sin
acentos: en PostgreSQL con la extensión `unaccent` (Usuarios/migrations/0020) y en SQLite (pruebas y copia local) con
una función UNACCENT registrada en cada conexión. Se instala desde UsuariosConfig.ready().
"""
import unicodedata

from django.db.backends.signals import connection_created
from django.db.models import CharField, TextField
from django.db.models.lookups import IContains


def quitar_acentos(texto):
    if texto is None:
        return None
    descompuesto = unicodedata.normalize('NFKD', str(texto))
    return ''.join(c for c in descompuesto if not unicodedata.combining(c)).lower()


class IContainsSinAcentos(IContains):
    """Igual que `icontains`, con UNACCENT() alrededor de la columna y del texto buscado."""

    def process_lhs(self, compiler, connection, lhs=None):
        sql, params = super().process_lhs(compiler, connection, lhs)
        return f'UNACCENT({sql})', params

    def process_rhs(self, qn, connection):
        sql, params = super().process_rhs(qn, connection)
        return f'UNACCENT({sql})', params


def _registrar_en_sqlite(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        connection.connection.create_function('UNACCENT', 1, quitar_acentos, deterministic=True)


def instalar():
    for campo in (CharField, TextField):
        campo.register_lookup(IContainsSinAcentos, lookup_name='icontains')
    connection_created.connect(_registrar_en_sqlite, dispatch_uid='cisahuayo.sin_acentos')
