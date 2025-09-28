from __future__ import print_function
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
from datetime import datetime
import time

#Copy all recorded songs from "AA Recorded Sets"
#Put them into folder ..MixedNutsLib/AA Recordings By Song/Songs that start with x,x,x/...
# From https://developers.google.com/drive/api/v3/quickstart/python

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
        
def getDestinationFolderId(firstCharacterOfString):
    # get the function from the switcher dictionary
    func = switcher.get(firstCharacterOfString, "Dest not found")
    # Execute the selected function
    return func()

def trashAllInFolder(service, folderId):
    items = getListOfItemIDs(service, folderId) # get a list of items inside the folder of a given ID
    for item in items :
        itemName = item.get('name')
        itemIdentifier = item.get('id')
        print("trashed Item: " + itemName + ": " + itemIdentifier)
        file_metadata = { 'trashed' : True }
        try:
            fileAttr = service.files().update(fileId=itemIdentifier,
                                    body= file_metadata).execute()
        except:
            print("************************************* unale to trash item: " + itemName)
                  
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

        
def main():
    startTime = datetime.now()
    print("Start time: ", startTime)
    
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    store = file.Storage('token.json')
    ##store = file.Storage('my-service-account-key.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
        creds = tools.run_flow(flow, store)
    service = build('drive', 'v3', http=creds.authorize(Http()))

    # Get the ids for various folders inthe mixed nuts google docs library.
    mixedNutsFolderId = getFolderId(service, 'Mixed Nuts Files', 'root')
    aaRecordingsBySetId = getFolderId(service, 'AA Recordings By Set', mixedNutsFolderId)
    aaRecordingsBySongId = getFolderId(service, 'AA Recordings By Song', mixedNutsFolderId)
    SongsStartingWith09id     = getFolderId(service, 'Songs starting with 0-9',         aaRecordingsBySongId)
    SongsStartingWithABid     = getFolderId(service, 'Songs starting with A,B',         aaRecordingsBySongId)
    SongsStartingWithCDEid    = getFolderId(service, 'Songs starting with C,D,E',       aaRecordingsBySongId)
    SongsStartingWithFGHid    = getFolderId(service, 'Songs starting with F,G,H',       aaRecordingsBySongId)
    SongsStartingWithIJid     = getFolderId(service, 'Songs starting with I,J',         aaRecordingsBySongId)
    SongsStartingWithKLMid    = getFolderId(service, 'Songs starting with K,L,M',       aaRecordingsBySongId)
    SongsStartingWithNOPQRid  = getFolderId(service, 'Songs starting with N,O,P,Q,R',   aaRecordingsBySongId)
    SongsStartingWithSid      = getFolderId(service, 'Songs starting with S',           aaRecordingsBySongId)
    SongsStartingWithTid      = getFolderId(service, 'Songs starting with T',           aaRecordingsBySongId)
    SongsStartingWithUVWXYZid = getFolderId(service, 'Songs starting with U,V,W,X,Y,Z', aaRecordingsBySongId)

    # clean out the destination folders
    for x in range(0,4):  # 3 times
        trashAllInFolder(service, SongsStartingWith09id)
        trashAllInFolder(service, SongsStartingWithABid)
        trashAllInFolder(service, SongsStartingWithCDEid)
        trashAllInFolder(service, SongsStartingWithFGHid)
        trashAllInFolder(service, SongsStartingWithIJid)
        trashAllInFolder(service, SongsStartingWithKLMid)
        trashAllInFolder(service, SongsStartingWithNOPQRid)
        trashAllInFolder(service, SongsStartingWithSid)
        trashAllInFolder(service, SongsStartingWithTid)
        trashAllInFolder(service, SongsStartingWithUVWXYZid)
        print("Waiting for 60 seconds . . .")
        time.sleep(60) # wait 60 seconds

    print("\n\nAre all the sub dirs in the AA Recordings By Song dir now empty? If not, wait a while and ")
    input("cancel and rerun this program. It may take a few passes...")
    
    #define a dictionary of folderIDs named destFolderDict
    destFolderDict = {
        '0':SongsStartingWith09id,
        '1':SongsStartingWith09id,
        '2':SongsStartingWith09id,
        '3':SongsStartingWith09id,
        '4':SongsStartingWith09id,
        '5':SongsStartingWith09id,
        '6':SongsStartingWith09id,
        '7':SongsStartingWith09id,
        '8':SongsStartingWith09id,
        '9':SongsStartingWith09id,
        'A':SongsStartingWithABid,
        'B':SongsStartingWithABid,
        'C':SongsStartingWithCDEid,
        'D':SongsStartingWithCDEid,
        'E':SongsStartingWithCDEid,
        'F':SongsStartingWithFGHid, 
        'G':SongsStartingWithFGHid,
        'H':SongsStartingWithFGHid,
        'I':SongsStartingWithIJid,
        'J':SongsStartingWithIJid,
        'K':SongsStartingWithKLMid,
        'L':SongsStartingWithKLMid,
        'M':SongsStartingWithKLMid,
        'N':SongsStartingWithNOPQRid,
        'O':SongsStartingWithNOPQRid,
        'P':SongsStartingWithNOPQRid,
        'Q':SongsStartingWithNOPQRid,
        'R':SongsStartingWithNOPQRid,
        'S':SongsStartingWithSid,
        'T':SongsStartingWithTid,
        'U':SongsStartingWithUVWXYZid,
        'V':SongsStartingWithUVWXYZid,
        'W':SongsStartingWithUVWXYZid,
        'X':SongsStartingWithUVWXYZid,
        'Y':SongsStartingWithUVWXYZid,
        'Z':SongsStartingWithUVWXYZid,
        }    
   
    folderIDs = getListOfItemIDs(service, aaRecordingsBySetId) # get a list of folders inside the "AA Recordings By Set" folder
    for folder in folderIDs :
        folderName = folder.get('name')
        folderIdentifier = folder.get('id')
        itemIDs = getListOfItemIDs(service, folderIdentifier) # get a list of items inside the folder of a given ID
        for item in itemIDs :
            itemName = item.get('name')
            itemIdentifier = item.get('id')
            fixedItemName=fixItemName(itemName) # takes out rouge "-"s
            fixedItemName=RmvLeadZerosAndBlanks(fixedItemName)  # remove leading blanks and numeric digits
            copyItemNewTitle = fixedItemName.rsplit('-')[-1].strip()  # Last segment of the string, split by "-" as the delimiter and striped of leading and trainling blanks.
            try:
                copiedFile = service.files().copy (fileId=itemIdentifier,      
                                body={"parents": [{"kind": "drive#fileLink",
                                      "id": aaRecordingsBySetId}],
                                      "name": copyItemNewTitle}).execute()
            except:
                print("********************************** Unable to copy: " + itemName + " in folder: " + folderName + " to new name: " + copyItemNewTitle)
                
            copiedFileId = copiedFile['id']
            
            # Determine the parent to add (the folder to put it into)
            firstCharacter = copyItemNewTitle[0].upper() # returns upper case of the first character of the copied file name (after striping off leading stuff)
            DestinationFolderId = destFolderDict.get(firstCharacter, "Dest not found")
            if DestinationFolderId == "Dest not found" :
                DestinationFolderId = aaRecordingsBySongId      

            # Retrieve the existing parents to remove
            fileAttr = service.files().get(fileId=copiedFileId,
                                 fields='parents').execute()
            previous_parents = ",".join(fileAttr.get('parents'))
            
            # Move the file to the new folder
            try:
                fileAttr = service.files().update(fileId=copiedFileId,
                                    addParents=DestinationFolderId,
                                    removeParents=previous_parents,
                                    fields='id, parents').execute()
                print("Copied from: " + folderName + "/" + itemName + " to Songs starting with: <" + firstCharacter + "> New name: " + copyItemNewTitle) 
            except:
                print("***************************************** Unable to copy: " + itemName + " in folder: " + folderName)

    endTime = datetime.now()
    print("End time: ", endTime)
    print('Time elapsed (hh:mm:ss.ms) {}'.format(endTime - startTime))
    print("============= The program has finished. ====================")
    input("Press Enter to close the terminal.")

if __name__ == '__main__':
    main()
