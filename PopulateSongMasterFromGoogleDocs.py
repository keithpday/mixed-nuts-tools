from __future__ import print_function
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
from datetime import datetime
import time
import sqlite3
import re


#Read throught Music Sets and write to song master

# Client ID
# 576085676265-tsr jooepajafke52afmoqtjje0ulnucp.apps.googleusercontent.com
# Client Secret
# pxxfkB2fkAQjqhRsfi0ypN5z

# If modifying these scopes, delete the file token.json.
# SCOPES = 'https://www.googleapis.com/auth/drive.metadata.readonly'
SCOPES = 'https://www.googleapis.com/auth/drive'

def getFolderId(service, folderName, parentId) :
    page_token = None
    folderId = None
    queryString = "name='" + folderName + "' and '" + parentId + "' in parents and trashed=false"
    response = service.files().list(q=queryString,
                                    spaces='drive',
                                    fields='nextPageToken, files(id, name)',
                                    pageToken=page_token).execute()
    folderlist = response.get('files', [])
    if len(folderlist) == 1 :
        return folderlist[0].get('id')
    elif len(folderlist) > 1 :
        print("Program ended. More than one folder found for: "  + folderName + " with parentId: " + parentId)
        quit()
    else :
        print("Program ended.  No folder ID found for: "  + folderName + " with parentId: " + parentId)
        quit()

def getListOfItemIDs(service, parentId) :
    page_token = None
    itemIDs = list() # define an empty list
    queryString = "'" + parentId + "' in parents and trashed=false"
    while True:
        response = service.files().list(q=queryString,
                                        spaces='drive',
                                        fields='nextPageToken, files(id, name)',
                                        pageToken=page_token).execute()
        itemIDs.extend(response.get('files', [])) # this extends the folderIDs list with the items in the current response page
        return itemIDs

        page_token = response.get('nextPageToken', None) # more pages of items
        if page_token is None:
            break
                  
def fixItemName(inString):
    newString = inString
    for subItem in (("-Instrumental", " Instrumental"),
                     ("-Vocals", " Vocals"),
                     ("-Katie", " Katie"),
                     ("-Bob", " Bob"),
                     ("-Wendy", " Wendy"),
                     ("-Sandra", " Sandra"),
                     ("-Duet", " Duet"),
                     ("-Doo", " Doo"),
                     ("-Male", " Male"),
                     ("-Female", " Female"),
                     ("-Doodle", " Doodle"),
                     ("-Leaf", " Leaf"),
                     ("A-My", "A My"),
                     ("Red-Nosed", "Red Nosed"),
                     ("On-A", "On A"),
                     ("Polka-All", "Polka_All"),
                     ("ppy-Hap", "ppy_Hap"),
                     ("-Plenty", " Plenty"),
                     ("-5000", "_5000"),
                     ("-1.mp3", "_1.mp3"),
                     ("-Robyn", " Robyn")):
        newString = newString.replace(*subItem)
    return newString.strip()   # remove any leading and trainling blanks before returning.

def RmvLeadZerosAndBlanks(inString):
    newString = inString.strip()
    for x in range(3,5):  # 4 times
          newString = newString.lstrip() 
          newString = newString.lstrip("0")
          newString = newString.lstrip("1")
          newString = newString.lstrip("2")
          newString = newString.lstrip("3")
          newString = newString.lstrip("4")
          newString = newString.lstrip("5")
          newString = newString.lstrip("6")
          newString = newString.lstrip("7")
          newString = newString.lstrip("8")
          newString = newString.lstrip("9")
    return newString

def create_connection(db_file):
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(e)

    return conn

def clear_table(conn, table):
    """
    Delete all rows in a table
    :param conn:
    :param table:
    :return:
    """

    sql = ''' DELETE FROM ? '''
    print(sql)
    cur = conn.cursor()
    cur.execute(sql, table)
    conn.commit()

    return 

