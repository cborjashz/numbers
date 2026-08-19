from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime
import psycopg2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io
import os
from datetime import timezone, timedelta
import json
import random
import secrets  # Para generar tokens seguros

# ===== CONFIGURACIÓN =====
DATABASE_URL = os.getenv("DATABASE_URL")

app = FastAPI(title="Sistema de Lotería - PDV")
templates = Jinja2Templates(directory="templates")

# ===== MODELOS =====
class LoginRequest(BaseModel):
    usuario: str
    password: str

class VentaRequest(BaseModel):
    nombre_vendedor: str
    cliente: str
    items: list[dict]  # Lista de objetos {"numero": "05", "precio": 10.0}
    cierre_elegido: str | None = None

# ===== LÓGICA DE CIERRES =====
def calcular_cierre(hora_venta: int) -> str:
    if hora_venta < 11:
        return "Cierre 1 (11am)"
    elif 11 <= hora_venta < 15:
        return "Cierre 2 (3pm)"
    elif 15 <= hora_venta < 21:
        return "Cierre 3 (9pm)"
    else:
        return "Cierre 1 (11am - Día siguiente)"

def generar_recibo_pdf(
    num_recibo: int, 
    fecha_emision: str, 
    cliente: str, 
    agrupado: dict[float, list[str]],  # {precio: [numeros]}
    total: float, 
    cierre: str, 
    vendedor: str
) -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Colores base
    color_oro = (0.85, 0.65, 0.13)      # Un dorado más sobrio y elegante
    color_oscuro = (0.15, 0.15, 0.15)    # Negro suave para texto
    color_gris = (0.4, 0.4, 0.4)        # Gris para etiquetas secundarias

    # Margen izquierdo y ancho útil
    margin_x = 50
    content_width = width - (margin_x * 2)

    # === ENCABEZADO ===
    # Marco superior decorativo
    c.setStrokeColor(color_oro)
    c.setLineWidth(3)
    c.line(margin_x, height - 40, width - margin_x, height - 40)

    # Título principal
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(color_oscuro)
    c.drawCentredString(width / 2, height - 70, "COMPROBANTE DE COMPRA")

    # Subtítulo/Estado
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(color_oro)
    c.drawCentredString(width / 2, height - 88, f"SISTEMA DE LOTERÍA • {cierre.upper()}")

    # Separador
    c.setStrokeColor((0.8, 0.8, 0.8))
    c.setLineWidth(0.5)
    c.line(margin_x, height - 100, width - margin_x, height - 100)

    # === DATOS GENERALES (Estructurado en 2 columnas) ===
    y_meta = height - 125
    line_height = 18

    # Columna 1 (Cliente y Vendedor)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(color_gris)
    c.drawString(margin_x, y_meta, "CLIENTE:")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(color_oscuro)
    c.drawString(margin_x + 65, y_meta, cliente.title())

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(color_gris)
    c.drawString(margin_x, y_meta - line_height, "VENDEDOR:")
    c.setFont("Helvetica", 11)
    c.setFillColor(color_oscuro)
    c.drawString(margin_x + 65, y_meta - line_height, vendedor)

    # Columna 2 (Recibo y Fecha)
    col2_x = width / 2 + 40
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(color_gris)
    c.drawString(col2_x, y_meta, "RECIBO N°:")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(color_oscuro)
    c.drawString(col2_x + 75, y_meta, str(num_recibo))

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(color_gris)
    c.drawString(col2_x, y_meta - line_height, "FECHA:")
    c.setFont("Helvetica", 11)
    c.setFillColor(color_oscuro)
    c.drawString(col2_x + 75, y_meta - line_height, fecha_emision)

    # Separador para detalle
    y_line = y_meta - (line_height * 2) - 10
    c.setStrokeColor(color_oro)
    c.setLineWidth(1)
    c.line(margin_x, y_line, width - margin_x, y_line)

    # Encabezado de la tabla de ítems
    y_table = y_line - 20
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(color_oscuro)
    c.drawString(margin_x, y_table, "DETALLE DE JUGADAS")
    c.drawRightString(width - margin_x, y_table, "SUBTOTAL")

    c.setStrokeColor((0.85, 0.85, 0.85))
    c.setLineWidth(0.5)
    c.line(margin_x, y_table - 6, width - margin_x, y_table - 6)

    # === NÚMEROS JUGADOS (AGRUPADOS POR PRECIO) ===
    y = y_table - 25
    precios_ordenados = sorted(agrupado.keys(), reverse=True)
    total_numeros_jugados = 0

    for precio in precios_ordenados:
        numeros = agrupado[precio]
        cant_numeros = len(numeros)
        total_numeros_jugados += cant_numeros
        subtotal_grupo = precio * cant_numeros
        texto_numeros = ", ".join(numeros)

        # Etiqueta de precio y cantidad
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(color_oscuro)
        etiqueta = f"{cant_numeros} num. a L. {precio:.2f} c/u:"
        c.drawString(margin_x, y, etiqueta)

        # Monto acumulado por grupo
        c.setFont("Helvetica", 10)
        c.drawRightString(width - margin_x, y, f"L. {subtotal_grupo:.2f}")

        # Listado de números jugados (indentado hacia abajo)
        y -= 14
        c.setFont("Helvetica", 10)
        c.setFillColor((0.25, 0.25, 0.25))
        c.drawString(margin_x + 15, y, texto_numeros)

        y -= 22  # Espacio entre grupos

    # === RESUMEN Y PIE DE PÁGINA ===
    c.setStrokeColor(color_oro)
    c.setLineWidth(1)
    c.line(margin_x, y + 10, width - margin_x, y + 10)

    y_totales = y - 15

    # Cantidad total de números
    c.setFont("Helvetica", 11)
    c.setFillColor(color_gris)
    c.drawString(margin_x, y_totales, f"Cantidad total de números: {total_numeros_jugados}")

    # Cuadro destacado para el TOTAL
    c.setFillColor(color_oscuro)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_x, y_totales - 25, "TOTAL A PAGAR:")

    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(color_oro)
    c.drawRightString(width - margin_x, y_totales - 25, f"L. {total:.2f}")

    # Línea inferior final
    c.setStrokeColor((0.8, 0.8, 0.8))
    c.setLineWidth(0.5)
    c.line(margin_x, y_totales - 40, width - margin_x, y_totales - 40)

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(color_gris)
    c.drawCentredString(width / 2, y_totales - 55, "¡Gracias por su compra y buena suerte!")

    c.save()
    buffer.seek(0)
    return buffer

