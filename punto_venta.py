import customtkinter as ctk
import requests
from datetime import datetime

# Configuración de la API (dirección de tu servidor local)
API_URL = "http://127.0.0.1:8000/vender"

# Configuración visual de la ventana
ctk.set_appearance_mode("System")  # Modo oscuro/claro automático
ctk.set_default_color_theme("blue")  # Tema azul

class PuntoVentaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configurar la ventana (MÁS GRANDE)
        self.title("Sistema de Lotería - Punto de Venta")
        self.geometry("500x650")  # Aumentamos el alto a 650
        self.resizable(False, False)
        
        # Título
        self.label_titulo = ctk.CTkLabel(self, text="🎱 LOTERÍA EN LÍNEA", font=("Arial", 22, "bold"))
        self.label_titulo.pack(pady=20)
        
        # Campo: Vendedor (fijo por ahora)
        self.label_vendedor = ctk.CTkLabel(self, text="Vendedor:")
        self.label_vendedor.pack(pady=(10, 0))
        self.entry_vendedor = ctk.CTkEntry(self, placeholder_text="CHC1", width=300)
        self.entry_vendedor.insert(0, "CHC1")
        self.entry_vendedor.pack(pady=5)
        
        # Campo: Cliente
        self.label_cliente = ctk.CTkLabel(self, text="Cliente:")
        self.label_cliente.pack(pady=(10, 0))
        self.entry_cliente = ctk.CTkEntry(self, placeholder_text="Nombre del cliente", width=300)
        self.entry_cliente.pack(pady=5)
        
        # Campo: Número (2 cifras)
        self.label_numero = ctk.CTkLabel(self, text="Número (2 cifras):")
        self.label_numero.pack(pady=(10, 0))
        self.entry_numero = ctk.CTkEntry(self, placeholder_text="Ej: 08", width=300)
        self.entry_numero.pack(pady=5)
        
        # Campo: Precio
        self.label_precio = ctk.CTkLabel(self, text="Precio (Lempiras):")
        self.label_precio.pack(pady=(10, 0))
        self.entry_precio = ctk.CTkEntry(self, placeholder_text="Ej: 15.00", width=300)
        self.entry_precio.pack(pady=5)
        
        # Botón Vender (MÁS GRANDE Y BIEN VISIBLE)
        self.btn_vender = ctk.CTkButton(self, text="🟢 VENDER", font=("Arial", 18, "bold"), width=250, height=50, command=self.vender)
        self.btn_vender.pack(pady=30)
        
        # Área de mensajes (MÁS GRANDE Y VISIBLE)
        self.label_resultado = ctk.CTkLabel(self, text="", font=("Arial", 14, "bold"), wraplength=450)
        self.label_resultado.pack(pady=10)

    def vender(self):
        # Obtener datos de los campos
        vendedor = self.entry_vendedor.get()
        cliente = self.entry_cliente.get()
        numero = self.entry_numero.get()
        precio = self.entry_precio.get()
        
        # Validaciones básicas
        if not cliente or not numero or not precio:
            self.label_resultado.configure(text="❌ Por favor, complete todos los campos", text_color="red")
            return
        
        try:
            precio_float = float(precio)
        except ValueError:
            self.label_resultado.configure(text="❌ Precio inválido", text_color="red")
            return
        
        # Validar número de 2 cifras
        if not numero.isdigit() or len(numero) != 2:
            self.label_resultado.configure(text="❌ El número debe ser de 2 dígitos (00-99)", text_color="red")
            return
        
        # Preparar datos para enviar a la API (Cantidad siempre es 1)
        datos = {
            "nombre_vendedor": vendedor,
            "cliente": cliente,
            "numero_jugado": numero,
            "precio_unitario": precio_float,
            "cantidad": 1
        }
        
        try:
            # Enviar a la API (a tu servidor)
            respuesta = requests.post(API_URL, json=datos)
            
            if respuesta.status_code == 200:
                data = respuesta.json()
                self.label_resultado.configure(
                    text=f"✅ Venta exitosa!\nRecibo: {data['num_recibo']}\nCierre: {data['cierre']}\nTotal: L. {data['total']}",
                    text_color="green"
                )
                # Limpiar campos para la siguiente venta
                self.entry_cliente.delete(0, "end")
                self.entry_numero.delete(0, "end")
                self.entry_precio.delete(0, "end")
            else:
                self.label_resultado.configure(text=f"❌ Error del servidor: {respuesta.status_code}", text_color="red")
                
        except requests.exceptions.ConnectionError:
            self.label_resultado.configure(text="❌ No se pudo conectar al servidor.\n¿Está corriendo la API?", text_color="red")

# Ejecutar la app
if __name__ == "__main__":
    app = PuntoVentaApp()
    app.mainloop()