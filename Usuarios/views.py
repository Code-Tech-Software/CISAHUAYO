from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from . import catalogo
from .forms import CambioContrasenaForm, FiltroUsuariosForm, MiCuentaForm, UsuarioForm
from .docentes import profesor_de
from .models import PerfilUsuario
from .seguridad import (
    ACCION_ALTA,
    ACCION_BAJA,
    ACCION_CAMBIO,
    contrasena_temporal,
    es_ultimo_administrador,
    historial,
    nombre_de,
    permisos_de_cuenta,
    permisos_efectivos,
    puede_gestionar,
    registrar,
    rol_de,
)
from .signals import SESION_CAMBIO_DE_CONTRASENA

Usuario = get_user_model()
SESION_CREDENCIALES = 'credenciales_usuario'


def _consulta():
    """Usuarios con su perfil, su ficha de profesor y su rol ya cargados (sin una consulta por fila)."""
    return Usuario.objects.select_related('perfil', 'profesor').prefetch_related(
        Prefetch('groups', queryset=Group.objects.select_related('rol').prefetch_related('permissions')),
        'user_permissions',
    )


def _gestionable(request, usuario):
    """Si quien pide puede actuar sobre este usuario, o 403: no se puede tocar a quien tiene más poder que uno mismo."""
    if not puede_gestionar(request.user, usuario):
        raise PermissionDenied('No puedes administrar a un usuario con más permisos que tú.')
    return usuario


def guardar_credenciales(request, usuario, contrasena, titulo, url=None, escrita=False):
    """Deja en la sesión las credenciales de una cuenta para mostrarlas una sola vez (la contraseña no se guarda en claro)."""
    request.session[SESION_CREDENCIALES] = {
        'pk': usuario.pk,
        'nombre': nombre_de(usuario),
        'url': url or reverse('usuarios:detalle', args=[usuario.pk]),
        'usuario': usuario.username,
        'contrasena': contrasena,
        'titulo': titulo,
        'etiqueta': 'Contraseña inicial' if escrita else 'Contraseña temporal',
    }


def _texto_de_la_ficha(form):
    """« Se registró su ficha de profesor.» o « Quedó vinculada con el profesor X.» (o nada)."""
    profesor = getattr(form, 'profesor_vinculado', None)
    if profesor is None:
        return ''
    if form.docente.profesor_creado:
        return f' Se registró su ficha de profesor ({profesor}).'
    return f' Quedó vinculada con la ficha del profesor {profesor}.'


def _anotar_en_la_ficha(request, form, usuario):
    profesor = getattr(form, 'profesor_vinculado', None)
    if profesor is not None:
        accion = 'Ficha registrada junto con' if form.docente.profesor_creado else 'Se vinculó con'
        registrar(request.user, profesor, ACCION_CAMBIO, f'{accion} la cuenta de acceso «{usuario.username}».')


def _cambios_de(form):
    """Texto con qué cambió en un formulario (para la bitácora)."""
    etiquetas = {nombre: str(campo.label) for nombre, campo in form.fields.items()}
    cambios = [etiquetas[n] for n in form.changed_data if n in etiquetas and n != 'rol']
    return ', '.join(cambios)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('auth.view_user')
def usuario_lista(request):
    filtro = FiltroUsuariosForm(request.GET)
    pagina, rango_paginas, por_pagina = paginar(request, filtro.filtrar(_consulta()))

    puede_actuar = request.user.has_perm('auth.change_user') or request.user.has_perm('auth.delete_user')
    propios = permisos_efectivos(request.user) if puede_actuar else set()
    for usuario in pagina:
        usuario.rol_actual = rol_de(usuario)
        usuario.gestionable = puede_actuar and puede_gestionar(request.user, usuario, propios)
        usuario.es_yo = usuario.pk == request.user.pk

    conteos = Usuario.objects.aggregate(
        activos=Count('pk', filter=Q(is_active=True)), inactivos=Count('pk', filter=Q(is_active=False)),
    )
    return render(request, 'usuarios/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'total_activos': conteos['activos'],
        'total_inactivos': conteos['inactivos'],
        'viendo_inactivos': filtro.activos.get('estado') == 'INACTIVO',
        'filtros_activos': {k: v for k, v in filtro.activos.items() if k not in ('orden', 'estado')},
        # Tras crear una cuenta se muestran, una sola vez, sus credenciales temporales
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, usuario=None):
    return render(request, 'usuarios/form.html', {'form': form, 'usuario': usuario, 'es_edicion': usuario is not None})


