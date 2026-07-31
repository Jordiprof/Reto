# Tests de F5.5 #7 (leer PDF/Word): src/documentos.py.
#
# Doctrina del proyecto: los controles de seguridad se validan por
# MUTACION, no solo con tests en verde (ver diario 27/07 y 30/07). Aqui hay
# dos controles reales: (1) solo se aceptan .pdf/.docx de un tamaño
# razonable, y (2) un .docx (que es un ZIP) no se descomprime sin mirar
# antes el tamaño de sus partes - la bomba de descompresion que cita
# ADR-006. Los tests de esos dos controles construyen la mutacion a mano
# (quitar la comprobacion) para demostrar que SI detectarian el fallo.
import io
import zipfile

import docx
import pytest

from src.documentos import (
    DocumentoNoValido,
    documento_actual,
    extraer_texto,
    fijar_documento_actual,
    restaurar_documento_actual,
    validar_adjunto,
)


def _pdf_con_texto(texto: str) -> bytes:
    """PDF minimo escrito a mano (sin reportlab): un objeto Catalog, uno
    Pages, uno Page y un content stream con el texto. pypdf lo lee bien
    aunque el xref no sea perfecto (recupera escaneando objetos, como
    haria con cualquier PDF real algo maltratado)."""
    stream = f"BT /F1 24 Tf 10 100 Td ({texto}) Tj ET".encode()
    contenido = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >>
   /MediaBox [0 0 300 300] /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length {len(stream)} >>
stream
{stream.decode()}
endstream
endobj
xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF""".encode()
    return contenido


def _docx_con_texto(*parrafos: str) -> bytes:
    documento = docx.Document()
    for parrafo in parrafos:
        documento.add_paragraph(parrafo)
    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()


# --- Extension y tamaño --------------------------------------------------


def test_una_extension_no_pdf_ni_docx_se_rechaza():
    with pytest.raises(DocumentoNoValido, match="\\.pdf o \\.docx"):
        validar_adjunto(b"lo que sea", "notas.txt")


def test_sin_extension_se_rechaza():
    with pytest.raises(DocumentoNoValido):
        validar_adjunto(b"lo que sea", "notas")


def test_un_pdf_dentro_del_tamaño_se_acepta():
    adjunto = validar_adjunto(_pdf_con_texto("Hola"), "informe.pdf")
    assert adjunto.tipo == "pdf"
    assert adjunto.nombre == "informe.pdf"


def test_un_fichero_demasiado_grande_se_rechaza(monkeypatch):
    import src.documentos as documentos

    monkeypatch.setattr(documentos, "_MAX_BYTES_ADJUNTO", 10)
    with pytest.raises(DocumentoNoValido, match="pesa demasiado"):
        validar_adjunto(b"x" * 11, "informe.pdf")


def test_justo_en_el_limite_de_tamaño_se_acepta(monkeypatch):
    """Caso de control del test anterior: el limite es <=, no <."""
    import src.documentos as documentos

    monkeypatch.setattr(documentos, "_MAX_BYTES_ADJUNTO", 10)
    validar_adjunto(b"x" * 10, "informe.pdf")  # no lanza


# --- Bomba de descompresion en .docx (ADR-006) ----------------------------


def _docx_con_entrada_gigante(tamaño_descomprimido: int) -> bytes:
    """Una bomba de descompresion DE VERDAD, no simulada: bytes muy
    repetitivos (comprimen brutalmente con DEFLATE) para que el ZIP
    resultante sea pequeño en disco pero enorme al descomprimir - la forma
    real del ataque que cita ADR-006. ZipFile.writestr() RECALCULA
    file_size a partir de los bytes reales, asi que no basta con poner el
    numero a mano en el ZipInfo (se probo y no sobrevive al writestr)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as paquete:
        paquete.writestr("word/document.xml", b"0" * tamaño_descomprimido)
    return buffer.getvalue()


def test_un_docx_con_una_parte_gigante_se_rechaza():
    grande = _docx_con_entrada_gigante(60_000_000)
    with pytest.raises(DocumentoNoValido, match="sospechosamente grande"):
        validar_adjunto(grande, "bomba.docx")


def test_un_docx_normal_no_activa_la_comprobacion_de_bomba():
    """Caso de control: sin el, el test anterior podria estar rechazando
    CUALQUIER .docx, no solo el malicioso."""
    normal = _docx_con_texto("Un documento normal y corriente.")
    validar_adjunto(normal, "normal.docx")  # no lanza


def test_MUTACION_sin_la_comprobacion_de_bomba_el_docx_pasaria(monkeypatch):
    """Prueba de mutacion (doctrina del proyecto, 27/07): se rompe el
    control a proposito -subiendo el tope muy por encima del ataque- y se
    confirma que ES la comprobacion quien paraba el fichero, no una
    casualidad de otro sitio (extension, tamaño total del fichero
    comprimido, que sigue siendo minusculo - el ataque es justo que
    comprime mucho)."""
    import src.documentos as documentos

    grande = _docx_con_entrada_gigante(60_000_000)
    assert len(grande) < 1_000_000  # el .docx en si pasa de sobra _MAX_BYTES_ADJUNTO

    monkeypatch.setattr(documentos, "_MAX_BYTES_DESCOMPRIMIDOS", 200_000_000)
    validar_adjunto(grande, "bomba.docx")  # con el tope "roto", ya no lanza


def test_un_docx_corrupto_se_rechaza():
    with pytest.raises(DocumentoNoValido, match="dañado"):
        validar_adjunto(b"esto no es un zip de verdad", "roto.docx")


