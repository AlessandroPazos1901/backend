# api_server.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
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
            confidence REAL,
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
        ('RPI_HUANUCO_001', 'Raspberry Pi Centro', 'Centro de Huánuco', -9.9306, -76.2422, ?, 'active'),
        ('RPI_HUANUCO_002', 'Raspberry Pi Norte', 'Zona Norte', -9.9250, -76.2380, ?, 'active'),
        ('RPI_HUANUCO_003', 'Raspberry Pi Sur', 'Zona Sur', -9.9360, -76.2470, ?, 'active')
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

from fastapi import Request  # Asegúrate de importar esto también

@app.post("/api/raspberry-data")
async def receive_raspberry_data(
    request: Request,  # 👈 agregado para capturar la URL base real
    raspberry_id: str = Form(...),
    detection_count: int = Form(...),
    temperature: float = Form(...),
    humidity: float = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    confidence: float = Form(...),
    image: UploadFile = File(...)
):
    try:
        # Validar el archivo de imagen
        if not image.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")
        
        # Crear nombre único para la imagen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        image_extension = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
        filename = f"{raspberry_id}_{timestamp}.{image_extension}"
        local_path = f"images/{filename}"
        
        # Guardar imagen en carpeta
        os.makedirs("images", exist_ok=True)
        with open(local_path, "wb") as f:
            content = await image.read()
            f.write(content)

        # ✅ Generar URL pública de la imagen
        base_url = str(request.base_url).rstrip("/")
        image_url = f"{base_url}/images/{filename}"
        
        # Guardar en base de datos
        conn = sqlite3.connect('raspberry_data.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO detections 
            (raspberry_id, timestamp, detection_count, temperature, humidity, 
             latitude, longitude, image_path, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            raspberry_id, 
            datetime.now().isoformat(),
            detection_count,
            temperature,
            humidity,
            latitude,
            longitude,
            image_url,  # 👈 usar la URL pública aquí
            confidence
        ))
        
        cursor.execute('''
            UPDATE raspberry_info 
            SET last_seen = ?, latitude = ?, longitude = ?
            WHERE raspberry_id = ?
        ''', (datetime.now().isoformat(), latitude, longitude, raspberry_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Datos recibidos de {raspberry_id}: {detection_count} detecciones")
        
        return {
            "status": "success", 
            "message": f"Data received successfully from {raspberry_id}",
            "image_path": image_url,
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
               COUNT(d.id) as total_detections,
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
        SELECT id, timestamp, detection_count, confidence, image_filename, 
               image_url, temperature, humidity
        FROM detections 
        WHERE raspberry_id = ?
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (raspberry_id, limit))
    
    columns = ['id', 'timestamp', 'detection_count', 'confidence', 'image_filename',
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
               'image_filename', 'image_url', 'confidence', 'created_at']
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
