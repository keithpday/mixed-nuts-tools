import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect('music.db')
cursor = conn.cursor()

# Read values from Tempo, Meter, Type columns in charts_by_set
cursor.execute('SELECT SongTitle, Meter, Tempo, Type FROM charts_by_set')

# Fetch all rows returned by the query
rows = cursor.fetchall()

# Loop through each row and update Time_signature, temp, and type in song_master where song_name in song_master matches SongTitle in charts_by_set
for row in rows:
    # print('row=' + str(row))
    # Extract Tempo, Meter, and Type values
    songtitle_value,  meter_value, tempo_value, type_value = row 

    # print('songtitle_value=' + songtitle_value)
    # Find the matching row in song_master
    #cursor.execute('SELECT * FROM song_master WHERE song_name = ? LIMIT 1', (songtitle_value,))
    cursor.execute('SELECT * FROM song_master WHERE song_name = ?', (songtitle_value,))
    matching_row = cursor.fetchone()

    if matching_row:
        # print('Row match')
        # Update time_signature, tempo and type in song_master where song_name in song_master matches SongTitle in charts_by_set
        cursor.execute('UPDATE song_master SET time_signature = ?, tempo = ?, type = ? WHERE song_name = ?', (meter_value, tempo_value, type_value, songtitle_value))

# Commit the changes to the database
conn.commit()
print('Update completed.')
# Close the database connection
conn.close()