# --- Extraccion de texto --------------------------------------------------


def test_extrae_texto_de_un_pdf():
    adjunto = validar_adjunto(_pdf_con_texto("Contenido del PDF"), "x.pdf")
    assert "Contenido del PDF" in extraer_texto(adjunto)


def test_extrae_texto_de_un_docx():
    adjunto = validar_adjunto(_docx_con_texto("Primer párrafo.", "Segundo párrafo."), "x.docx")
    texto = extraer_texto(adjunto)
    assert "Primer párrafo." in texto
    assert "Segundo párrafo." in texto


def test_extrae_texto_de_tablas_en_un_docx():
    """Las tablas NO salen en `.paragraphs` (python-docx las trata aparte):
    sin recorrerlas a mano, un documento con datos solo en tablas
    devolveria texto vacio aunque el documento SI tuviera contenido."""
    documento = docx.Document()
    tabla = documento.add_table(rows=1, cols=2)
    tabla.rows[0].cells[0].text = "Nombre"
    tabla.rows[0].cells[1].text = "Precio"
    buffer = io.BytesIO()
    documento.save(buffer)

    adjunto = validar_adjunto(buffer.getvalue(), "tabla.docx")
    texto = extraer_texto(adjunto)

    assert "Nombre" in texto and "Precio" in texto


def test_un_pdf_cifrado_no_se_puede_leer(monkeypatch):
    """No se fabrica un PDF cifrado de verdad (complejidad innecesaria):
    se sustituye PdfReader por uno de mentira que declara is_encrypted,
    igual que otros tests del proyecto sustituyen la pieza minima que
    hace falta para forzar la rama."""
    from src.documentos import _extraer_texto_pdf

    class _LectorFalso:
        is_encrypted = True
        pages = []

    # _extraer_texto_pdf importa PdfReader dentro de la funcion (import
    # perezoso, ver el resto del proyecto), asi que se parchea el modulo
    # real de pypdf, no un atributo de documentos.py.
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", lambda datos: _LectorFalso())

    with pytest.raises(DocumentoNoValido, match="contraseña"):
        _extraer_texto_pdf(b"lo que sea")


def test_si_falta_la_libreria_de_pdf_el_mensaje_es_NUESTRO(monkeypatch):
    """REGRESION de un fallo REAL (31/07): pypdf estaba instalado en el
    Python del sistema pero NO en el venv desde el que Jordi ejecuta. El
    ImportError crudo llegaba al modelo como "Error ejecutando
    'leer_documento': No module named 'pypdf'" y el modelo, en vez de
    decir que la herramienta habia reventado, se INVENTO que el usuario no
    habia adjuntado nada - le echo la culpa a Jordi de un fallo del
    servidor.

    Es la misma leccion que la alucinacion de fecha de NASA APOD: cuando el
    modelo puede confundir un fallo con otra cosa, no basta con que el dato
    sea correcto, hay que hacer el fallo VISIBLE e inconfundible.

    Importa de cara al hosting (decision todavia abierta): el dia que el
    bot se despliegue en un VPS y falte una dependencia, esto es lo que
    decidira si el mensaje es util o una mentira."""
    import builtins

    real_import = builtins.__import__

    def sin_pypdf(nombre, *args, **kwargs):
        if nombre.startswith("pypdf"):
            raise ImportError("No module named 'pypdf'")
        return real_import(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_pypdf)

    from src.documentos import _extraer_texto_pdf

    with pytest.raises(DocumentoNoValido) as fallo:
        _extraer_texto_pdf(b"lo que sea")

    mensaje = str(fallo.value)
    # Dice que el problema es de INSTALACION, no del fichero ni del usuario.
    assert "instalada" in mensaje or "instalar" in mensaje
    # Y le prohibe explicitamente al modelo culpar al usuario, que es
    # exactamente lo que hizo el 31/07.
    assert "no es culpa" in mensaje.lower()
    # No filtra el volcado interno de Python (misma politica que
    # test_mensajes_de_error_no_filtran_detalles_internos en test_tools.py).
    assert "No module named" not in mensaje


def test_si_falta_la_libreria_de_word_el_mensaje_es_NUESTRO(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def sin_docx(nombre, *args, **kwargs):
        if nombre == "docx" or nombre.startswith("docx."):
            raise ImportError("No module named 'docx'")
        return real_import(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_docx)

    from src.documentos import _extraer_texto_docx

    with pytest.raises(DocumentoNoValido) as fallo:
        _extraer_texto_docx(b"lo que sea")

    assert "no es culpa" in str(fallo.value).lower()
    assert "No module named" not in str(fallo.value)


def test_un_docx_sin_texto_da_cadena_vacia():
    """No es un error - lo distingue tools.py, que es quien decide el
    mensaje ('no tiene texto que pueda leer')."""
    adjunto = validar_adjunto(_docx_con_texto(), "vacio.docx")
    assert extraer_texto(adjunto) == ""


# --- El ContextVar (como leer_documento sabe "cual" documento) -----------


def test_sin_fijar_nada_documento_actual_es_None():
    assert documento_actual() is None


def test_fijar_y_restaurar_documento_actual():
    adjunto = validar_adjunto(_pdf_con_texto("x"), "x.pdf")

    token = fijar_documento_actual(adjunto)
    try:
        assert documento_actual() is adjunto
    finally:
        restaurar_documento_actual(token)

    assert documento_actual() is None
