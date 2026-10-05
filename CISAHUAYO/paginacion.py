"""Paginación de listados con el Paginator de Django.

Solo se consulta la página que se muestra (LIMIT/OFFSET) más un COUNT, en lugar de traer
todos los registros: el costo no crece con el tamaño de la tabla. Los `prefetch_related`
del queryset también se aplican únicamente a los registros de la página.
"""
from django.core.paginator import Paginator

OPCIONES_POR_PAGINA = (10, 20, 50, 100)
POR_PAGINA_DEFECTO = 20


def paginar(request, queryset, por_defecto=POR_PAGINA_DEFECTO):
    """Devuelve (página, rango de números para mostrar, registros por página).

    `?page=` elige la página (una inválida cae en la primera o la última) y `?por_pagina=`
    el tamaño, limitado a OPCIONES_POR_PAGINA para que nadie pida miles de filas de golpe.
    """
    try:
        por_pagina = int(request.GET.get('por_pagina', por_defecto))
    except (TypeError, ValueError):
        por_pagina = por_defecto
    if por_pagina not in OPCIONES_POR_PAGINA:
        por_pagina = por_defecto

    paginador = Paginator(queryset, por_pagina)
    pagina = paginador.get_page(request.GET.get('page'))
    rango = paginador.get_elided_page_range(pagina.number, on_each_side=1, on_ends=1)
    return pagina, rango, por_pagina
