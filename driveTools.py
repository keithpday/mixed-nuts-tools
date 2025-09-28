from __future__ import print_function
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
from apiclient.http import MediaFileUpload
from datetime import datetime

# From https://developers.google.com/drive/api/v3/quickstart/python

# Client ID
# 576085676265-tsr jooepajafke52afmoqtjje0ulnucp.apps.googleusercontent.com
# Client Secret
# pxxfkB2fkAQjqhRsfi0ypN5z

# If modifying these scopes, delete the file token.json.
# SCOPES = 'https://www.googleapis.com/auth/drive.metadata.readonly'
SCOPES = 'https://www.googleapis.com/auth/drive'

def getService():
    store = file.Storage('token.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
        creds = tools.run_flow(flow, store)
    service = build('drive', 'v3', http=creds.authorize(Http()))
    return service

def getDbService():
    store = file.Storage('token.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
        creds = tools.run_flow(flow, store)
    dbService = build('drive', 'v3', http=creds.authorize(Http()))
    return dbService




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
        print("Error. More than one folder found for: "  + folderName + " with parentId: " + parentId)
        return None
    else :
        print("Error.  No folder ID found for: "  + folderName + " with parentId: " + parentId)
        return None

def getItemId(service, itemName, parentId) :
    page_token = None
    itemId = None
    queryString = "name contains '" + itemName + "' and '" + parentId + "' in parents and trashed=false" # contains only works with start of name.
    #print('before queryString=' + queryString)
    response = service.files().list(q=queryString,
                                    spaces='drive',
                                    fields='nextPageToken, files(id, name)',
                                    pageToken=page_token).execute()
    #print('after queryString response dict:')
    #print(response)
    itemlist = response.get('files', [])
    #print('itemlist:')
    #print(itemlist)
    if len(itemlist) == 1 :
        return itemlist[0].get('id') 
    elif len(itemlist) > 1 :
        print("Error. More than one item found for: "  + itemName + " with parentId: " + parentId)
        return None
    else :
        print("Error.  No item ID found for: "  + itemName + " with parentId: " + parentId)
        return None
    

def getListOfItemIDs(service, parentId):
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
        
def trashItemInFolder(service, folderId, itemId):
    # no worki:  itemName = itemId.get('name')
    
    file_metadata = { 'trashed' : True }
    try:
        fileAttr = service.files().update(fileId=itemId,
                                body= file_metadata).execute()
        print(" trashed ItemId: " + itemId)
    except:
        print("************************************* unable to trash item: " + itemname)

def trashAllInFolder(service, folderId):
    items = getListOfItemIDs(service, folderId) # get a list of items inside the folder of a given ID
    for item in items :
        itemName = item.get('name')
        itemIdentifier = item.get('id')
        print(" trashed Item: " + itemName + ": " + itemIdentifier)
        file_metadata = { 'trashed' : True }
        try:
            fileAttr = service.files().update(fileId=itemIdentifier,
                                    body= file_metadata).execute()
        except:
            print("************************************* unale to trash item: " + itemname)

def moveItemToNewFolder(service, inputFileId, dstFolderId):
    # Retrieve the existing parents of file to move
    #print('Getting parent ID in prep to move file')
    fileAttr = service.files().get(fileId=inputFileId,
                        fields='parents').execute()
    previous_parents = ",".join(fileAttr.get('parents'))
    #print('previous_parents=' + previous_parents)
    # Move the file to the new folder
    try:
        fileAttr = service.files().update(fileId=inputFileId,
                            addParents=dstFolderId,
                            removeParents=previous_parents,
                            fields='id, parents').execute()
        #print('**** move executed successfully')
    except:
        print("**** Unable to move item in root to a new parent folder ****")
        input("Press Enter to continue...")

def uploadItemToDrive(service, driveFolderId, fromPcPath, item):
    # NO WORKIE: file_metadata = {'name': item, 'parents': ['id': driveFolderId, 'kind': 'drive#file']}
    # NO WORKIE: file_metadata = {'name': item, 'parents': [{'id' : driveFolderId}]}
    # NO WORKIE: file_metadata = {'name': item, 'parents': [{'id': driveFolderId, 'kind': 'drive#file'}]}
    # NO WORKIE: file_metadata = {'name': item, 'parents': [{'id': driveFolderId, 'kind': 'drive#fileLink'}]}
    # So, just let the damn thing upload to root and then move it.
    #print('Debug poin 123')
    file_metadata = {'name': item}
    media = MediaFileUpload(fromPcPath + "/" + item,
                            mimetype='application/pdf')
    file = service.files().create(body=file_metadata,
                                  media_body=media,
                                  fields='id').execute()
    fileId = file.get('id')
    #print('Uploaded file to root with Id: ' + fileId)

    moveItemToNewFolder(service, fileId, driveFolderId)
    #print('Moved fileID ' + fileId + ' to driveFolderID ' + driveFolderId)
    return file.get('id')
    
