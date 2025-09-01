import sqlite3
import os
import re
from flask import Flask, render_template, request

# Tentukan laluan mutlak untuk pangkalan data
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "contact_logs.db")
ADIF_FOLDER = os.path.join(PROJECT_ROOT, 'adif_uploads')
os.makedirs(ADIF_FOLDER, exist_ok=True)

app = Flask(__name__)

def parse_adif_content(adif_content):
    """
    Menghuraikan kandungan ADIF (Amateur Data Interchange Format)
    dan mengembalikan senarai rekod hubungan.
    """
    records = []
    # Gunakan regex yang lebih mantap untuk mencari setiap tag ADIF dan nilainya
    tags_regex = re.compile(r'<(\w+)(?::\d+)?>([^<]+)', re.IGNORECASE)
    
    # Pisahkan kandungan ke dalam blok rekod QSO menggunakan <EOR>
    qso_blocks = adif_content.split('<EOR>')
    
    for block in qso_blocks:
        if not block.strip():
            continue
            
        record = {}
        # Cari semua tag dan nilai dalam blok QSO semasa
        tags = tags_regex.findall(block)
        for tag, value in tags:
            record[tag.lower()] = value.strip()
            
        # Jika rekod QSO mempunyai maklumat yang diperlukan, tambahkan ke dalam senarai
        if all(key in record for key in ['station_callsign', 'call', 'band', 'mode', 'qso_date', 'time_on']):
            records.append({
                'station_callsign': record.get('station_callsign', 'N/A'),
                'contact_callsign': record.get('call', 'N/A'),
                'band': record.get('band', 'N/A'),
                'mode': record.get('mode', 'N/A'),
                'qso_date': record.get('qso_date', 'N/A'),
                'time_on': record.get('time_on', 'N/A')
            })
            
    return records

def create_and_save_contacts_to_db(contacts):
    """
    Mencipta jadual 'logs' jika tidak wujud
    dan menyimpan rekod hubungan ke pangkalan data.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Cipta jadual 'logs'
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY,
            station_callsign TEXT,
            contact_callsign TEXT,
            band TEXT,
            mode TEXT,
            qso_date TEXT,
            time_on TEXT
        )
    ''')
    
    for contact in contacts:
        c.execute('''
            INSERT INTO logs (station_callsign, contact_callsign, band, mode, qso_date, time_on) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (contact['station_callsign'], contact['contact_callsign'], contact['band'], 
              contact['mode'], contact['qso_date'], contact['time_on']))
              
    conn.commit()
    conn.close()

# --- Fungsi Baru untuk Statistik ---

def get_unique_station_callsigns():
    """Mengambil senarai unik semua stesen master."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT DISTINCT station_callsign FROM logs ORDER BY station_callsign")
        stations = [row[0] for row in c.fetchall()]
        conn.close()
        return stations
    except sqlite3.OperationalError:
        return []

def get_global_stats():
    """Mengambil statistik global ringkas dari pangkalan data."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM logs")
        total_contacts = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT contact_callsign) FROM logs")
        unique_stations = c.fetchone()[0]
        c.execute("SELECT contact_callsign, COUNT(*) as cnt FROM logs GROUP BY contact_callsign ORDER BY cnt DESC LIMIT 1")
        row = c.fetchone()
        most_active_contact = f"{row[0]} ({row[1]} contact)" if row and row[0] else "Tiada Data"
        conn.close()
        return {
            "total_contacts": total_contacts,
            "unique_stations": unique_stations,
            "most_active_contact": most_active_contact
        }
    except sqlite3.OperationalError as e:
        print(f"Ralat pangkalan data: {e}")
        return {"total_contacts": 0, "unique_stations": 0, "most_active_contact": "Tiada Data"}

def get_station_stats(callsign):
    """Mengambil statistik untuk stesen master yang dipilih."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Jumlah kontak untuk stesen ini
        c.execute("SELECT COUNT(*) FROM logs WHERE station_callsign = ?", (callsign,))
        total_contacts = c.fetchone()[0]
        # Jumlah stesen unik yang dihubungi oleh stesen ini
        c.execute("SELECT COUNT(DISTINCT contact_callsign) FROM logs WHERE station_callsign = ?", (callsign,))
        unique_contacts = c.fetchone()[0]
        # Kontak paling aktif yang dihubungi oleh stesen ini
        c.execute("""
            SELECT contact_callsign, COUNT(*) as cnt 
            FROM logs 
            WHERE station_callsign = ? 
            GROUP BY contact_callsign 
            ORDER BY cnt DESC 
            LIMIT 1
        """, (callsign,))
        row = c.fetchone()
        most_active_contact = f"{row[0]} ({row[1]} contact)" if row and row[0] else "Tiada Data"
        conn.close()
        return {
            "total_contacts": total_contacts,
            "unique_contacts": unique_contacts,
            "most_active_contact": most_active_contact,
            "callsign": callsign
        }
    except sqlite3.OperationalError as e:
        print(f"Ralat pangkalan data: {e}")
        return None

