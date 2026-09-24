"""
=============================================================================
 MOTOR DE LENGUAJE NATURAL DEL ALMACÉN INTELIGENTE  (IA local, sin API)
=============================================================================
Este módulo interpreta instrucciones escritas en español "tal cual las
escribiría una persona" y las traduce en acciones concretas sobre el
inventario.

IMPORTANTE: todo el procesamiento ocurre 100% en este equipo, usando
únicamente expresiones regulares y la librería estándar de Python
(re, unicodedata). NO se hace ninguna llamada a internet, ni a ninguna
API, ni a ningún modelo de lenguaje en la nube. Es una IA basada en
reglas (rule-based NLU), diseñada a la medida del vocabulario de una
tienda/almacén mexicano.

Acciones que reconoce:
    HELP             -> pide ayuda / ejemplos de comandos
    CREATE_CATEGORY  -> crear una sección o marca
    DELETE_CATEGORY  -> eliminar una sección o marca
    ADD_PRODUCT      -> registrar un producto nuevo
    DELETE_PRODUCT   -> eliminar un producto existente
    UPDATE_PRICE     -> cambiar el precio de venta de un producto
    UPDATE_COST      -> cambiar el costo de un producto
    QUERY_STOCK      -> preguntar cuánto stock tiene un producto (solo lectura)
    QUERY_PRICE      -> preguntar el precio de un producto (solo lectura)
    UPDATE_STOCK     -> sumar/restar existencias (uno o varios productos)
    UNKNOWN          -> no se reconoció ninguna intención
=============================================================================
"""
import re
import unicodedata


# ===========================================================================
# UTILIDADES DE TEXTO
# ===========================================================================

def strip_accents(text):
    """Quita los acentos de un texto. Así detectamos palabras clave sin
    importar si el usuario escribió 'sección' o 'seccion', 'í' o 'i', etc.
    También la usa app.py para comparar nombres de productos/secciones
    ignorando acentos al hacer las búsquedas inteligentes."""
    nfkd = unicodedata.normalize('NFD', text)
    return ''.join(ch for ch in nfkd if unicodedata.category(ch) != 'Mn')


def _to_float(raw):
    """Convierte '10', '10.5' o '10,5' (coma decimal, común en México) a float."""
    return float(raw.replace(',', '.'))


def _smart_title(text):
    """Pone en mayúscula inicial cada palabra, EXCEPTO las que ya
    contienen números (ej. '600ml', 'x12'), para no deformarlas."""
    words = text.strip().split()
    out = []
    for w in words:
        out.append(w if any(ch.isdigit() for ch in w) else w.capitalize())
    return ' '.join(out)


def _clean(text):
    """Limpia espacios, comas sueltas y signos de interrogación al cortar
    un nombre extraído del comando."""
    return text.strip(' ,.?¡!¿').strip()


def _strip_article(text):
    """Quita un artículo suelto al inicio (el/la/los/las/un/una) para que
    búsquedas como 'la coca' o 'el platano' encuentren el producto
    correcto. Solo se usa para nombres de REFERENCIA/búsqueda (consultar,
    eliminar, actualizar precio/stock), nunca para nombres de productos o
    secciones NUEVAS, donde el artículo podría ser parte real del nombre."""
    return re.sub(r'^(?:el|la|los|las|un|una)\s+', '', text).strip()


# ===========================================================================
# VOCABULARIO: sinónimos aceptados para cada concepto del negocio
# (todo en minúsculas y sin acentos, porque se compara contra texto
#  ya normalizado con strip_accents)
# ===========================================================================
V_CREAR = r'(?:crear|nueva|nuevo|agregar|anadir|registrar|dar de alta|alta de)'
V_ELIMINAR = r'(?:eliminar|borrar|quitar|remover|dar de baja|baja de)'
V_CAMBIAR = r'(?:cambiar|actualizar|poner|ajustar|modificar|fijar)'

N_SECCION = r'(?:seccion|categoria|marca|departamento|familia)'
N_PRODUCTO = r'(?:producto|articulo|item)'

STOP_WORDS = (
    r'(?:producto|articulo|item|costo|precio|stock|inventario|cantidad|cant|'
    r'existencias|codigo|cod|barras|sku|seccion|categoria|marca|'
    r'departamento|familia)'
)

