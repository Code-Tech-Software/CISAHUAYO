"""Ajustes › Conducta: los catálogos de cada nivel educativo (categorías, motivos, medidas disciplinarias y motivos de
suspensión) y el aviso de reincidencia.

Cada catálogo pide sus propios permisos (Conducta.*_<modelo>). Lo que ya se usó en el historial no se elimina: se
desactiva (deja de ofrecerse para registros nuevos, pero los registros que lo usan lo siguen mostrando). Eliminar solo
se permite a lo que nunca se usó.
"""
from dataclasses import dataclass

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from CISAHUAYO.permisos import requiere_alguno, requiere_permisos

from . import reglas
from .forms import CategoriaForm, MedidaForm, MotivoForm, MotivoSuspensionForm, ReglaReincidenciaForm
from .models import NIVELES, CategoriaConducta, MedidaDisciplinaria, MotivoConducta, MotivoSuspension, ReglaReincidencia
from .permisos import CONFIGURACION

NIVEL_INICIAL = 'PRIMARIA'


@dataclass(frozen=True)
class Catalogo:
    clave: str            # en la dirección y en ?seccion=
    nombre: str           # el de la ruta: conducta:<nombre>_crear…
    modelo: type
    form: type
    permiso: str          # codename del modelo
    singular: str
    plural: str
    nueva: str            # «Nueva categoría»
    articulo: str         # «la» / «el»
    uso: str              # el related_name que cuenta su uso en el historial

    def ver(self):
        return f'Conducta.view_{self.permiso}'

    def nivel_de(self, objeto):
        return objeto.categoria.nivel if self.modelo is MotivoConducta else objeto.nivel


CATALOGOS = {
    'categorias': Catalogo('categorias', 'categoria', CategoriaConducta, CategoriaForm, 'categoriaconducta', 'categoría', 'Categorías', 'Nueva categoría', 'la', 'registros'),
    'motivos': Catalogo('motivos', 'motivo', MotivoConducta, MotivoForm, 'motivoconducta', 'motivo', 'Motivos', 'Nuevo motivo', 'el', 'registros'),
    'medidas': Catalogo('medidas', 'medida', MedidaDisciplinaria, MedidaForm, 'medidadisciplinaria', 'medida', 'Medidas disciplinarias', 'Nueva medida', 'la', 'aplicaciones'),
    'suspensiones': Catalogo('suspensiones', 'suspension_motivo', MotivoSuspension, MotivoSuspensionForm, 'motivosuspension', 'motivo de suspensión', 'Motivos de suspensión', 'Nuevo motivo de suspensión', 'el', 'suspensiones'),
}
SECCIONES = [*CATALOGOS, 'reincidencia']

# Sugerencias de medidas (no se cargan solas: solo si quien administra las pide, en un nivel sin medidas)
SUGERENCIAS_DE_MEDIDAS = (
    ('Amonestación verbal', 'Llamado de atención hablado con el estudiante.', False, False),
    ('Compromiso escrito', 'El estudiante firma un compromiso de mejora.', True, False),
    ('Reunión con padres o tutores', 'Cita con la familia para acordar acciones.', True, False),
    ('Suspensión', 'Suspensión temporal de clases, con motivo y fechas.', True, True),
)


def _nivel(valor):
    return valor if valor in dict(NIVELES) else NIVEL_INICIAL


def _volver(nivel, seccion):
    return f"{reverse('conducta:configuracion')}?nivel={nivel}&seccion={seccion}"