# --- Laluan Flask ---

@app.route("/", methods=['GET', 'POST'])
def index():
    query = ""
    contact_records = []
    selected_station_stats = None
    
    # Dapatkan senarai stesen master yang unik untuk menu lungsur
    station_masters = get_unique_station_callsigns()
    
    # Dapatkan statistik global
    global_stats = get_global_stats()

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if request.method == 'POST':
            # Semak borang mana yang dihantar
            if 'query' in request.form:
                query = request.form.get('query', '')
                if query:
                    c.execute("""
                        SELECT station_callsign, contact_callsign, band, mode, qso_date, time_on
                        FROM logs 
                        WHERE station_callsign LIKE ? OR contact_callsign LIKE ?
                        ORDER BY qso_date DESC, time_on DESC
                    """, (f"%{query}%", f"%{query}%"))
                    contact_records = c.fetchall()
                else:
                    c.execute("SELECT * FROM logs ORDER BY qso_date DESC, time_on DESC")
                    contact_records = c.fetchall()
            elif 'station_master' in request.form:
                selected_callsign = request.form.get('station_master')
                selected_station_stats = get_station_stats(selected_callsign)
                # Dapatkan rekod untuk stesen yang dipilih sahaja
                c.execute("""
                    SELECT station_callsign, contact_callsign, band, mode, qso_date, time_on
                    FROM logs
                    WHERE station_callsign = ?
                    ORDER BY qso_date DESC, time_on DESC
                """, (selected_callsign,))
                contact_records = c.fetchall()
        else:
            # Laluan GET lalai
            c.execute("SELECT * FROM logs ORDER BY qso_date DESC, time_on DESC")
            contact_records = c.fetchall()

        conn.close()

    except sqlite3.OperationalError as e:
        print(f"Ralat pangkalan data: {e}")
        return render_template('index.html', 
                                global_stats=global_stats, 
                                station_masters=station_masters,
                                query=query, 
                                error_message="Ralat: Pangkalan data tidak boleh diakses. Sila pastikan anda telah memuatkan rekod kontak.")

    return render_template('index.html', 
                            global_stats=global_stats, 
                            station_masters=station_masters,
                            selected_station_stats=selected_station_stats, 
                            query=query, 
                            contact_records=contact_records)

if __name__ == "__main__":
    adif_folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adif_uploads')
    if not os.path.exists(adif_folder_path):
        os.makedirs(adif_folder_path)

    db_exists = os.path.exists(DB_PATH)
    if not db_exists:
        print("Pangkalan data tidak wujud. Memproses fail ADIF yang dimuat naik...")
        adif_files = [f for f in os.listdir(adif_folder_path) if f.lower().endswith(('.adif', '.adi'))]
        if not adif_files:
            print("Tiada fail ADIF ditemui. Pelayan akan berjalan dengan pangkalan data kosong.")
        else:
            for adif_file in adif_files:
                file_path = os.path.join(adif_folder_path, adif_file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        adif_content = f.read()
                    contacts = parse_adif_content(adif_content)
                    create_and_save_contacts_to_db(contacts)
                    print(f"Berjaya memproses dan menyimpan rekod dari {adif_file}.")
                except Exception as e:
                    print(f"Ralat semasa memproses fail {adif_file}: {e}")

    print("Memulakan pelayan web...")
    app.run(debug=True)