# ===== RUTAS WEB =====
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# ===== FUNCIÓN AUXILIAR PARA VALIDAR TOKEN =====
async def validar_token(token: str):
    """
    Valida que el token exista, esté activo, no haya expirado,
    y que el usuario esté activo y no haya expirado.
    Retorna (id_usuario, nombre_usuario) si es válido.
    """
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute("SET TIMEZONE = 'America/Managua'")
    try:
        cursor.execute("""
            SELECT 
                s.id_usuario,
                u.nombre_usuario,
                s.fecha_expiracion,
                u.fecha_expiracion AS usuario_expiracion,
                u.activo AS usuario_activo
            FROM sesiones_activas s
            JOIN usuarios u ON s.id_usuario = u.id_usuario
            WHERE s.token = %s AND s.activo = TRUE
        """, (token,))
        resultado = cursor.fetchone()
        conn.close()

        if not resultado:
            raise HTTPException(status_code=401, detail="Token inválido o sesión cerrada")

        id_usuario = resultado[0]
        nombre_usuario = resultado[1]
        fecha_expiracion_token = resultado[2]
        fecha_expiracion_usuario = resultado[3]
        usuario_activo = resultado[4]

        ahora = datetime.now(timezone(timedelta(hours=-6)))

        # Verificar expiración del token
        if fecha_expiracion_token < ahora:
            # Opcional: podríamos invalidar la sesión aquí
            raise HTTPException(status_code=401, detail="Token expirado")

        # Verificar que el usuario esté activo
        if not usuario_activo:
            raise HTTPException(status_code=401, detail="Usuario desactivado")

        # Verificar que el usuario no haya expirado
        if fecha_expiracion_usuario and fecha_expiracion_usuario < ahora:
            raise HTTPException(status_code=401, detail="Licencia del usuario expirada")

        return id_usuario, nombre_usuario

    except Exception as e:
        conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Error validando token")

