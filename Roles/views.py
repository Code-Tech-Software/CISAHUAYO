from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from CISAHUAYO.permisos import requiere_permisos
from Usuarios import catalogo
from Usuarios.models import Rol
from Usuarios.seguridad import (
    ACCION_ALTA,
    ACCION_BAJA,
    ACCION_CAMBIO,
    historial,
    objetos_de_permisos,
    permisos_de_rol,
    permisos_efectivos,
    registrar,
    rol_de,
)

from .forms import RolForm

Usuario = get_user_model()


def _roles():
    """Los roles con cuántos usuarios activos los tienen."""
    return Rol.objects.select_related('grupo').annotate(
        usuarios=Count('grupo__user', filter=Q(grupo__user__is_active=True), distinct=True),
    )


def _es_mi_rol(request, rol):
    """El rol que uno mismo tiene no lo edita uno mismo (salvo un superusuario): evita quitarse permisos o dárselos."""
    return not request.user.is_superuser and getattr(rol_de(request.user), 'pk', None) == rol.pk


def _alcanza(request, rol):
    """Quien no es superusuario solo administra roles que no tengan más permisos que él: no puede recortar ni apagar
    un rol más poderoso que el suyo."""
    return request.user.is_superuser or permisos_de_rol(rol) <= permisos_efectivos(request.user)


def _administrable(request, rol):
    if not _alcanza(request, rol):
        raise PermissionDenied('No puedes administrar un rol con más permisos que tú.')
    return rol


def _matriz(request, marcados, editable):
    """El catálogo con lo marcado y, al editar, qué casillas están bloqueadas porque quien edita no las tiene."""
    matriz = catalogo.resumen(marcados)
    if editable:
        propios = permisos_efectivos(request.user)
        for modulo in matriz:
            for fila in modulo['filas']:
                for celda in fila['celdas']:
                    if celda:
                        celda['bloqueada'] = celda['permiso'] not in propios
    return matriz


def _resumen_de_cambios(otorgados, retirados):
    partes = []
    if otorgados:
        partes.append('Permisos concedidos: ' + ', '.join(catalogo.etiqueta_de(p) for p in otorgados[:8]) + (f' y {len(otorgados) - 8} más' if len(otorgados) > 8 else '') + '.')
    if retirados:
        partes.append('Permisos retirados: ' + ', '.join(catalogo.etiqueta_de(p) for p in retirados[:8]) + (f' y {len(retirados) - 8} más' if len(retirados) > 8 else '') + '.')
    return ' '.join(partes)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Usuarios.view_rol')
