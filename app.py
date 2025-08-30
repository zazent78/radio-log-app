import sqlite3
import os
import re
from flask import Flask, render_template, request

# Define the absolute path for the database
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "contact_logs.db")
ADIF_FOLDER = os.path.join(PROJECT_ROOT, 'adif_uploads')
os.makedirs(ADIF_FOLDER, exist_ok=True)

app = Flask(__name__)

def parse_adif_content(adif_content):
    """
    Parses the content of an ADIF (Amateur Data Interchange Format)
    and returns a list of contact records.
    """
    records = []
    # Use a more robust regex to find each ADIF tag and its value
    # This regex now handles both <TAGNAME:length>VALUE and <TAGNAME>VALUE
    tags_regex = re.compile(r'<(\w+)(?::\d+)?>([^<]+)', re.IGNORECASE)
    
    # Split the content into QSO record blocks using <EOR>
    qso_blocks = adif_content.split('<EOR>')
    
    for block in qso_blocks:
        if not block.strip():
            continue
            
        record = {}
        # Find all tags and values within the current QSO block
        tags = tags_regex.findall(block)
        for tag, value in tags:
            record[tag.lower()] = value.strip()
            
        # If the QSO record has the required information, add it to the list
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
    Creates a 'logs' table if it doesn't exist
    and saves contact records to the database.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create the 'logs' table
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

def get_stats():
    """Fetches brief statistics from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Total contacts
        c.execute("SELECT COUNT(*) FROM logs")
        total_contacts = c.fetchone()[0]

        # Unique stations
        c.execute("SELECT COUNT(DISTINCT contact_callsign) FROM logs")
        unique_stations = c.fetchone()[0]

        # Most active contact (station with the most QSOs)
        c.execute("""
            SELECT contact_callsign, COUNT(*) as cnt 
            FROM logs 
            GROUP BY contact_callsign 
            ORDER BY cnt DESC 
            LIMIT 1
        """)
        row = c.fetchone()
        
        most_active_contact = f"{row[0]} ({row[1]} contact)" if row and row[0] else "No Data"

        conn.close()

        return {
            "total_contacts": total_contacts,
            "unique_stations": unique_stations, 
            "most_active_contact": most_active_contact
        }
    except sqlite3.OperationalError as e:
        print(f"Database error: {e}. Please ensure you have processed an ADIF file.")
        return {
            "total_contacts": 0,
            "unique_stations": 0,
            "most_active_contact": "No Data"
        }

@app.route("/", methods=['GET', 'POST'])
def index():
    query = ""
    contact_records = []
    stats = get_stats()

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if request.method == 'POST':
            query = request.form.get('query', '')
            if query:
                c.execute("""
                    SELECT 
                        station_callsign,
                        contact_callsign,
                        band,
                        mode,
                        qso_date,
                        time_on
                    FROM logs 
                    WHERE station_callsign LIKE ? OR contact_callsign LIKE ?
                    ORDER BY qso_date DESC, time_on DESC
                """, (f"%{query}%", f"%{query}%"))
                contact_records = c.fetchall()
            else:
                c.execute("""
                    SELECT 
                        station_callsign,
                        contact_callsign,
                        band,
                        mode,
                        qso_date,
                        time_on
                    FROM logs
                    ORDER BY qso_date DESC, time_on DESC
                """)
                contact_records = c.fetchall()
        else:
            c.execute("""
                SELECT 
                    station_callsign,
                    contact_callsign,
                    band,
                    mode,
                    qso_date,
                    time_on
                FROM logs
                ORDER BY qso_date DESC, time_on DESC
            """)
            contact_records = c.fetchall()

        conn.close()

    except sqlite3.OperationalError as e:
        print(f"Database error: {e}")
        return render_template('index.html', stats=stats, query=query, error_message="Error: The database is inaccessible. Please ensure you have loaded contact records.")
    
    return render_template('index.html', stats=stats, query=query, contact_records=contact_records)

if __name__ == "__main__":
    # ADIF file processing logic on startup
    adif_folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adif_uploads')
    if not os.path.exists(adif_folder_path):
        os.makedirs(adif_folder_path)

    # Check if the database already exists and has records
    db_exists = os.path.exists(DB_PATH)
    if not db_exists:
        print("Database does not exist. Processing uploaded ADIF files...")
        
        adif_files = [f for f in os.listdir(adif_folder_path) if f.lower().endswith(('.adif', '.adi'))]
        if not adif_files:
            print("No ADIF files found in the 'adif_uploads' folder. The server will run with an empty database.")
        else:
            for adif_file in adif_files:
                file_path = os.path.join(adif_folder_path, adif_file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        adif_content = f.read()
                    contacts = parse_adif_content(adif_content)
                    create_and_save_contacts_to_db(contacts)
                    print(f"Successfully processed and saved records from {adif_file}.")
                except Exception as e:
                    print(f"Error while processing file {adif_file}: {e}")

    # Run the Flask application
    print("Starting web server...")
    app.run(debug=True)