# ===== API =====
@app.post("/api/login")
async def login(data: LoginRequest):
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Validar credenciales y obtener datos del usuario (INCLUIMOS id_mayorista)
        cursor.execute("""
            SELECT id_usuario, nombre_usuario, limite_venta, fecha_expiracion, max_sesiones, activo, id_mayorista
            FROM usuarios 
            WHERE nombre_usuario = %s AND password_hash = %s
        """, (data.usuario, data.password))
        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

        id_usuario = resultado[0]
        nombre_usuario = resultado[1]
        limite_venta = resultado[2]
        fecha_expiracion = resultado[3]
        max_sesiones = resultado[4]
        activo = resultado[5]
        id_mayorista = resultado[6]

        # 2. Verificar que el usuario esté activo
        if not activo:
            raise HTTPException(status_code=401, detail="Usuario desactivado")

        # 3. Verificar que la licencia no haya expirado
        ahora = datetime.now(timezone(timedelta(hours=-6)))
        if fecha_expiracion and fecha_expiracion < ahora:
            raise HTTPException(status_code=401, detail="Licencia del usuario expirada")

        # 4. Contar sesiones activas y verificar límite
        cursor.execute("""
            SELECT COUNT(*) FROM sesiones_activas 
            WHERE id_usuario = %s AND activo = TRUE
        """, (id_usuario,))
        sesiones_activas = cursor.fetchone()[0]
        if sesiones_activas >= max_sesiones:
            raise HTTPException(
                status_code=403, 
                detail=f"Límite de sesiones alcanzado (máximo {max_sesiones}). Cierre otra sesión o contacte al administrador."
            )

        # 5. Generar token único
        token = secrets.token_hex(32)

        # 6. Definir expiración del token
        expiracion_token = ahora + timedelta(hours=8)

        # 7. Insertar la nueva sesión
        cursor.execute("""
            INSERT INTO sesiones_activas (id_usuario, token, fecha_expiracion)
            VALUES (%s, %s, %s)
        """, (id_usuario, token, expiracion_token))

        conn.commit()
        conn.close()

        # 8. Devolver token, datos y AHORA TAMBIÉN id_mayorista
        return {
            "usuario": nombre_usuario,
            "limite_venta": limite_venta,
            "token": token,
            "expiracion": expiracion_token.isoformat(),
            "id_mayorista": id_mayorista  # <--- NUEVO CAMPO DEVUELTO
        }

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/opciones")
async def get_opciones(authorization: str = Header(None)):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    _, _ = await validar_token(token)  # Solo validamos, no necesitamos el usuario aquí

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute("SET TIMEZONE = 'America/Managua'")
    cursor.execute("SELECT nombre_opcion, numeros_incluidos FROM opciones_rapidas ORDER BY id_opcion")
    filas = cursor.fetchall()
    conn.close()
    return [{"nombre_opcion": f[0], "numeros_incluidos": f[1]} for f in filas]

