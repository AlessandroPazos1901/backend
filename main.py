# api_server.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sqlite3
import os
from datetime import datetime
import uvicorn
from pathlib import Path

app = FastAPI(title="Raspberry Pi Data Receiver", version="1.0.0")

# CORS para permitir conexiones desde Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear directorios necesarios
IMAGES_DIR = "images"
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs("static", exist_ok=True)

# Servir archivos estáticos (imágenes) - SOLO UNA RUTA
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# Base de datos
def init_db():
    conn = sqlite3.connect('raspberry_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raspberry_id TEXT,
            timestamp TEXT,
            detection_count INTEGER,
            temperature REAL,
            humidity REAL,
            latitude REAL,
            longitude REAL,
            image_filename TEXT,
            image_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla para información de Raspberry Pi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS raspberry_info (
            raspberry_id TEXT PRIMARY KEY,
            name TEXT,
            location TEXT,
            latitude REAL,
            longitude REAL,
            last_seen TEXT,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Insertar 3 Raspberry Pi de ejemplo si no existen
    cursor.execute('''
        INSERT OR IGNORE INTO raspberry_info 
        (raspberry_id, name, location, latitude, longitude, last_seen, status)
        VALUES 
        ('DIRIS_LIMA', 'Raspberry Pi DIRIS', 'El Agustino', -12.0407, -76.9951, ?, 'online'),
        ('UPC_MONTERRICO', 'Raspberry Pi UPC', 'Monterrico', -12.1037, -76.9630, ?, 'online'),
        ('RPI_MOLINA', 'Raspberry Pi Molina', 'La Molina', -12.0729, -76.9691, ?, 'offline')
    ''', (datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

@app.on_event("startup")
async def startup_event():
    init_db()
    print("🚀 FastAPI server started successfully!")
    print("📊 Database initialized")
    print("📂 Static files directory created")

@app.get("/")
async def root():
    return {"message": "Raspberry Pi Data Receiver API", "status": "running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/api/raspberry-data")
async def receive_raspberry_data(
    raspberry_id: str = Form(...),
    name: str = Form(...),
    location: str = Form(...),
    detection_count: int = Form(...),
    temperature: float = Form(...),
    humidity: float = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),\
    image: UploadFile = File(...)
):
    try:
        # Validar el archivo de imagen
        if not image.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")
        
        # Crear nombre único para la imagen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        image_extension = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
        image_filename = f"{raspberry_id}_{timestamp}.{image_extension}"
        image_path = os.path.join(IMAGES_DIR, image_filename)
        
        # Guardar imagen
        with open(image_path, "wb") as f:
            content = await image.read()
            f.write(content)
        
        # Crear URL completa para la imagen
        # En producción, usa tu dominio de Render
        # En desarrollo, usa localhost
        base_url = os.getenv("BASE_URL")
        image_url = f"{base_url}/images/{image_filename}"
        
        # Guardar en base de datos
        conn = sqlite3.connect('raspberry_data.db')
        cursor = conn.cursor()
        # Verificar si el Raspberry Pi ya existe, si no, lo insertamos
        cursor.execute('SELECT COUNT(*) FROM raspberry_info WHERE raspberry_id = ?', (raspberry_id,))
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO raspberry_info (raspberry_id, name, location, latitude, longitude, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                raspberry_id,
                name,  
                location,
                latitude,
                longitude,
                datetime.now().isoformat(),
                "online"
            ))
            
        # Insertar detección
        cursor.execute('''
            INSERT INTO detections 
            (raspberry_id, timestamp, detection_count, temperature, humidity, 
             latitude, longitude, image_filename, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            raspberry_id, 
            datetime.now().isoformat(),
            detection_count,
            temperature,
            humidity,
            latitude,
            longitude,
            image_filename,
            image_url
        ))
        
        # Actualizar última conexión del Raspberry Pi
        cursor.execute('''
            UPDATE raspberry_info 
            SET last_seen = ?, latitude = ?, longitude = ?, location = ?
            WHERE raspberry_id = ?
        ''', (datetime.now().isoformat(), latitude, longitude, raspberry_id,location))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Datos recibidos de {raspberry_id}: {detection_count} detecciones")
        print(f"🖼️ Imagen guardada: {image_url}")
        
        return {
            "status": "success", 
            "message": f"Data received successfully from {raspberry_id}",
            "image_filename": image_filename,
            "image_url": image_url,
            "detections": detection_count
        }
    
    except Exception as e:
        print(f"❌ Error procesando datos de {raspberry_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing data: {str(e)}")
        
@app.get("/api/raspberry-locations")
async def get_raspberry_locations():
    """Obtener ubicaciones de todos los Raspberry Pi"""
    conn = sqlite3.connect('raspberry_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.raspberry_id, r.name, r.location, r.latitude, r.longitude, 
               r.last_seen, r.status,
               SUM(d.detection_count) as total_detections,
               MAX(d.timestamp) as last_detection
        FROM raspberry_info r
        LEFT JOIN detections d ON r.raspberry_id = d.raspberry_id
        GROUP BY r.raspberry_id
    ''')
    
    columns = ['raspberry_id', 'name', 'location', 'latitude', 'longitude', 
               'last_seen', 'status', 'total_detections', 'last_detection']
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    
    return {"raspberry_locations": data}

@app.get("/api/raspberry-images/{raspberry_id}")
async def get_raspberry_images(raspberry_id: str, limit: int = 20):
    """Obtener imágenes de un Raspberry Pi específico"""
    conn = sqlite3.connect('raspberry_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, timestamp, detection_count, image_filename, 
               image_url, temperature, humidity
        FROM detections 
        WHERE raspberry_id = ?
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (raspberry_id, limit))
    
    columns = ['id', 'timestamp', 'detection_count', 'image_filename',
               'image_url', 'temperature', 'humidity']
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    
    return {"raspberry_id": raspberry_id, "images": data}

@app.get("/api/latest-data")
async def get_latest_data(limit: int = 50):
    """Obtener datos más recientes de todos los Raspberry Pi"""
    conn = sqlite3.connect('raspberry_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM detections 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (limit,))
    
    columns = ['id', 'raspberry_id', 'timestamp', 'detection_count',
               'temperature', 'humidity', 'latitude', 'longitude',
               'image_filename', 'image_url', 'created_at']
    data = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    
    return {"data": data}

@app.get("/api/statistics")
async def get_statistics():
    """Obtener estadísticas generales"""
    conn = sqlite3.connect('raspberry_data.db')
    cursor = conn.cursor()
    
    # Estadísticas básicas
    cursor.execute('SELECT COUNT(*) FROM detections')
    total_detections = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT raspberry_id) FROM detections')
    active_raspberries = cursor.fetchone()[0]
    
    cursor.execute('SELECT AVG(temperature) FROM detections WHERE temperature IS NOT NULL')
    avg_temp = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT AVG(humidity) FROM detections WHERE humidity IS NOT NULL')
    avg_humidity = cursor.fetchone()[0] or 0
    
    # Detecciones por Raspberry Pi
    cursor.execute('''
        SELECT raspberry_id, COUNT(*) as count
        FROM detections
        GROUP BY raspberry_id
        ORDER BY count DESC
    ''')
    detections_by_pi = dict(cursor.fetchall())
    
    conn.close()
    
    return {
        "total_detections": total_detections,
        "active_raspberries": active_raspberries,
        "avg_temperature": round(avg_temp, 2),
        "avg_humidity": round(avg_humidity, 2),
        "detections_by_pi": detections_by_pi
    }

# Endpoint para verificar si una imagen existe
@app.get("/api/image-exists/{image_filename}")
async def check_image_exists(image_filename: str):
    """Verificar si una imagen existe"""
    image_path = os.path.join(IMAGES_DIR, image_filename)
    exists = os.path.exists(image_path)
    
    return {
        "filename": image_filename,
        "exists": exists,
        "path": image_path if exists else None
    }

# Endpoint alternativo para servir imágenes (por si acaso)
@app.get("/api/image/{image_filename}")
async def get_image_file(image_filename: str):
    """Servir imagen específica"""
    image_path = os.path.join(IMAGES_DIR, image_filename)
    
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(
        image_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=3600"}
    )

@app.delete("/api/delete-data")
async def delete_data(
    admin_key: str = Header(...), # Para recibir tokens, API keys o claves
    raspberry_id: str = Query(None),
    start_date: str = Query(None),  # formato: "2024-01-01"
    end_date: str = Query(None)     # formato: "2024-12-31"
):
    if admin_key != "SECRET123":
        raise HTTPException(status_code=403, detail="No autorizado")

    conn = sqlite3.connect("raspberry_data.db")
    cursor = conn.cursor()

    try:
        # 🔁 Caso 1: Borrar por rango de fechas
        if start_date and end_date:
            cursor.execute('''
                DELETE FROM detections
                WHERE DATE(timestamp) BETWEEN ? AND ?
            ''', (start_date, end_date))
            conn.commit()
            return {"status": "success", "message": f"Se eliminaron datos entre {start_date} y {end_date}"}

        # 🎯 Caso 2: Borrar por Raspberry ID
        elif raspberry_id:
            cursor.execute("DELETE FROM detections WHERE raspberry_id = ?", (raspberry_id,))
            cursor.execute("DELETE FROM raspberry_info WHERE raspberry_id = ?", (raspberry_id,))
            conn.commit()
            return {"status": "success", "message": f"Datos eliminados para {raspberry_id}"}

        # 🧹 Caso 3: Borrar todo
        else:
            cursor.execute("DELETE FROM detections")
            cursor.execute("DELETE FROM raspberry_info")
            conn.commit()
            return {"status": "success", "message": "Todos los datos han sido eliminados"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al eliminar datos: {str(e)}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("🍓 Iniciando servidor FastAPI para Raspberry Pi...")
    print("📍 Servidor corriendo en: http://localhost:8000")
    print("📚 Documentación API: http://localhost:8000/docs")
    print("🖼️ Imágenes disponibles en: http://localhost:8000/images/")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=True,  # Auto-reload para desarrollo
        log_level="info"
    )
