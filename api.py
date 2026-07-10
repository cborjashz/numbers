from fastapi import FastAPI, HTTPException, Request
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

# ===== API =====
@app.post("/api/login")
async def login(data: LoginRequest):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id_usuario, nombre_usuario, limite_venta FROM usuarios WHERE nombre_usuario = %s AND password_hash = %s",
        (data.usuario, data.password)
    )
    resultado = cursor.fetchone()
    conn.close()
    if not resultado:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return {"usuario": resultado[1], "limite_venta": resultado[2]}

@app.get("/api/opciones")
async def get_opciones():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute("SELECT nombre_opcion, numeros_incluidos FROM opciones_rapidas ORDER BY id_opcion")
    filas = cursor.fetchall()
    conn.close()
    return [{"nombre_opcion": f[0], "numeros_incluidos": f[1]} for f in filas]

@app.post("/api/vender")
async def vender(venta: VentaRequest):
    conn = None
    try:
        # === VALIDACIÓN DE PRECIO NEGATIVO ===
        if venta.precio_unitario <= 0:
            raise HTTPException(status_code=400, detail="El precio unitario debe ser mayor a 0")

        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.autocommit = False  # Inicia la transacción
        cursor = conn.cursor()

        # Zona horaria de Managua
        managua_tz = timezone(timedelta(hours=-6))
        ahora = datetime.now(managua_tz)

        cierre = calcular_cierre(ahora.hour)
        total = venta.precio_unitario * len(venta.numeros)

        # 1. Verificar vendedor y su límite
        cursor.execute(
            "SELECT id_usuario, limite_venta FROM usuarios WHERE nombre_usuario = %s",
            (venta.nombre_vendedor,)
        )
        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Vendedor no encontrado")
        id_usuario = resultado[0]
        limite_venta = resultado[1]

        # Validar límite por número
        if limite_venta is not None and venta.precio_unitario > limite_venta:
            raise HTTPException(
                status_code=400,
                detail=f"El precio por número (L. {venta.precio_unitario}) supera el límite permitido de L. {limite_venta}"
            )

        # 2. Generar numero de recibo de forma aleatoria y unica
        num_recibo = int(f"{(int(ahora.timestamp() * 1000)% 10000000)}{random.randint(100, 999)}")

        # 3. Convertir la lista de números a JSONB
        numeros_json = json.dumps(venta.numeros)

        # 4. Insertar UN SOLO registro con el array JSON
        sql_insert = """
            INSERT INTO ventas (
                num_recibo, id_usuario, cliente, numero_jugado, 
                precio_unitario, cantidad, total, cierre_asignado, fecha_hora
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            ahora
        ))

        conn.commit()  # Confirmar la transacción

        # Generar PDF
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
            conn.rollback()  # Deshacer todo si algo falla
            conn.close()
        # Si ya es una HTTPException, la relanzamos; si no, la envolvemos
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/recibo/{num_recibo}")
async def obtener_recibo(num_recibo: int):
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        # Ahora buscamos UN solo registro
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

        # Convertir JSONB de vuelta a lista de strings
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