@app.post("/api/vender")
async def vender(venta: VentaRequest, authorization: str = Header(None)):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, nombre_vendedor = await validar_token(token)

    venta.nombre_vendedor = nombre_vendedor

    conn = None
    try:
        # === VALIDACIÓN DE PRECIO NEGATIVO ===
        # === VALIDACIÓN DE PRECIO NEGATIVO Y CLIENTE ===
        for item in venta.items:
            if item["precio"] <= 0:
                raise HTTPException(status_code=400, detail="Todos los precios deben ser mayores a 0")
        
        # Si el cliente llega vacío, lo forzamos a "Cliente Final"
        if not venta.cliente or venta.cliente.strip() == "":
            venta.cliente = "Cliente Final"

        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.autocommit = False
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        # 1. Determinar el cierre
        if venta.cierre_elegido:
            cierres_validos = ["Cierre 1 (11am)", "Cierre 2 (3pm)", "Cierre 3 (9pm)"]
            if venta.cierre_elegido not in cierres_validos:
                raise HTTPException(status_code=400, detail="Cierre elegido no válido")
            hora_actual = ahora.hour
            if venta.cierre_elegido == "Cierre 1 (11am)" and hora_actual >= 11:
                raise HTTPException(status_code=400, detail="El Cierre 1 (11am) ya pasó.")
            elif venta.cierre_elegido == "Cierre 2 (3pm)" and hora_actual >= 15:
                raise HTTPException(status_code=400, detail="El Cierre 2 (3pm) ya pasó.")
            elif venta.cierre_elegido == "Cierre 3 (9pm)" and hora_actual >= 21:
                raise HTTPException(status_code=400, detail="El Cierre 3 (9pm) ya pasó.")
            cierre = venta.cierre_elegido
        else:
            cierre = calcular_cierre(ahora.hour)

        # 2. Agrupar los items por precio
        grupos = {}
        for item in venta.items:
            precio = item["precio"]
            numero = item["numero"]
            if precio not in grupos:
                grupos[precio] = []
            grupos[precio].append(numero)

        # 3. Construir el detalle JSON (fuente de verdad)
        detalle_venta = []
        for precio, numeros in grupos.items():
            detalle_venta.append({
                "precio": precio,
                "numeros": numeros
            })
        detalle_json = json.dumps(detalle_venta)

        # 4. Calcular total
        total = sum(item["precio"] for item in venta.items)

        # 5. Obtener límite de venta y mayorista
        cursor.execute(
            "SELECT limite_venta, id_mayorista FROM usuarios WHERE id_usuario = %s",
            (id_usuario,)
        )
        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        limite_venta = resultado[0]
        id_mayorista = resultado[1]

        # Validar límite por número (usamos el precio más alto de la venta)
        precio_maximo = max(item["precio"] for item in venta.items)
        if limite_venta is not None and precio_maximo > limite_venta:
            raise HTTPException(
                status_code=400,
                detail=f"El precio máximo (L. {precio_maximo}) supera el límite permitido de L. {limite_venta}"
            )

        # 6. Generar número de recibo
        num_recibo = int(f"{(int(ahora.timestamp() * 1000) % 10000000)}{random.randint(100, 999)}")

        # 7. Preparar datos para la BD
        # - numero_jugado: lista plana de números (para cumplir NOT NULL)
        # - precio_unitario: valor del primer precio (NO se usa, solo para NOT NULL)
        # - detalle_venta: detalle agrupado por precio (fuente de verdad)
        numeros_planos = [item["numero"] for item in venta.items]
        numeros_json = json.dumps(numeros_planos)
        primer_precio = venta.items[0]["precio"] if venta.items else 0

        # 8. Guardar en la BD
        sql_insert = """
            INSERT INTO ventas (
                num_recibo, id_usuario, cliente, fecha_hora,
                cierre_asignado, id_mayorista, total,
                numero_jugado, precio_unitario, detalle_venta
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql_insert, (
            num_recibo,
            id_usuario,
            venta.cliente,
            ahora,
            cierre,
            id_mayorista,
            total,
            numeros_json,        # <--- LISTA PLANA DE NÚMEROS
            primer_precio,       # <--- PRIMER PRECIO (solo para NOT NULL)
            detalle_json         # <--- DETALLE AGRUPADO (fuente de verdad)
        ))

        conn.commit()

        # 8. Generar PDF usando el diccionario agrupado
        fecha_str = ahora.strftime("%d-%m-%Y %H:%M:%S")
        pdf_buffer = generar_recibo_pdf(
            num_recibo=num_recibo,
            fecha_emision=fecha_str,
            cliente=venta.cliente,
            agrupado=grupos,
            total=total,
            cierre=cierre,
            vendedor=venta.nombre_vendedor
        )

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=recibo_{num_recibo}.pdf"}
        )

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/recibo/{num_recibo}")
async def obtener_recibo(num_recibo: int, authorization: str = Header(None)):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    _, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        cursor.execute("""
            SELECT detalle_venta
            FROM ventas
            WHERE num_recibo = %s
        """, (num_recibo,))

        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Recibo no encontrado")

        detalle_venta_json = resultado[0]
        if not detalle_venta_json:
            raise HTTPException(status_code=400, detail="El recibo no tiene detalle de precios")

        # Verificar si psycopg2 ya parseó el JSONB a list/dict o si viene como str
        if isinstance(detalle_venta_json, str):
            grupos = json.loads(detalle_venta_json)
        else:
            grupos = detalle_venta_json

        conn.close()

        # Formato para el frontend: lista de objetos {numero, precio} para llenar la tabla
        items = []
        for grupo in grupos:
            precio = grupo["precio"]
            for numero in grupo["numeros"]:
                items.append({"numero": numero, "precio": precio})

        return {
            "items": items
        }

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/reimprimir/{num_recibo}")
async def reimprimir_recibo(num_recibo: int, authorization: str = Header(None)):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # Consultar la venta y los datos del vendedor
        cursor.execute("""
            SELECT 
                v.fecha_hora,
                v.cliente,
                v.detalle_venta,
                v.total,
                v.cierre_asignado,
                u.nombre_usuario
            FROM ventas v
            JOIN usuarios u ON v.id_usuario = u.id_usuario
            WHERE v.num_recibo = %s
        """, (num_recibo,))

        resultado = cursor.fetchone()
        conn.close()

        if not resultado:
            raise HTTPException(status_code=404, detail="Recibo no encontrado")

        fecha_hora, cliente, detalle_venta_json, total, cierre, vendedor = resultado

        if not detalle_venta_json:
            raise HTTPException(status_code=400, detail="El recibo no tiene detalle de precios registrado")

        # Parsear detalle_venta si viene como string o list desde psycopg2
        if isinstance(detalle_venta_json, str):
            grupos_list = json.loads(detalle_venta_json)
        else:
            grupos_list = detalle_venta_json

        # Reconstruir la estructura {precio: [numeros]} que necesita generar_recibo_pdf
        agrupado = {}
        for grupo in grupos_list:
            precio = float(grupo["precio"])
            numeros = grupo["numeros"]
            agrupado[precio] = numeros

        # Formatear fecha para el PDF
        fecha_str = fecha_hora.strftime("%d-%m-%Y %H:%M:%S")

        # Generar el PDF del recibo
        pdf_buffer = generar_recibo_pdf(
            num_recibo=num_recibo,
            fecha_emision=fecha_str,
            cliente=cliente,
            agrupado=agrupado,
            total=float(total),
            cierre=cierre,
            vendedor=vendedor
        )

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=recibo_{num_recibo}.pdf"}
        )

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/logout")
async def logout(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    
    token = authorization.replace("Bearer ", "")
    
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")
        
        # Marcar la sesión como inactiva
        cursor.execute("""
            UPDATE sesiones_activas
            SET activo = FALSE
            WHERE token = %s AND activo = TRUE
        """, (token,))
        
        # Si no se actualizó ninguna fila, el token no existía o ya estaba inactivo
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Sesión no encontrada o ya cerrada")
        
        conn.commit()
        conn.close()
        
        return {"detail": "Sesión cerrada exitosamente"}
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tablero-estado")
async def tablero_estado(
    authorization: str = Header(None),
    fecha: str = None,
    cierre: str = None
):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Obtener el id_mayorista del usuario logueado
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            return {"numeros": {}, "total": 0.0}

        id_mayorista = resultado[0]

        # 2. Determinar fecha y cierre (usando zona Managua)
        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        if fecha:
            fecha_consulta = datetime.strptime(fecha, "%Y-%m-%d").date()
        else:
            fecha_consulta = ahora.date()

        if cierre:
            cierre_consulta = cierre
        else:
            cierre_consulta = calcular_cierre(ahora.hour)

        # 3. Consulta SQL usando los filtros dinámicos
        cursor.execute("""
            SELECT 
                num_individual AS numero,
                SUM((detalle->>'precio')::numeric) AS monto_total
            FROM ventas v,
            LATERAL jsonb_array_elements(v.detalle_venta) AS detalle,
            LATERAL jsonb_array_elements_text(detalle->'numeros') AS num_individual
            WHERE v.cierre_asignado = %s
              AND v.id_mayorista = %s
              AND v.id_usuario = %s
              AND DATE(v.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Managua') = %s
            GROUP BY num_individual
        """, (cierre_consulta, id_mayorista, id_usuario, fecha_consulta))

        filas = cursor.fetchall()
        conn.close()

        numeros = {}
        total_general = 0.0
        for num, monto in filas:
            numeros[num] = float(monto)
            total_general += float(monto)

        return {
            "numeros": numeros,
            "total": total_general
        }

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reporte-ventas-cliente")
async def reporte_ventas_cliente(
    authorization: str = Header(None),
    fecha_inicio: str = None,
    fecha_fin: str = None,
    cliente_filtro: str = None,
    numero_filtro: str = None
):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Obtener id_mayorista del usuario
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            return []

        id_mayorista = resultado[0]

        # 2. Determinar rango de fechas
        managua_tz = timezone(timedelta(hours=-6))
        hoy = datetime.now(managua_tz).date()

        if fecha_inicio:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        else:
            fecha_inicio_dt = hoy

        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
        else:
            fecha_fin_dt = hoy

        # 3. Construir la consulta SQL base
        sql = """
            SELECT 
                v.num_recibo,
                v.cliente,
                v.cierre_asignado,
                SUM(v.cantidad) AS total_numeros,
                SUM(v.total) AS total_monto
            FROM ventas v
            WHERE v.id_mayorista = %s
              AND v.id_usuario = %s
              AND DATE(v.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Managua') BETWEEN %s AND %s
        """
        params = [id_mayorista, id_usuario, fecha_inicio_dt, fecha_fin_dt]

        # 4. Filtro por cliente (ILIKE)
        if cliente_filtro and cliente_filtro.strip() != "":
            sql += " AND v.cliente ILIKE %s"
            params.append(f"%{cliente_filtro.strip()}%")

        # 5. Filtro por número (búsqueda dentro del JSONB detalle_venta)
        if numero_filtro and numero_filtro.strip() != "":
            sql += """
                AND EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(v.detalle_venta) AS detalle
                    CROSS JOIN jsonb_array_elements_text(detalle->'numeros') AS num_individual
                    WHERE num_individual = %s
                )
            """
            params.append(numero_filtro.strip())

        # 6. Completar la consulta
        sql += """
            GROUP BY v.num_recibo, v.cliente, v.cierre_asignado
            ORDER BY v.cliente, v.cierre_asignado
        """

        cursor.execute(sql, params)
        filas = cursor.fetchall()
        conn.close()

        # 7. Formatear respuesta
        resultado = []
        for num_recibo, cliente, cierre, total_numeros, total_monto in filas:
            resultado.append({
                "num_recibo": num_recibo,
                "cliente": cliente,
                "cierre": cierre,
                "total_numeros": int(total_numeros),
                "total_monto": float(total_monto)
            })

        return resultado

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reporte-ventas-cliente-pdf")
async def reporte_ventas_cliente_pdf(
    authorization: str = Header(None),
    fecha_inicio: str = None,
    fecha_fin: str = None
):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Obtener id_mayorista del usuario
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Usuario sin mayorista")

        id_mayorista = resultado[0]

        # 2. Determinar rango de fechas
        managua_tz = timezone(timedelta(hours=-6))
        hoy = datetime.now(managua_tz).date()

        if fecha_inicio:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        else:
            fecha_inicio_dt = hoy

        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
        else:
            fecha_fin_dt = hoy

        # 3. Consulta SQL: Agrupar por cliente y cierre
        cursor.execute("""
            SELECT 
                cliente,
                cierre_asignado,
                SUM(cantidad) AS total_numeros,
                SUM(total) AS total_monto
            FROM ventas
            WHERE id_mayorista = %s
              AND id_usuario = %s
              AND DATE(fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Managua') BETWEEN %s AND %s
            GROUP BY cliente, cierre_asignado
            ORDER BY cliente, cierre_asignado
        """, (id_mayorista, id_usuario, fecha_inicio_dt, fecha_fin_dt))

        filas = cursor.fetchall()
        conn.close()

        # 4. Generar PDF
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Título
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 50, "Reporte de Ventas por Cliente")

        # Fechas
        c.setFont("Helvetica", 12)
        c.drawString(50, height - 80, f"Desde: {fecha_inicio_dt.strftime('%d/%m/%Y')}")
        c.drawString(250, height - 80, f"Hasta: {fecha_fin_dt.strftime('%d/%m/%Y')}")

        # Encabezados de tabla
        y = height - 120
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Cliente")
        c.drawString(200, y, "Cierre")
        c.drawString(350, y, "Números")
        c.drawString(450, y, "Total L.")
        c.line(50, y - 5, 550, y - 5)

        # Datos
        y -= 25
        c.setFont("Helvetica", 11)
        total_general = 0

        for cliente, cierre, total_numeros, total_monto in filas:
            if y < 50:  # Salto de página si no hay espacio
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 11)

            c.drawString(50, y, cliente[:30])  # Truncar si es muy largo
            c.drawString(200, y, cierre)
            c.drawString(350, y, str(total_numeros))
            c.drawString(450, y, f"{total_monto:.2f}")
            total_general += total_monto
            y -= 20

        # Total general
        y -= 10
        c.setFont("Helvetica-Bold", 12)
        c.line(50, y - 5, 550, y - 5)
        c.drawString(350, y, "TOTAL GENERAL")
        c.drawString(450, y, f"{total_general:.2f}")

        c.save()
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=reporte_ventas_{fecha_inicio_dt.strftime('%Y%m%d')}_a_{fecha_fin_dt.strftime('%Y%m%d')}.pdf"}
        )

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reporte-cierre")
async def reporte_cierre(
    authorization: str = Header(None),
    fecha: str = None,
    cierre: str = None
):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, nombre_vendedor = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Obtener id_mayorista del usuario (aunque no se use para filtrar, lo mantenemos por consistencia)
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            return {"vendedor": nombre_vendedor, "cierre": cierre, "numeros": {}, "total": 0.0}

        # 2. Determinar fecha y cierre
        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        if fecha:
            fecha_consulta = datetime.strptime(fecha, "%Y-%m-%d").date()
        else:
            fecha_consulta = ahora.date()

        if not cierre:
            raise HTTPException(status_code=400, detail="Debe seleccionar un cierre válido")

        # 3. Consulta SQL: Agrupar por número individual, sumando el precio_unitario
        cursor.execute("""
            SELECT 
                num_individual AS numero,
                SUM((detalle->>'precio')::numeric) AS monto_total
            FROM ventas v,
            LATERAL jsonb_array_elements(v.detalle_venta) AS detalle,
            LATERAL jsonb_array_elements_text(detalle->'numeros') AS num_individual
            WHERE v.cierre_asignado = %s
              AND v.id_usuario = %s
              AND DATE(v.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Managua') = %s
            GROUP BY num_individual
            ORDER BY num_individual ASC
        """, (cierre, id_usuario, fecha_consulta))

        filas = cursor.fetchall()
        conn.close()

        # 4. Construir el diccionario de resultados
        numeros = {}
        total_general = 0.0
        for num, monto in filas:
            numeros[num] = float(monto)
            total_general += float(monto)

        # 5. Asegurar que todos los números del 00 al 99 estén presentes (con 0 si no hay ventas)
        for i in range(100):
            num_str = f"{i:02d}"
            if num_str not in numeros:
                numeros[num_str] = 0.0

        # 6. Ordenar los números de forma natural (00, 01, 02, ...)
        numeros_ordenados = {k: numeros[k] for k in sorted(numeros.keys())}

        return {
            "vendedor": nombre_vendedor,
            "cierre": cierre,
            "fecha": fecha_consulta.strftime("%d-%m-%Y"),
            "numeros": numeros_ordenados,
            "total": total_general
        }

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reporte-cierre-pdf")
async def reporte_cierre_pdf(
    authorization: str = Header(None),
    fecha: str = None,
    cierre: str = None
):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, nombre_vendedor = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SET TIMEZONE = 'America/Managua'")

        # 1. Validar mayorista y obtener datos
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Usuario sin mayorista")

        # 2. Determinar fecha y cierre
        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        if fecha:
            fecha_consulta = datetime.strptime(fecha, "%Y-%m-%d").date()
        else:
            fecha_consulta = ahora.date()

        if not cierre:
            conn.close()
            raise HTTPException(status_code=400, detail="Debe seleccionar un cierre válido")

        # 3. Consulta SQL para obtener los datos del cierre
        cursor.execute("""
            SELECT 
                num_individual AS numero,
                SUM((detalle->>'precio')::numeric) AS monto_total
            FROM ventas v,
            LATERAL jsonb_array_elements(v.detalle_venta) AS detalle,
            LATERAL jsonb_array_elements_text(detalle->'numeros') AS num_individual
            WHERE v.cierre_asignado = %s
              AND v.id_usuario = %s
              AND DATE(v.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Managua') = %s
            GROUP BY num_individual
            ORDER BY num_individual ASC
        """, (cierre, id_usuario, fecha_consulta))

        filas = cursor.fetchall()
        conn.close()

        # 4. Construir diccionario de números y calcular total
        numeros = {}
        total_general = 0.0
        for num, monto in filas:
            numeros[num] = float(monto)
            total_general += float(monto)

        # 5. Generar PDF
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Colores
        color_oro = (0.85, 0.65, 0.13)
        color_oscuro = (0.15, 0.15, 0.15)
        color_gris = (0.4, 0.4, 0.4)

        # === ENCABEZADO ===
        c.setStrokeColor(color_oro)
        c.setLineWidth(2)
        c.line(50, height - 50, width - 50, height - 50)

        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(color_oscuro)
        c.drawCentredString(width / 2, height - 80, "REPORTE DE CIERRE")

        c.setFont("Helvetica", 10)
        c.setFillColor(color_gris)
        c.drawCentredString(width / 2, height - 100, f"Generado el {datetime.now(managua_tz).strftime('%d-%m-%Y %H:%M:%S')}")

        # === DATOS GENERALES ===
        y = height - 140
        line_height = 20
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(color_oscuro)
        c.drawString(50, y, f"Vendedor: {nombre_vendedor}")
        c.drawString(250, y, f"Cierre: {cierre}")
        c.drawString(450, y, f"Fecha: {fecha_consulta.strftime('%d-%m-%Y')}")

        # === DETALLE POR NÚMERO ===
        y -= 40
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(color_oscuro)
        c.drawString(50, y, "Número")
        c.drawRightString(width - 50, y, "Monto")

        c.setStrokeColor((0.8, 0.8, 0.8))
        c.setLineWidth(0.5)
        c.line(50, y - 5, width - 50, y - 5)

        y -= 20
        c.setFont("Helvetica", 10)
        for num, monto in sorted(numeros.items()):
            if y < 50:  # Salto de página
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 10)
            
            c.drawString(50, y, num)
            if monto > 0:
                c.drawRightString(width - 50, y, f"L. {monto:.2f}")
            y -= 15

        # === TOTAL GENERAL ===
        y -= 15
        c.setStrokeColor(color_oro)
        c.setLineWidth(1)
        c.line(50, y - 5, width - 50, y - 5)

        y -= 15
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(color_oscuro)
        c.drawString(50, y, "TOTAL DEL CIERRE:")
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(color_oro)
        c.drawRightString(width - 50, y, f"L. {total_general:.2f}")

        c.save()
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=reporte_cierre_{fecha_consulta.strftime('%Y%m%d')}_{cierre.replace(' ', '_')}.pdf"}
        )

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