def rol_lista(request):
    viendo_inactivos = request.GET.get('estado') == 'INACTIVO'
    todos = list(_roles())
    roles = [rol for rol in todos if rol.activo != viendo_inactivos]
    puede_editar = request.user.has_perm('Usuarios.change_rol')
    for rol in roles:
        permisos = permisos_de_rol(rol)
        rol.total_permisos = len(permisos)
        rol.modulos = [m['modulo'] for m in catalogo.resumen(permisos) if m['concedidos']]
        rol.puede_editar = puede_editar and not rol.es_sistema and not _es_mi_rol(request, rol) and _alcanza(request, rol)
    return render(request, 'roles/lista.html', {
        'roles': roles,
        'viendo_inactivos': viendo_inactivos,
        'total_activos': sum(1 for r in todos if r.activo),
        'total_inactivos': sum(1 for r in todos if not r.activo),
        'total_posibles': len(catalogo.TODOS),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, rol=None):
    return render(request, 'roles/form.html', {
        'form': form,
        'rol': rol,
        'es_edicion': rol is not None,
        'matriz': _matriz(request, form.marcados, True),
        'total_posibles': len(catalogo.TODOS),
    })


@requiere_permisos('Usuarios.add_rol')
def rol_crear(request):
    form = RolForm(request.POST if request.method == 'POST' else None, actor=request.user)
    if request.method == 'POST':
        if form.is_valid():
            rol = form.save()
            registrar(request.user, rol, ACCION_ALTA, _resumen_de_cambios(form.otorgados, []) or 'Rol creado sin permisos.')
            messages.success(request, f'El rol «{rol}» fue creado con {len(form.permisos_finales)} permiso{"s" if len(form.permisos_finales) != 1 else ""}.')
            return redirect('roles:detalle', rol.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Usuarios.change_rol')
def rol_editar(request, pk):
    rol = get_object_or_404(Rol.objects.select_related('grupo'), pk=pk)
    if rol.es_sistema:
        messages.info(request, f'«{rol}» es un rol del sistema: tiene acceso total y no se puede modificar.')
        return redirect('roles:detalle', rol.pk)
    _administrable(request, rol)
    if _es_mi_rol(request, rol):
        messages.error(request, f'«{rol}» es tu propio rol: pide a otra persona con ese permiso que lo modifique.')
        return redirect('roles:detalle', rol.pk)

    form = RolForm(request.POST if request.method == 'POST' else None, actor=request.user, rol=rol)
    if request.method == 'POST':
        if form.is_valid():
            antes = rol.nombre
            rol = form.save()
            resumen = _resumen_de_cambios(form.otorgados, form.retirados)
            if antes != rol.nombre:
                resumen = f'Nombre: «{antes}» → «{rol.nombre}». {resumen}'.strip()
            if resumen:
                registrar(request.user, rol, ACCION_CAMBIO, resumen)
            afectados = Usuario.objects.filter(groups=rol.grupo, is_active=True).count()
            aviso = f' Los cambios ya aplican a {afectados} usuario{"s" if afectados != 1 else ""}.' if (form.otorgados or form.retirados) and afectados else ''
            messages.success(request, f'El rol «{rol}» se actualizó.{aviso}')
            return redirect('roles:detalle', rol.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, rol)


# ---------------------------------------------------------------------------
# Perfil del rol
# ---------------------------------------------------------------------------
@requiere_permisos('Usuarios.view_rol')
def rol_detalle(request, pk):
    rol = get_object_or_404(_roles(), pk=pk)
    permisos = permisos_de_rol(rol)
    matriz = catalogo.resumen(permisos)
    usuarios = list(
        Usuario.objects.filter(Q(groups=rol.grupo) | (Q(is_superuser=True) if rol.acceso_total else Q(pk__in=[])))
        .distinct().order_by('-is_active', 'first_name', 'last_name', 'username')[:60]
    )
    alcanza = _alcanza(request, rol)
    puede_editar = (
        request.user.has_perm('Usuarios.change_rol') and not rol.es_sistema and not _es_mi_rol(request, rol) and alcanza
    )
    return render(request, 'roles/detalle.html', {
        'rol': rol,
        'matriz': matriz,
        'total_permisos': sum(m['concedidos'] for m in matriz),
        'total_posibles': len(catalogo.TODOS),
        'usuarios': usuarios,
        'historial': historial(rol),
        'puede_editar': puede_editar,
        'puede_desactivar': request.user.has_perm('Usuarios.delete_rol') and not rol.es_sistema and rol.activo and alcanza,
        'puede_copiar': request.user.has_perm('Usuarios.add_rol'),
    })


# ---------------------------------------------------------------------------
# Copiar, desactivar y reactivar
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Usuarios.add_rol')
def rol_copiar(request, pk):
    """Crea «Copia de X» con los mismos permisos (los que quien copia tiene) para ajustarlo después."""
    origen = get_object_or_404(Rol.objects.select_related('grupo'), pk=pk)
    base = f'Copia de {origen.nombre}'[:75]
    nombre, n = base, 1
    while Group.objects.filter(name__iexact=nombre).exists():
        n += 1
        nombre = f'{base} ({n})'

    propios = permisos_efectivos(request.user)
    permisos = permisos_de_rol(origen) & propios
    omitidos = len(permisos_de_rol(origen) - propios)
    with transaction.atomic():
        grupo = Group.objects.create(name=nombre)
        rol = Rol.objects.create(grupo=grupo, descripcion=origen.descripcion, tono=origen.tono)
        grupo.permissions.set(objetos_de_permisos(permisos))
    registrar(request.user, rol, ACCION_ALTA, f'Copia del rol «{origen}».')
    aviso = f' Se omitieron {omitidos} permiso{"s" if omitidos != 1 else ""} que tú no tienes.' if omitidos else ''
    messages.success(request, f'Se creó «{rol}» con los permisos de «{origen}».{aviso} Ajústalo con «Editar».')
    return redirect('roles:detalle', rol.pk)


@require_POST
@requiere_permisos('Usuarios.delete_rol')
def rol_baja(request, pk):
    """Desactiva el rol (no se borra): ya no se asigna a cuentas nuevas. Antes no debe tener usuarios activos."""
    rol = get_object_or_404(_roles(), pk=pk)
    if not rol.es_sistema:
        _administrable(request, rol)
    if rol.es_sistema:
        messages.error(request, f'«{rol}» es un rol del sistema y no se puede desactivar.')
    elif not rol.activo:
        messages.info(request, f'«{rol}» ya estaba desactivado.')
    elif rol.usuarios:
        messages.error(
            request,
            f'«{rol}» lo tienen {rol.usuarios} usuario{"s" if rol.usuarios != 1 else ""} activo{"s" if rol.usuarios != 1 else ""}. '
            'Cámbiales el rol antes de desactivarlo.',
        )
    else:
        rol.activo = False
        rol.save(update_fields=['activo', 'modificado'])
        registrar(request.user, rol, ACCION_BAJA, 'Rol desactivado.')
        messages.success(request, f'El rol «{rol}» fue desactivado. Se conserva y puedes reactivarlo desde el filtro «Desactivados».')
    if request.POST.get('volver') == 'detalle':
        return redirect('roles:detalle', rol.pk)
    return redirect('roles:lista')


@require_POST
@requiere_permisos('Usuarios.change_rol')
def rol_reactivar(request, pk):
    rol = _administrable(request, get_object_or_404(Rol.objects.select_related('grupo'), pk=pk))
    if not rol.activo:
        rol.activo = True
        rol.save(update_fields=['activo', 'modificado'])
        registrar(request.user, rol, ACCION_CAMBIO, 'Rol reactivado.')
        messages.success(request, f'El rol «{rol}» fue reactivado.')
    return redirect('roles:lista')