@requiere_alguno(*CONFIGURACION)
def configuracion(request):
    nivel = _nivel(request.GET.get('nivel'))
    permitidas = [clave for clave in SECCIONES if request.user.has_perm(
        'Conducta.view_reglareincidencia' if clave == 'reincidencia' else CATALOGOS[clave].ver()
    )]
    seccion = request.GET.get('seccion')
    seccion = seccion if seccion in permitidas else permitidas[0]
    contexto = {
        'nivel': nivel, 'nombre_de_nivel': reglas.NOMBRE_DE_NIVEL[nivel], 'niveles': NIVELES, 'seccion': seccion,
        'secciones': [(clave, 'Avisos de reincidencia' if clave == 'reincidencia' else CATALOGOS[clave].plural) for clave in permitidas],
        'ajustes_seccion': 'conducta', 'puede_configurar_conducta': True,
    }
    if seccion == 'reincidencia':
        regla = ReglaReincidencia.objects.filter(nivel=nivel).first() or ReglaReincidencia(nivel=nivel, activa=False)
        contexto.update({'regla': regla, 'regla_form': ReglaReincidenciaForm(instance=regla)})
    else:
        catalogo = CATALOGOS[seccion]
        filtro = {'categoria__nivel': nivel} if catalogo.modelo is MotivoConducta else {'nivel': nivel}
        elementos = catalogo.modelo.objects.filter(**filtro).annotate(usos=Count(catalogo.uso, distinct=True))
        if catalogo.modelo is MotivoConducta:
            elementos = elementos.select_related('categoria').order_by('categoria__tipo', 'categoria__nombre', 'nombre')
        elif catalogo.modelo is CategoriaConducta:
            elementos = elementos.annotate(motivos_activos=Count('motivos', distinct=True)).order_by('tipo', 'nombre')
        else:
            elementos = elementos.order_by('nombre')
        elementos = list(elementos)
        for elemento in elementos:
            elemento.url_editar = reverse(f'conducta:{catalogo.nombre}_editar', args=[elemento.pk])
            elemento.url_estado = reverse(f'conducta:{catalogo.nombre}_estado', args=[elemento.pk])
            elemento.url_eliminar = reverse(f'conducta:{catalogo.nombre}_eliminar', args=[elemento.pk])
        contexto.update({
            'catalogo': catalogo, 'elementos': elementos,
            'puede': {accion: request.user.has_perm(f'Conducta.{prefijo}_{catalogo.permiso}')
                      for accion, prefijo in (('crear', 'add'), ('editar', 'change'), ('eliminar', 'delete'))},
            'url_crear': f"{reverse(f'conducta:{catalogo.nombre}_crear')}?nivel={nivel}",
            'sin_categorias': catalogo.modelo is MotivoConducta and not CategoriaConducta.objects.filter(nivel=nivel, activo=True).exists(),
        })
    return render(request, 'conducta/configuracion.html', contexto)


