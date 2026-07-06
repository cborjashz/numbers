from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime
import psycopg2
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import black, white, yellow
import io
from fastapi.responses import FileResponse
import os

# ===== CONFIGURACIÓN =====
DATABASE_URL = "postgresql://postgres:Cbp43z_121990@db.vfjimjmwnayrairkkdmp.supabase.co:5432/postgres"

app = FastAPI(title="Sistema de Lotería - Web")
templates = Jinja2Templates(directory="templates")

# ===== MODELOS =====
class LoginRequest(BaseModel):
    usuario: str
    password: str

class VentaRequest(BaseModel):
    nombre_vendedor: str
    cliente: str
    numeros: list[str]  # Ahora recibe una lista de números
    precio_unitario: float

# ===== LÓGICA DE CIERRES =====
def calcular_cierre(hora_venta):
    if hora_venta < 11: return "Cierre 1 (11am)"
    elif 11 <= hora_venta < 15: return "Cierre 2 (3pm)"
    elif 15 <= hora_venta < 21: return "Cierre 3 (9pm)"
    else: return "Cierre 1 (11am - Día siguiente)"

def generar_recibo_pdf(num_recibo, fecha_emision, cliente, numero_jugado, precio_unitario, cantidad, total, cierre, vendedor):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # === 1. ENCABEZADO ===
    c.setStrokeColor(yellow)
    c.setLineWidth(2)
    c.line(50, height - 50, width - 50, height - 50)
    
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(black)
    c.drawCentredString(width/2, height - 80, "Comprobante de Pago")
    
    # Información del cliente (Ajuste #3: Primera letra mayúscula)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 120, "Cliente:")
    c.setFont("Helvetica", 12)
    c.drawString(130, height - 120, cliente.title())  # <--- .title() aplicado
    
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
    
    # Línea amarilla separadora del encabezado
    c.setStrokeColor(yellow)
    c.setLineWidth(1)
    c.line(50, height - 200, width - 50, height - 200)
    
    # === 2. NÚMEROS JUGADOS (Formateados en filas) ===
    c.setFont("Helvetica-Bold", 20)
    numeros_lista = numero_jugado.split(", ")
    filas = [numeros_lista[i:i+6] for i in range(0, len(numeros_lista), 6)]
    
    y_pos_numeros = height - 250
    for fila in filas:
        texto_fila = ", ".join(fila)
        c.drawCentredString(width/2, y_pos_numeros, texto_fila)
        y_pos_numeros -= 35  # Espacio entre filas
    
    # === 3. PRECIO Y CANTIDAD (Sin línea punteada, alineados juntos) ===
    # Ajuste #2: Eliminamos la línea punteada y ponemos precio/cantidad en una sola línea limpia
    y_pos_precio = y_pos_numeros + 10
    c.setFont("Helvetica", 12)
    c.drawString(50, y_pos_precio, f"Cantidad: {cantidad}")
    c.drawRightString(width - 50, y_pos_precio, f"Precio: L. {precio_unitario:.2f}")
    
    # === 4. TOTAL ===
    y_pos_total = y_pos_precio + 30
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, y_pos_total, "Total L.")
    c.setFont("Helvetica-Bold", 28)
    c.drawRightString(width - 50, y_pos_total, f"{total:.2f}")
    
    # === 5. LÍNEA AMARILLA SÓLIDA FINAL ===
    y_pos_linea_final = y_pos_total + 20
    c.setDash(1, 0)
    c.setStrokeColor(yellow)
    c.setLineWidth(2)
    c.line(50, y_pos_linea_final, width - 50, y_pos_linea_final)
    
    # === 6. CIERRE Y PIE DE PÁGINA (Ajuste #1: Movido al final) ===
    y_pos_cierre = y_pos_linea_final + 40
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(black)
    c.drawString(50, y_pos_cierre, cierre)
    
    c.setFont("Helvetica", 10)
    c.drawString(50, y_pos_cierre + 30, fecha_emision)
    c.drawRightString(width - 50, y_pos_cierre + 30, vendedor)
    
    # === 7. FINALIZAR ===
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
    cursor.execute("SELECT id_usuario, nombre_usuario, limite_venta FROM usuarios WHERE nombre_usuario = %s AND password_hash = %s", (data.usuario, data.password))
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
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        ahora = datetime.now()
        cierre = calcular_cierre(ahora.hour)
        total = venta.precio_unitario * len(venta.numeros)
        
        # 1. Verificar que el vendedor existe y obtener su límite
        cursor.execute("SELECT id_usuario, limite_venta FROM usuarios WHERE nombre_usuario = %s", (venta.nombre_vendedor,))
        resultado = cursor.fetchone()
        if not resultado:
            raise HTTPException(status_code=404, detail="Vendedor no encontrado")
        id_usuario = resultado[0]
        limite_venta = resultado[1]
        
        # 2. Validar que el PRECIO UNITARIO no supere el límite del vendedor
        # (El límite es por cada número, no por el total de la venta)
        if limite_venta is not None and venta.precio_unitario > limite_venta:
            raise HTTPException(
                status_code=400, 
                detail=f"⚠️ El precio por número (L. {venta.precio_unitario}) supera el límite permitido de L. {limite_venta}. Cada número individual no puede superar ese valor."
            )
        
        # 3. Generar un número de recibo único para toda la venta
        num_recibo = int(ahora.timestamp()) % 10000000
        
        # 4. Insertar TODOS los números en la base de datos (uno por uno)
        ventas_insertadas = 0
        for numero in venta.numeros:
            sql = """
                INSERT INTO ventas (num_recibo, id_usuario, cliente, numero_jugado, precio_unitario, cantidad, total, cierre_asignado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (num_recibo, id_usuario, venta.cliente, numero, venta.precio_unitario, 1, venta.precio_unitario, cierre))
            ventas_insertadas += 1
        
        conn.commit()
        conn.close()

        fecha_str = ahora.strftime("%d-%m-%Y %H:%M:%S")
        pdf_buffer = generar_recibo_pdf(
            num_recibo=num_recibo,
            fecha_emision=fecha_str,
            cliente=venta.cliente,
            numero_jugado=", ".join(venta.numeros),  # Mostrar todos los números
            precio_unitario=venta.precio_unitario,
            cantidad=len(venta.numeros),
            total=total,
            cierre=cierre,
            vendedor=venta.nombre_vendedor
        )
        
        # Devolver el PDF como respuesta
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=recibo_{num_recibo}.pdf"}
        )
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/recibo/{num_recibo}")
async def obtener_recibo(num_recibo: int):
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # Buscar todas las ventas con ese número de recibo
        cursor.execute("""
            SELECT cliente, precio_unitario, numero_jugado
            FROM ventas
            WHERE num_recibo = %s
        """, (num_recibo,))
        
        resultados = cursor.fetchall()
        if not resultados:
            conn.close()
            raise HTTPException(status_code=404, detail="Recibo no encontrado")
        
        # Extraer datos (todos los registros tienen el mismo cliente y precio)
        cliente = resultados[0][0]
        precio_unitario = resultados[0][1]
        numeros = [fila[2] for fila in resultados]  # Lista de todos los números
        
        conn.close()
        
        return {
            "cliente": cliente,
            "precio_unitario": precio_unitario,
            "numeros": numeros
        }
        
    except Exception as e:
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))