ADD_VERBS = r'(?:surtir|agregar|sumar|anadir|recibi|recibir|entraron|llegaron|reponer|repuesto)'
SUB_VERBS = r'(?:quitar|restar|sacar|merma|mermaron|perdida|romper|rompieron|daniado|daniados|robaron|robo)'


def parse_smart_command(command_text):
    """
    Punto de entrada principal. Recibe el texto escrito por el usuario y
    regresa un diccionario: { 'action': '<ACCION>', 'data': {...} }
    """
    try:
        return _parse(command_text)
    except Exception:
        # Cualquier texto raro o inesperado nunca debe tirar el servidor;
        # simplemente se reporta como comando no reconocido.
        return {'action': 'UNKNOWN', 'data': None}


def _parse(command_text):
    original = (command_text or '').strip()
    if not original:
        return {'action': 'UNKNOWN', 'data': None}

    # Texto normalizado (minúsculas, sin acentos) para detectar palabras
    # clave de forma confiable. Como quitar acentos no cambia la cantidad
    # de caracteres, los índices de texto siguen alineados con 'original',
    # así podemos recortar nombres preservando mayúsculas/acentos reales.
    text = strip_accents(original.lower())

    # -----------------------------------------------------------------
    # 0. AYUDA
    # -----------------------------------------------------------------
    if re.search(r'^(ayuda|help|que puedes hacer|comandos|opciones)\b', text):
        return {'action': 'HELP', 'data': None}

    # -----------------------------------------------------------------
    # 1. CREAR SECCIÓN / MARCA
    # -----------------------------------------------------------------
    m = re.search(rf'{V_CREAR}\s+{N_SECCION}\s+(.+)', text)
    if m:
        name = _clean(original[m.start(1):m.end(1)])
        if name:
            return {'action': 'CREATE_CATEGORY', 'data': {'name': _smart_title(name)}}

    # -----------------------------------------------------------------
    # 2. ELIMINAR SECCIÓN / MARCA
    # -----------------------------------------------------------------
    m = re.search(rf'{V_ELIMINAR}\s+(?:la\s+|el\s+)?{N_SECCION}\s+(.+)', text)
    if m:
        name = _clean(original[m.start(1):m.end(1)])
        if name:
            return {'action': 'DELETE_CATEGORY', 'data': {'name': name}}

    # -----------------------------------------------------------------
    # 3. REGISTRAR PRODUCTO NUEVO COMPLETO
    # -----------------------------------------------------------------
    if re.search(rf'{V_CREAR}\s+{N_PRODUCTO}\b', text):
        trigger = re.search(rf'{N_PRODUCTO}\b', text)
        start_idx = trigger.end()

        barcode_m = re.search(r'(?:codigo|cod\.?|barras|sku)\s+([a-z0-9\-]+)', text)
        cost_m = re.search(r'costo\s+(?:de\s+)?\$?\s*(\d+(?:[.,]\d+)?)', text)
        price_m = re.search(r'precio\s+(?:de\s+)?\$?\s*(\d+(?:[.,]\d+)?)', text)
        stock_m = re.search(r'(?:stock|inventario|cant(?:idad)?|existencias)\s+(?:de\s+)?(\d+)', text)
        category_m = re.search(
            rf'{N_SECCION}\s+((?:(?!{STOP_WORDS}\b)[a-z0-9]+\s*)+)', text
        )

        # El nombre del producto es lo que queda inmediatamente después
        # de la palabra "producto/artículo", hasta el siguiente campo
        # reconocido (costo, precio, stock, código o sección) que aparezca.
        field_starts = [
            mm.start() for mm in (barcode_m, cost_m, price_m, stock_m, category_m)
            if mm and mm.start() >= start_idx
        ]
        end_idx = min(field_starts) if field_starts else len(text)
        raw_name = original[start_idx:end_idx].replace(',', ' ')
        name = _smart_title(_clean(raw_name))

        category_name = _smart_title(_clean(category_m.group(1))) if category_m else 'General'

        return {
            'action': 'ADD_PRODUCT',
            'data': {
                'name': name,
                'barcode': barcode_m.group(1) if barcode_m else None,
                'cost': _to_float(cost_m.group(1)) if cost_m else 0.0,
                'price': _to_float(price_m.group(1)) if price_m else 0.0,
                'stock': int(stock_m.group(1)) if stock_m else 0,
                'category_name': category_name,
            }
        }

    # -----------------------------------------------------------------
    # 4. ELIMINAR PRODUCTO
    # -----------------------------------------------------------------
    m = re.search(rf'{V_ELIMINAR}\s+(?:el\s+|la\s+)?{N_PRODUCTO}\s+(.+)', text)
    if m:
        name = _strip_article(_clean(text[m.start(1):m.end(1)]))
        if name:
            return {'action': 'DELETE_PRODUCT', 'data': {'name': name}}

    # -----------------------------------------------------------------
    # 5. CAMBIAR PRECIO
    # -----------------------------------------------------------------
    m = re.search(
        rf'{V_CAMBIAR}\s+(?:el\s+)?precio\s+(?:de\s+|del\s+|al\s+)?(.+?)\s+(?:a|en)\s+\$?\s*(\d+(?:[.,]\d+)?)',
        text
    )
    if m:
        name = _strip_article(_clean(text[m.start(1):m.end(1)]))
        value = _to_float(m.group(2))
        if name:
            return {'action': 'UPDATE_PRICE', 'data': {'name': name, 'value': value}}

    # -----------------------------------------------------------------
    # 6. CAMBIAR COSTO
    # -----------------------------------------------------------------
    m = re.search(
        rf'{V_CAMBIAR}\s+(?:el\s+)?costo\s+(?:de\s+|del\s+|al\s+)?(.+?)\s+(?:a|en)\s+\$?\s*(\d+(?:[.,]\d+)?)',
        text
    )
    if m:
        name = _strip_article(_clean(text[m.start(1):m.end(1)]))
        value = _to_float(m.group(2))
        if name:
            return {'action': 'UPDATE_COST', 'data': {'name': name, 'value': value}}

    # -----------------------------------------------------------------
    # 7. CONSULTAR STOCK (solo lectura, no modifica nada)
    # -----------------------------------------------------------------
    stock_query_patterns = [
        r'cuant[oa]s?\s+(?:stock|inventario|existencias|piezas|unidades)\s+(?:de\s+|hay de\s+|tiene\s+|tengo\s+)?(.+)',
        r'(?:stock|inventario|existencias)\s+de\s+(.+)',
        r'cuant[oa]s?\s+(.+?)\s+(?:hay|quedan|tenemos|tengo)\b',
    ]
    for pattern in stock_query_patterns:
        m = re.search(pattern, text)
        if m:
            name = _strip_article(_clean(m.group(1)))
            if name:
                return {'action': 'QUERY_STOCK', 'data': {'name': name}}

    # -----------------------------------------------------------------
    # 8. CONSULTAR PRECIO (solo lectura, no modifica nada)
    # -----------------------------------------------------------------
    price_query_patterns = [
        r'cual\s+es\s+el\s+precio\s+de\s+(.+)',
        r'cuanto\s+cuesta\s+(.+)',
        r'que\s+precio\s+tiene\s+(.+)',
        r'^precio\s+de\s+(.+)',
    ]
    for pattern in price_query_patterns:
        m = re.search(pattern, text)
        if m:
            name = _strip_article(_clean(m.group(1)))
            if name:
                return {'action': 'QUERY_PRICE', 'data': {'name': name}}

    # -----------------------------------------------------------------
    # 9. SURTIDO / AJUSTE DE STOCK (uno o varios productos, separados por coma)
    # -----------------------------------------------------------------
    items = []
    parts = text.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue

        mm = re.search(r'^([+-]?\d+)\s+(.+)', part)
        if mm:
            items.append({'name': _strip_article(_clean(mm.group(2))), 'qty': int(mm.group(1))})
            continue

        mm = re.search(rf'{ADD_VERBS}\s+(\d+)\s+(?:unidades?\s+(?:de\s+)?)?(.+)', part)
        if mm:
            items.append({'name': _strip_article(_clean(mm.group(2))), 'qty': int(mm.group(1))})
            continue

        mm = re.search(rf'{SUB_VERBS}\s+(\d+)\s+(?:unidades?\s+(?:de\s+)?)?(.+)', part)
        if mm:
            items.append({'name': _strip_article(_clean(mm.group(2))), 'qty': -int(mm.group(1))})
            continue

    items = [it for it in items if it['name']]
    if items:
        return {'action': 'UPDATE_STOCK', 'data': items}

    # -----------------------------------------------------------------
    # 10. NO SE RECONOCIÓ NINGÚN PATRÓN
    # -----------------------------------------------------------------
    return {'action': 'UNKNOWN', 'data': None}