# ---------------------------------------------------------------------------
# Alta, edición, activar o desactivar y eliminar (una vista de cada una por catálogo, con sus permisos)
# ---------------------------------------------------------------------------
def _vistas(catalogo):
    def _formulario(request, objeto, nivel):
        form = catalogo.form(request.POST if request.method == 'POST' else None, instance=objeto, nivel=nivel)
        if request.method == 'POST':
            if form.is_valid():
                guardado = form.save()
                accion = 'Se guardaron los cambios de' if objeto.pk else 'Se agregó'
                messages.success(request, f'{accion} {catalogo.articulo} {catalogo.singular} «{guardado}» de {reglas.NOMBRE_DE_NIVEL[nivel].lower()}.')
                return redirect(_volver(nivel, catalogo.clave))
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
        return render(request, 'conducta/catalogo_form.html', {
            'catalogo': catalogo, 'form': form, 'objeto': objeto, 'nivel': nivel, 'nombre_de_nivel': reglas.NOMBRE_DE_NIVEL[nivel],
            'volver': _volver(nivel, catalogo.clave), 'en_uso': bool(objeto.pk) and getattr(objeto, catalogo.uso).exists(),
        })

    @requiere_permisos(f'Conducta.add_{catalogo.permiso}')
    def crear(request):
        nivel = _nivel(request.GET.get('nivel') or request.POST.get('nivel'))
        objeto = catalogo.modelo() if catalogo.modelo is MotivoConducta else catalogo.modelo(nivel=nivel)
        if catalogo.modelo is MotivoConducta and request.GET.get('categoria', '').isdigit():
            objeto.categoria_id = int(request.GET['categoria'])
        return _formulario(request, objeto, nivel)

    @requiere_permisos(f'Conducta.change_{catalogo.permiso}')
    def editar(request, pk):
        objeto = get_object_or_404(catalogo.modelo, pk=pk)
        return _formulario(request, objeto, catalogo.nivel_de(objeto))

    @require_POST
    @requiere_permisos(f'Conducta.change_{catalogo.permiso}')
    def estado(request, pk):
        objeto = get_object_or_404(catalogo.modelo, pk=pk)
        objeto.activo = not objeto.activo
        objeto.save(update_fields=['activo', 'modificado'])
        if objeto.activo:
            messages.success(request, f'«{objeto}» vuelve a ofrecerse en los registros nuevos.')
        else:
            messages.success(request, f'«{objeto}» quedó inactivo: ya no se ofrece en registros nuevos, pero los registros que lo usan lo conservan.')
        return redirect(_volver(catalogo.nivel_de(objeto), catalogo.clave))

    @require_POST
    @requiere_permisos(f'Conducta.delete_{catalogo.permiso}')
    def eliminar(request, pk):
        objeto = get_object_or_404(catalogo.modelo, pk=pk)
        nivel = catalogo.nivel_de(objeto)
        if getattr(objeto, catalogo.uso).exists():
            messages.error(request, f'«{objeto}» ya se usa en el historial: no se elimina. Desactívalo para que ya no se ofrezca.')
        elif catalogo.modelo is CategoriaConducta and objeto.motivos.exists():
            messages.error(request, f'«{objeto}» tiene motivos: elimínalos o muévelos antes, o desactiva la categoría.')
        else:
            objeto.delete()
            messages.success(request, f'Se eliminó «{objeto}».')
        return redirect(_volver(nivel, catalogo.clave))

    return crear, editar, estado, eliminar


VISTAS = {clave: _vistas(catalogo) for clave, catalogo in CATALOGOS.items()}


# ---------------------------------------------------------------------------
# Aviso de reincidencia y sugerencias
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Conducta.change_reglareincidencia')
def reincidencia(request):
    nivel = _nivel(request.POST.get('nivel'))
    regla = ReglaReincidencia.objects.filter(nivel=nivel).first() or ReglaReincidencia(nivel=nivel)
    form = ReglaReincidenciaForm(request.POST, instance=regla)
    if form.is_valid():
        regla = form.save(commit=False)
        regla.modificado_por = request.user
        regla.save()
        if regla.activa:
            messages.success(request, f'Listo: en {reglas.NOMBRE_DE_NIVEL[nivel].lower()} se avisará al llegar a {regla.incidencias} incidencias del mismo motivo en {regla.dias} días.')
        else:
            messages.success(request, f'Los avisos de reincidencia de {reglas.NOMBRE_DE_NIVEL[nivel].lower()} quedaron apagados.')
    else:
        errores = ' '.join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f'No se guardó: {errores}')
    return redirect(_volver(nivel, 'reincidencia'))


@require_POST
@requiere_permisos('Conducta.add_medidadisciplinaria')
def sugerencias(request):
    """Agrega las medidas sugeridas a un nivel que todavía no tiene ninguna (quien administra las revisa después)."""
    nivel = _nivel(request.POST.get('nivel'))
    if MedidaDisciplinaria.objects.filter(nivel=nivel).exists():
        messages.info(request, 'Ese nivel ya tiene medidas: las sugerencias solo se agregan a un catálogo vacío.')
    else:
        MedidaDisciplinaria.objects.bulk_create([
            MedidaDisciplinaria(nivel=nivel, nombre=n, descripcion=d, requiere_seguimiento=s, implica_suspension=i)
            for n, d, s, i in SUGERENCIAS_DE_MEDIDAS
        ])
        messages.success(request, f'Se agregaron {len(SUGERENCIAS_DE_MEDIDAS)} medidas sugeridas a {reglas.NOMBRE_DE_NIVEL[nivel].lower()}: revísalas y ajústalas a tu reglamento.')
    return redirect(_volver(nivel, 'medidas'))
