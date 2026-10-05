from datetime import date

from django.core.management.base import BaseCommand, CommandError

from Alumnos.asistencias import cerrar_dia, cerrar_dias_pendientes


class Command(BaseCommand):
    help = (
        'Cierra los días de clases: genera las faltas de quien no registró entrada. Sin opciones cierra todos los días '
        'anteriores que sigan abiertos (conviene programarlo cada noche); con --fecha, solo ese día.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--fecha', help='Día a cerrar, en formato AAAA-MM-DD.')

    def handle(self, *args, **opciones):
        if opciones['fecha']:
            try:
                fecha = date.fromisoformat(opciones['fecha'])
            except ValueError:
                raise CommandError('La fecha debe tener el formato AAAA-MM-DD.')
            faltas = cerrar_dia(fecha, automatico=True)
            if faltas is None:
                self.stdout.write(f'{fecha}: no se cierra (día sin clases, futuro o fuera de un ciclo).')
            else:
                self.stdout.write(self.style.SUCCESS(f'{fecha}: cerrado, {faltas} falta(s) generada(s).'))
            return

        cerrados = cerrar_dias_pendientes(automatico=True)
        if not cerrados:
            self.stdout.write('No había días pendientes por cerrar.')
        for fecha, faltas in cerrados:
            self.stdout.write(self.style.SUCCESS(f'{fecha}: cerrado, {faltas} falta(s) generada(s).'))
