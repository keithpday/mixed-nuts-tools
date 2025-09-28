# Mixed Nuts Tables Creation
import sqlite3

conn = sqlite3.connect('mixedNuts.db')

c = conn.cursor()

#   songMasterHdr creation
c.execute('DROP TABLE IF EXISTS newTable')
c.execute("""CREATE TABLE newTable (
    song_hdr_id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_song_name TEXT NOT NULL
    )""")
#c.execute("""
#    INSERT INTO newTable (
#        song_hdr_id,
#        search_song_name
#        )
#    SELECT
#        song_hdr_id,
#        search_song_name
#    FROM songMasterHdr
#    """)
c.execute('DROP TABLE IF EXISTS songMasterHdr')
c.execute('ALTER TABLE newTable RENAME TO songMasterHdr')

#   songMasterDet creation
c.execute('DROP TABLE IF EXISTS newTable')
c.execute("""CREATE TABLE newTable (
    song_det_id INTEGER,
    revision_date TEXT NOT NULL,
    version_code TEXT NOT NULL,
    song_name TEXT NOT NULL,
    meter TEXT NOT NULL,
    tempo INTEGER,
    PRIMARY KEY (song_det_id,
                revision_date,
                version_code)
    )""")
#c.execute("""
#    INSERT INTO newTable (
#        song_det_id,
#        revision_date,
#        version_code,
#        song_name,
#        meter,
#        tempo
#                )
#    SELECT
#        song_det_id,
#        revision_date,
#        version_code,
#        song_name,
#        meter,
#        tempo
#    FROM songMasterDet
#    """)
c.execute('DROP TABLE IF EXISTS songMasterDet')
c.execute('ALTER TABLE newTable RENAME TO songMasterDet')

#   setMasterHdr creation
c.execute('DROP TABLE IF EXISTS newTable')
c.execute("""CREATE TABLE newTable (
    set_hdr_id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_name TEXT NOT NULL,
    google_set_addr TEXT NOT NULL
    )""")

#c.execute("""
#    INSERT INTO newTable (
#        set_hdr_id,
#        set_name,
#        google_set_addr
#        )
#    SELECT
#        set_hdr_id,
#        set_name,
#        google_set_addr    
#    FROM setMasterHdr
#    """)
c.execute('DROP TABLE IF EXISTS setMasterHdr')
c.execute('ALTER TABLE newTable RENAME TO setMasterHdr')

#   setMasterDet creation
c.execute('DROP TABLE IF EXISTS newTable')

c.execute("""CREATE TABLE newTable (
    set_det_id INTEGER,
    set_seq INTEGER,
    song_det_id INTEGER,
    revision_date TEXT NOT NULL,
    version_code TEXT NOT NULL,
    google_song_addr TEXT NOT NULL,
    PRIMARY KEY (set_det_id,
                set_seq)
    )""")

#c.execute("""
#    INSERT INTO newTable (
#        set_det_id,
#        Set_seq,
#        song_det_id,
#        revision_date,
#        version_code,
#        google_song_addr,
#        )
#    SELECT
#        set_hdr_id,
#        set_name,
#        google_set_addr    
#    FROM setMasterHdr
#    """)
c.execute('DROP TABLE IF EXISTS setMasterDet')
c.execute('ALTER TABLE newTable RENAME TO setMasterDet')
#---------------------------------------------------------
conn.commit()

c.execute("""SELECT name FROM sqlite_master 
    WHERE type='table'""")
print("List of tables\n")
print(c.fetchall())


conn.close()
print("the sqlite connection is closed")