@requiere_permisos('auth.add_user')
def usuario_crear(request):
    form = UsuarioForm(request.POST if request.method == 'POST' else None, actor=request.user)
    if request.method == 'POST':
        if form.is_valid():
            usuario = form.save()
            rol = rol_de(usuario)
            registrar(request.user, usuario, ACCION_ALTA, f'Cuenta creada con el rol «{rol}».{_texto_de_la_ficha(form)}')
            _anotar_en_la_ficha(request, form, usuario)
            guardar_credenciales(request, usuario, form.contrasena_en_claro, 'Cuenta creada', escrita=form.contrasena_escrita)
            messages.success(request, f'La cuenta de {nombre_de(usuario)} fue creada con el rol «{rol}».{_texto_de_la_ficha(form)}')
            return redirect('usuarios:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('auth.change_user')
def usuario_editar(request, pk):
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    form = UsuarioForm(request.POST if request.method == 'POST' else None, instance=usuario, actor=request.user)
    if request.method == 'POST':
        if form.is_valid():
            usuario = form.save()
            partes = []
            if form.rol_cambio:
                partes.append(f'Rol: {form.rol_anterior or "sin rol"} → {rol_de(usuario)}.')
            cambios = _cambios_de(form)
            if cambios:
                partes.append(f'Datos modificados: {cambios}.')
            if form.profesor_vinculado:
                partes.append(_texto_de_la_ficha(form).strip())
                _anotar_en_la_ficha(request, form, usuario)
            if partes:
                registrar(request.user, usuario, ACCION_CAMBIO, ' '.join(partes))
            messages.success(request, f'Los datos de {nombre_de(usuario)} se actualizaron.{_texto_de_la_ficha(form)}')
            return redirect('usuarios:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, usuario)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@requiere_permisos('auth.view_user')
def usuario_detalle(request, pk):
    usuario = get_object_or_404(_consulta(), pk=pk)
    rol = rol_de(usuario)
    es_yo = usuario.pk == request.user.pk
    gestionable = puede_gestionar(request.user, usuario)
    # Una cuenta desactivada no tiene permisos en Django: se muestra lo que tendría al reactivarla
    permisos = permisos_efectivos(usuario) if usuario.is_active else permisos_de_cuenta(usuario)
    resumen = catalogo.resumen(permisos)
    ultimo_administrador = es_ultimo_administrador(usuario)

    return render(request, 'usuarios/detalle.html', {
        'usuario': usuario,
        'perfil': getattr(usuario, 'perfil', None) or PerfilUsuario(usuario=usuario),
        'profesor': profesor_de(usuario),
        'rol': rol,
        'es_yo': es_yo,
        'resumen': resumen,
        'total_permisos': sum(m['concedidos'] for m in resumen),
        'historial': historial(usuario),
        'puede_editar': request.user.has_perm('auth.change_user') and gestionable,
        'puede_desactivar': (
            request.user.has_perm('auth.delete_user') and gestionable and usuario.is_active
            and not es_yo and not ultimo_administrador
        ),
        'motivo_no_desactivar': (
            'Es tu propia cuenta.' if es_yo else 'Es el único administrador activo.' if ultimo_administrador else ''
        ),
        'puede_restablecer': request.user.has_perm('auth.change_user') and gestionable and usuario.is_active and not es_yo,
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
    })


# ---------------------------------------------------------------------------
# Desactivar, reactivar y restablecer la contraseña
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('auth.delete_user')
def usuario_baja(request, pk):
    """Desactiva la cuenta (no se borra): deja de poder entrar, pero conserva su historial y su rol."""
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes desactivar tu propia cuenta.')
    elif es_ultimo_administrador(usuario):
        messages.error(request, 'Es el único administrador activo: si lo desactivas, nadie podría administrar el sistema.')
    elif not usuario.is_active:
        messages.info(request, f'La cuenta de {nombre_de(usuario)} ya estaba desactivada.')
    else:
        usuario.is_active = False
        usuario.save(update_fields=['is_active'])
        registrar(request.user, usuario, ACCION_BAJA, 'Cuenta desactivada.')
        messages.success(
            request,
            f'La cuenta de {nombre_de(usuario)} fue desactivada: ya no puede entrar. Se conserva y puedes reactivarla desde el filtro «Desactivados».',
        )
    if request.POST.get('volver') == 'detalle':
        return redirect('usuarios:detalle', usuario.pk)
    return redirect('usuarios:lista')


@require_POST
@requiere_permisos('auth.change_user')
def usuario_reactivar(request, pk):
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if not usuario.is_active:
        usuario.is_active = True
        usuario.save(update_fields=['is_active'])
        registrar(request.user, usuario, ACCION_CAMBIO, 'Cuenta reactivada.')
        messages.success(request, f'La cuenta de {nombre_de(usuario)} fue reactivada.')
    return redirect('usuarios:lista')


@require_POST
@requiere_permisos('auth.change_user')
def usuario_restablecer(request, pk):
    """Genera una contraseña temporal nueva (se muestra una sola vez); la persona deberá cambiarla al entrar."""
    usuario = _gestionable(request, get_object_or_404(Usuario, pk=pk))
    if usuario.pk == request.user.pk:
        messages.error(request, 'Para cambiar tu propia contraseña usa «Mi cuenta».')
        return redirect('usuarios:detalle', usuario.pk)
    if not usuario.is_active:
        messages.error(request, 'Reactiva la cuenta antes de restablecer su contraseña.')
        return redirect('usuarios:detalle', usuario.pk)

    contrasena = contrasena_temporal()
    usuario.set_password(contrasena)   # además cierra sus sesiones abiertas: el hash de la sesión deja de coincidir
    usuario.save(update_fields=['password'])
    perfil = PerfilUsuario.de(usuario)
    perfil.debe_cambiar_contrasena = True
    perfil.save(update_fields=['debe_cambiar_contrasena', 'modificado'])
    registrar(request.user, usuario, ACCION_CAMBIO, 'Contraseña restablecida (deberá cambiarla al entrar).')
    guardar_credenciales(request, usuario, contrasena, 'Contraseña restablecida')
    messages.success(request, f'Se generó una contraseña temporal para {nombre_de(usuario)}. Entrégasela: no se volverá a mostrar.')
    return redirect('usuarios:detalle', usuario.pk)


# ---------------------------------------------------------------------------
# Mi cuenta (cualquier usuario con sesión)
# ---------------------------------------------------------------------------
@login_required
def cuenta_perfil(request):
    form = MiCuentaForm(request.POST if request.method == 'POST' else None, instance=request.user)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Tus datos se actualizaron.')
            return redirect('cuenta:perfil')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    permisos = permisos_efectivos(request.user)
    resumen = catalogo.resumen(permisos)
    return render(request, 'usuarios/cuenta.html', {
        'form': form,
        'perfil': PerfilUsuario.de(request.user),
        'rol': rol_de(request.user),
        'resumen': resumen,
        'total_permisos': sum(m['concedidos'] for m in resumen),
    })


@login_required
def cuenta_contrasena(request):
    perfil = PerfilUsuario.de(request.user)
    obligatorio = perfil.debe_cambiar_contrasena
    form = CambioContrasenaForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, request.user)   # sigue con la sesión abierta
            perfil.debe_cambiar_contrasena = False
            perfil.save(update_fields=['debe_cambiar_contrasena', 'modificado'])
            request.session[SESION_CAMBIO_DE_CONTRASENA] = False
            registrar(request.user, request.user, ACCION_CAMBIO, 'Cambió su propia contraseña.')
            messages.success(request, 'Tu contraseña se actualizó.')
            return redirect('inicio' if obligatorio else 'cuenta:perfil')
        messages.error(request, 'No se pudo cambiar la contraseña: revisa los campos marcados.')
    return render(request, 'usuarios/contrasena.html', {'form': form, 'obligatorio': obligatorio})
