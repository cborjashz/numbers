import psycopg2
from datetime import datetime

# ===== ESTO ES LO ÚNICO QUE DEBES CAMBIAR =====
# Pega aquí tu cadena de conexión (la que modificaste en el Paso 1)
DATABASE_URL = "postgresql://postgres:Cbp43z_121990@db.vfjimjmwnayrairkkdmp.supabase.co:5432/postgres"

def calcular_cierre(hora_venta):
    if hora_venta < 11:
        return "Cierre 1 (11am)"
    elif 11 <= hora_venta < 15:
        return "Cierre 2 (3pm)"
    elif 15 <= hora_venta < 21:
        return "Cierre 3 (9pm)"
    else:
        return "Cierre 1 (11am - Día siguiente)"

def guardar_venta(nombre_vendedor, cliente, numero, precio_unitario, cantidad):
    try:
        # Conectar a la base de datos
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        ahora = datetime.now()
        cierre = calcular_cierre(ahora.hour)
        total = precio_unitario * cantidad
        
        # Buscar el ID del vendedor
        cursor.execute("SELECT id_usuario FROM usuarios WHERE nombre_usuario = %s", (nombre_vendedor,))
        resultado = cursor.fetchone()
        if not resultado:
            print(f"❌ Error: El vendedor '{nombre_vendedor}' no existe en la base de datos.")
            return
        id_usuario = resultado[0]
        
        # Generar número de recibo (temporal)
        num_recibo = int(ahora.timestamp()) % 10000000
        
        # Guardar la venta
        sql = """
            INSERT INTO ventas (num_recibo, id_usuario, cliente, numero_jugado, precio_unitario, cantidad, total, cierre_asignado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (num_recibo, id_usuario, cliente, numero, precio_unitario, cantidad, total, cierre))
        
        conn.commit()
        print(f"✅ ÉXITO! Venta guardada. Recibo: {num_recibo} | Cierre: {cierre}")
        
        cursor.close()
        conn.close()
        return num_recibo

    except Exception as e:
        print(f"❌ ERROR EN LA CONEXIÓN: {e}")

# === EJECUTAR PRUEBA ===
if __name__ == "__main__":
    print("🧪 Intentando guardar una venta de prueba...")
    guardar_venta("CHC1", "Juan", "08", 15.00, 1)