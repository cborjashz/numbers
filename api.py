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
    numeros: list[str]
    precio_unitario: float

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

def generar_recibo_pdf(num_recibo: int, fecha_emision: str, cliente: str, numeros: list, precio_unitario: float, total: float, cierre: str, vendedor: str) -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # === ENCABEZADO ===
    c.setStrokeColor((1, 0.84, 0))  # Amarillo
    c.setLineWidth(2)
    c.line(50, height - 50, width - 50, height - 50)

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor((0, 0, 0))
    c.drawCentredString(width / 2, height - 80, "Comprobante de Pago")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 120, "Cliente:")
    c.setFont("Helvetica", 12)
    c.drawString(130, height - 120, cliente.title())

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 140, "Fecha de Emisión:")
    c.setFont("Helvetica", 12)
    c.drawString(200, height - 140, fecha_emision)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 160, "Número de Recibo:")
    c.setFont("Helvetica", 12)
    c.drawString(200, height - 160, str(num_recibo))

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 180, "Vendedor:")
    c.setFont("Helvetica", 12)
    c.drawString(150, height - 180, vendedor)

    c.setStrokeColor((1, 0.84, 0))
    c.setLineWidth(1)
    c.line(50, height - 200, width - 50, height - 200)

    # === NÚMEROS JUGADOS ===
    c.setFont("Helvetica-Bold", 20)
    filas = [numeros[i:i+6] for i in range(0, len(numeros), 6)]
    y_pos_numeros = height - 250
    for fila in filas:
        texto_fila = ", ".join(fila)
        c.drawCentredString(width / 2, y_pos_numeros, texto_fila)
        y_pos_numeros -= 35

    # === CIERRE Y PIE ===
    y_pos_cierre = y_pos_numeros + 15
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y_pos_cierre, cierre)

    c.setFont("Helvetica", 10)
    c.drawRightString(width - 50, y_pos_cierre, fecha_emision)
    c.drawRightString(width - 50, y_pos_cierre - 20, vendedor)

    c.setStrokeColor((1, 0.84, 0))
    c.setLineWidth(1)
    c.line(50, y_pos_cierre + 20, width - 50, y_pos_cierre + 20)

    y_pos_total = y_pos_cierre + 40
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, y_pos_total, "Total L.")
    c.setFont("Helvetica-Bold", 28)
    c.drawRightString(width - 50, y_pos_total, f"{total:.2f}")

    c.setFont("Helvetica", 12)
    c.drawString(50, y_pos_total + 25, f"Cantidad: {len(numeros)}")
    c.drawRightString(width - 50, y_pos_total + 25, f"Precio: L. {precio_unitario:.2f}")

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

    # (Opcional: podrías usar el nombre_vendedor del token en lugar del que viene en el body)
    # Forzamos a que el vendedor sea el del token para seguridad
    venta.nombre_vendedor = nombre_vendedor

    conn = None
    try:
        # === VALIDACIÓN DE PRECIO NEGATIVO ===
        if venta.precio_unitario <= 0:
            raise HTTPException(status_code=400, detail="El precio unitario debe ser mayor a 0")

        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.autocommit = False
        cursor = conn.cursor()

        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        cierre = calcular_cierre(ahora.hour)
        total = venta.precio_unitario * len(venta.numeros)

        # 1. Obtener límite de venta Y EL MAYORISTA del usuario
        cursor.execute(
            "SELECT limite_venta, id_mayorista FROM usuarios WHERE id_usuario = %s",
            (id_usuario,)
        )
        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        limite_venta = resultado[0]
        id_mayorista = resultado[1]  # <--- OBTENEMOS EL ID DEL MAYORISTA

        if limite_venta is not None and venta.precio_unitario > limite_venta:
            raise HTTPException(
                status_code=400,
                detail=f"El precio por número (L. {venta.precio_unitario}) supera el límite permitido de L. {limite_venta}"
            )

        # 2. Generar numero de recibo
        num_recibo = int(f"{(int(ahora.timestamp() * 1000) % 10000000)}{random.randint(100, 999)}")

        # 3. Convertir la lista de números a JSONB
        numeros_json = json.dumps(venta.numeros)

        # 4. Insertar UN SOLO registro con el array JSON (AHORA INCLUYENDO id_mayorista)
        sql_insert = """
            INSERT INTO ventas (
                num_recibo, id_usuario, cliente, numero_jugado, 
                precio_unitario, cantidad, total, cierre_asignado, fecha_hora,
                id_mayorista
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql_insert, (
            num_recibo,
            id_usuario,
            venta.cliente,
            numeros_json,
            venta.precio_unitario,
            len(venta.numeros),
            total,
            cierre,
            ahora,
            id_mayorista  # <--- VALOR DEL MAYORISTA
        ))

        conn.commit()

        fecha_str = ahora.strftime("%d-%m-%Y %H:%M:%S")
        pdf_buffer = generar_recibo_pdf(
            num_recibo=num_recibo,
            fecha_emision=fecha_str,
            cliente=venta.cliente,
            numeros=venta.numeros,
            precio_unitario=venta.precio_unitario,
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

        cursor.execute("""
            SELECT cliente, precio_unitario, numero_jugado
            FROM ventas
            WHERE num_recibo = %s
        """, (num_recibo,))

        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Recibo no encontrado")

        cliente = resultado[0]
        precio_unitario = resultado[1]
        numeros_json = resultado[2]

        if isinstance(numeros_json, str):
            numeros = json.loads(numeros_json)
        else:
            numeros = numeros_json

        conn.close()

        return {
            "cliente": cliente,
            "precio_unitario": precio_unitario,
            "numeros": numeros
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
    _, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                v.cliente,
                v.precio_unitario,
                v.numero_jugado,
                v.fecha_hora,
                v.cierre_asignado,
                u.nombre_usuario
            FROM ventas v
            JOIN usuarios u ON v.id_usuario = u.id_usuario
            WHERE v.num_recibo = %s
            LIMIT 1
        """, (num_recibo,))

        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Recibo no encontrado para reimprimir")

        cliente = resultado[0]
        precio_unitario = resultado[1]
        numeros_json = resultado[2]
        fecha_hora = resultado[3]
        cierre = resultado[4]
        nombre_vendedor = resultado[5]

        if isinstance(numeros_json, str):
            numeros = json.loads(numeros_json)
        else:
            numeros = numeros_json

        total = precio_unitario * len(numeros)
        fecha_str = fecha_hora.strftime("%d-%m-%Y %H:%M:%S")

        conn.close()

        pdf_buffer = generar_recibo_pdf(
            num_recibo=num_recibo,
            fecha_emision=fecha_str,
            cliente=cliente,
            numeros=numeros,
            precio_unitario=precio_unitario,
            total=total,
            cierre=cierre,
            vendedor=nombre_vendedor
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
async def tablero_estado(authorization: str = Header(None)):
    # Validar token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.replace("Bearer ", "")
    id_usuario, _ = await validar_token(token)

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        # 1. Obtener el id_mayorista del usuario logueado
        cursor.execute("SELECT id_mayorista FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        resultado = cursor.fetchone()
        if not resultado or resultado[0] is None:
            conn.close()
            return {}  # Si no tiene mayorista, no mostramos nada

        id_mayorista = resultado[0]

        # 2. Obtener la hora actual y calcular el cierre
        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)
        cierre_actual = calcular_cierre(ahora.hour)

        # 3. Consulta SQL: Sumar los totales por número, solo del cierre actual Y DEL MAYORISTA
        cursor.execute("""
            SELECT 
                num_individual AS numero,
                SUM(v.precio_unitario) AS monto_total
            FROM ventas v,
            LATERAL jsonb_array_elements_text(v.numero_jugado) AS num_individual
            WHERE v.cierre_asignado = %s
              AND v.id_mayorista = %s
            GROUP BY num_individual
        """, (cierre_actual, id_mayorista))

        filas = cursor.fetchall()
        conn.close()

        # 4. Convertir a diccionario: {"00": 350.0, "05": 1200.0, ...}
        resultado = {}
        for num, monto in filas:
            resultado[num] = float(monto)

        return resultado

    except Exception as e:
        if conn:
            conn.close()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))