def create_song(conn, song):
    """
    Create a new song
    :param conn:
    :param song:
    :return:
    """

    sql = ''' INSERT INTO song_master  (song_id,
                                        song_name,
                                        file_name,
                                        last_revised_date,
                                        male_female_duet,
                                        time_signature,
                                        tempo,
                                        type,
                                        google_docs_folder_id,
                                        Google_docs_file_id)
              VALUES(?,?,?,?,?,?,?,?,?,?) '''
    cur = conn.cursor()
    cur.execute(sql, song)
    conn.commit()

    return cur.lastrowid
        
def main():
    startTime = datetime.now()
    print("Start time: ", startTime)

    
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    store = file.Storage('token.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
        creds = tools.run_flow(flow, store)
    service = build('drive', 'v3', http=creds.authorize(Http()))

    # Get the ids for various folders in the mixed nuts google docs library.
    mixedNutsFolderId = getFolderId(service, 'Mixed Nuts Files', 'root')
    aaMusicSetsId = getFolderId(service, 'AA Music Sets', mixedNutsFolderId)
    
    
    songCount = 0
    # conn = sqlite3.connect(':memory:')pwd
    database = 'music.db'
    conn = create_connection(database)
       
    with conn:
        sql = ''' DELETE FROM song_master ''' # Clear cong_master table
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        
        folderIDs = getListOfItemIDs(service, aaMusicSetsId) # get a list of folders inside the "AA Music Sets" folder
        for folder in folderIDs :
            folderName = folder.get('name')
            folderIdentifier = folder.get('id')
            itemIDs = getListOfItemIDs(service, folderIdentifier) # get a list of items inside the folder of a given ID
            for item in itemIDs :
                itemName = item.get('name')
                itemIdentifier = item.get('id')
                fixedItemName=fixItemName(itemName) # takes out rouge "-"s
                fixedItemName=RmvLeadZerosAndBlanks(fixedItemName)  # remove leading blanks and numeric digits
                fixedItemName=fixedItemName.rsplit('-')[-1].strip()  # Last segment of the string, split by "-" as the delimiter and striped of leading and trainling blanks.
                #try:  # this blows up on strings that have no "-" and even some that donj't have one.
                #    fixedItemName = fixedItemName.split("-",1)[1]  # Remove everything up to and including the first instance of "-".
                #except:
                #    print('Bad item name      : ' + itemName)
                #    print('Bad fixed item name: ' + fixedItemName)
                songName = str(fixedItemName.split('(',1)[0]) # one split as "("  [0] means take just first of two split parts.
                songName = songName.replace("_", "'") # replace underscores with apostrophe
                # slice out the date
                date_format = '&Y.&m.&d'
                trydate = itemName[-14:-4]
                # print(trydate)
                # let's validate the date portion.  Set to 0001.01.01 if valid date not present.
                try:
                    trydate2 = datetime.strptime(trydate, '%Y.%m.%d')
                    revisionDate = trydate
                except ValueError:
                    revisionDate = '0001.01.01'
                #print(revisionDate)
                male_female_duet = 'none'
                try:
                    male_female_duet = re.search('\((.*?)\)', itemName).group(1) # get stuff betewwn parenthesis (which I had to escape) with regex search.
                except AttributeError:
                    # parenthesis not found in the original string
                    male_female_duet = '' # apply your error handling

                songCount += 1
                # Here is where we write to song_master
                song = [
                        songCount,
                        songName,
                        itemName,
                        revisionDate,
                        male_female_duet,
                        'Unknown TimeSig',
                        0,
                        'Unknown type',
                        folderIdentifier,
                        itemIdentifier
                        ]
                song_id = create_song(conn, song)
                #print("Song_id:" + str(song_id) + "||song_name:" + songName + "||file_name:" + itemName)
 
    endTime = datetime.now()
    print("End time: ", endTime)
    print('Time elapsed (hh:mm:ss.ms) {}'.format(endTime - startTime))
    print("============= The program has finished. ====================")
    input("Press Enter to close the terminal.")

if __name__ == '__main__':
    main()
