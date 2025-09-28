
##processRevisions
import winreg
from os import listdir
from os import makedirs
from os import path
from os import chdir
from os import getcwd
from os import rename
import shutil
from datetime import datetime
import errno
from PyPDF2 import PdfFileWriter, PdfFileReader
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from send2trash import send2trash
from makeSetListPage import makeSetListPage
from makeBook import makeBook
from driveTools import getService
from driveTools import getFolderId
from driveTools import getItemId
from driveTools import trashItemInFolder
from driveTools import uploadItemToDrive
import re
import time
import string
import os

#def makeDirIfNotExist(newPathAndDirectory):
#    # Create target Directory if it doesn't exist
#    if not path.exists(1-newPathAndDirectory):
#        makedirs(newPathAndDirectory)
#        print("Directory: " , newPathAndDirectory ,  " Created ")
#    else:    
#        print("Directory: " , newPathAndDirectory ,  " already exists")

def makeTimeStampedBackup(fromDir, toNewDir):
    shutil.copytree(fromDir, toNewDir)
       

def main():
    # set all defaults
    specialRun = 'N'
    skipDateStamping = 'N'
    skipSetIdStamping = 'N'
    zzSet = 'N'
    todaysDate = datetime.today().strftime('%Y.%m.%d')
    print("\nIs this a special run? (y/n) ", end="")
    specialRun = input()
    specialRun = specialRun.upper()
    print("\nspecialRun = " + specialRun)
    if specialRun == 'Y' :
        print("\nThis is a special run.\n=========================")
        print("Skip date stamping? (y/n) ", end="")
        skipDateStamping = input()
        skipDateStamping = skipDateStamping.upper()
        if skipDateStamping != 'Y' :
            skipDateStamping = 'N'
        print("Skip set Id (and number) stamping? (y/n) ", end="")
        skipSetIdStamping = input()
        skipSetIdStamping = skipSetIdStamping.upper()
        if skipSetIdStamping != 'Y' :
            skipSetIdStamping = 'N'
        print("Is this a special ZZ set? (y/n) ", end="")
        zzSet = input()
        zzSet = zzSet.upper()
        if zzSet != 'Y' :
            zzSet = 'N'
        print("Enter the Revision Date in YYYY.MM.DD format: ", end="")
        todaysDate = input()
    
    
    startTime = datetime.now().strftime('%Y.%m.%d.%H.%M.%S')
            
    srcDir = './PDFsFromBob'  # '.' is the current working directory (set in main)
    # sanitize file names.
    rename_files_in_directory(srcDir)
    unMarkedDir = './UnMarked'
    unMarkedArchiveDir = './UnMarkedArchive'
    
    newlyRenamedDir = './NewlyRenamed'
    newlyRenamedList = listdir(newlyRenamedDir)
    # Clear the NewlyRenamed directory
    for f in newlyRenamedList :
        send2trash(newlyRenamedDir + "/" + f)
        
    newlyMarkedDir = './NewlyMarked'
    newlyMarkedList = listdir(newlyMarkedDir)
    # Clear the NewlyMarked directory
    for f in newlyMarkedList :
        send2trash(newlyMarkedDir + "/" + f)

    markedDir = './Marked'
    markedArchiveDir = './MarkedArchive'

    booksDir = './Books'
    booksArchiveDir = './BooksArchive'
    
    fileList = listdir(srcDir)
    unMarkedList = listdir(unMarkedDir)
    markedList = listdir(markedDir)
    booksList = listdir(booksDir)
    
    if len(fileList) < 0:
        print("\nNo files in " + srcDir + " to process.")
        print("====== Nothing to do so the program has finished. =============")
        input("Press Enter to end the program.")
        quit()
    else:
        print("\nFiles found in PDFsFromBob:")
        print("==========================================")
        for item in fileList:             
            print(item)

    backupPath = srcDir + "." + startTime
    makeTimeStampedBackup(srcDir, backupPath)
     
    print("\nWhat is the new or updated Set Id (local)? ", end="")
    setId = input()
    zzSetId = 'None'
    if zzSet == 'Y':
        print("\nWhat is the ZZ name (i.e. \"ZZ Christmas 1\" without the word \"Book\" or \"Set\")? ", end="")
        zzSetId = input()
        
    # Process each file name in fileList
    for f in fileList :
        # Get song name without extention
        subString = f.split('.')[0]  # return first part of string up to the first "."
        # find items in unMarked that contain the song name
        print("\nMatching files for: " + f)
        print("==========================================================")
        for s in unMarkedList :
            if subString.lower() in s.lower():
                print(s)
            
        
        # Generate new file name
        seqNbr = "00"
        if skipSetIdStamping == 'N' :
            print("\nPlease enter the set sequence number for this song: ", end="")
            seqNbr = ("00" + input())[-2:] # gets last two chars in the string
            # print("seqNbr=" + seqNbr)
        if skipSetIdStamping == 'N' and skipDateStamping == 'N' :         
            newFileName = setId + seqNbr + "-" + f.split('.')[0] + "." + todaysDate + '.pdf'
            # print("newFileName=" + newFileName)
        elif skipSetIdStamping == 'Y' and skipDateStamping == 'N' :
            newFileName = f.split('.')[0] + "." + todaysDate + '.pdf'
        elif skipSetIdStamping == 'N' and skipDateStamping == 'Y' :
            newFileName = setId + seqNbr + "-" + f
        else : # both are 'Y'
            newFileName = f
        # input("newFileName = " + newFileName + "  -->(DEBUG) Press Enter to continue.")
         
        rename(srcDir + "/" + f  , newlyRenamedDir + "/" + newFileName)
          
        if skipDateStamping == 'N' :
            # Build overlay PDF
            # input("Building overlay -->(DEBUG) Press Enter to continue.")
            packet = io.BytesIO()
            # create a new PDF in memory witmakeSetListPageh Reportlab
            can = canvas.Canvas(packet, pagesize=letter)
            waterMark1 = "Last revised: " + todaysDate
            waterMark2 = setId + seqNbr
            can.drawString(250, 780 , waterMark1)
            can.drawString(570 - (len(waterMark2) * 5.5), 780 , waterMark2) # X (0 is left, 570 is right), Y (780 is top, 0 is bottom)
            can.save() 
            packet.seek(0)  #move to the beginning of the StringIO buffer
            new_pdf_watermark_overlay = PdfFileReader(packet,strict=False)
             
            # Do the overlay of the newly created watermark page
            inputPdf = open(newlyRenamedDir + "/" + newFileName, "rb")
            existing_pdf_stream = PdfFileReader(inputPdf,strict=False)
            output_pdf_stream = PdfFileWriter()
            
            # add the "waterMark" overlay to every page
            print("beforebefore")
            for pageNum in range(existing_pdf_stream.numPages) :
                print("But did we get here?")
                page = existing_pdf_stream.getPage(pageNum)
                print("We got to here")
                page.mergePage(new_pdf_watermark_overlay.getPage(0))  # get the first and only overlay page every time
                output_pdf_stream.addPage(page)
            print("before")
            # finally, write "output" (every page)to a real file
            resultPdfFile = open(newlyMarkedDir + "/" + newFileName, "wb")
            output_pdf_stream.write(resultPdfFile)  # write to the disk
            # close the newly created output PDFimport re
            resultPdfFile.close()
            print("after")
            # close original input PDF
            inputPdf.close()
            
        else :
            shutil.copyfile(newlyRenamedDir + "/" + newFileName , newlyMarkedDir + "/" + newFileName)
               
        subString = newFileName.split('.')[0]  # return first part of file name up to the first "."
        
        # Move old song from unMarked to UnMarkedArchived
        for s in unMarkedList :       
            if subString.lower() in s.lower():
                print("substring: " + subString)
                print("item: " + s)
                # move from UnMarked to UnMarkedArchive
                try:
                    shutil.move(unMarkedDir + "/" + s , unMarkedArchiveDir)
                except:
                    print("\nUnable to move " + unMarkedDir + "/" + s + " to " + unMarkedArchiveDir)
                    input("Press Enter to continue...")

        # Move old songs from Marked to MarkedArchived
        for s in markedList :
            n = s.lower() # n = lower cased name
            if subString.lower() in n :
                print("substring: " + subString)
                print("item: " + s)
                # move from Marked to MarkedArchive
                try:
                    shutil.move(markedDir + "/" + s , markedArchiveDir)
                except:
                    print("\nUnable to move " + markedDir + "/" + s + " to " + markedArchiveDir)
                    input("Press Enter to continue...")


        # Move the newly named (unmarked) file to the UnMarked directory
        try:
            shutil.move(newlyRenamedDir + "/" + newFileName , unMarkedDir)
        except:
            print("\nUnable to move " + newlyRenamedDir + "/" + newFileName + " to " + unMarkedDir)
            input("Press Enter to continue...")

        # Move the newly marked file to the Marked directory
        try:
            shutil.move(newlyMarkedDir + "/" + newFileName , markedDir)
        except:
            print("\nUnable to move " + newlyMarkedDir + "/" + newFileName + " to " + markedDir)
            input("Press Enter to continue...")

        # Move original file to trash 
        #send2trash(srcDir + "/" + f)
    # move old setlist file to the MarkedArchive directory
    subString = setId + "00-" # Should be the one and only set list file.
    for s in markedList :
        n = s.lower() # n = lower cased name
        if  n.startswith(subString.lower()):
            # move from Marked to MarkedArchive
            try:
                shutil.move(markedDir + "/" + s , markedArchiveDir)
            except:
                print("\nUnable to move " + markedDir + "/" + s + " to " + markedArchiveDir)
                input("Press Enter to continue...")
                
    input("(DEBUG) Will now call the makeSetListPage module...")
    # Build the setlist doc from the files in the Marked directory.
    makeSetListPage(setId, todaysDate, markedDir)
    # move old book file to the BooksArchive directory
    setNameSubString = setId + " Book." # Should be the one and only book file.
    if zzSet == "Y":
        setNameSubString = zzSetId + " Book." # Should be the one and only book file.
    for b in booksList :
        n = b.lower() # n = lower cased name
        if setNameSubString.lower() in n :
            # move from Books to BooksArchive
            try:
                shutil.move(booksDir + "/" + b , booksArchiveDir)
            except:
                print("\nUnable to move " + booksDir + "/" + b + " to " + booksArchiveDir)
                input("Press Enter to continue...")
    # Make the Book from the files in the Marked directory
    bookDirAndName = makeBook(setId, todaysDate, markedDir, booksDir, zzSetId)
    bookFileName = path.basename(bookDirAndName)  # get just the file name
    # Publish the changes to Google Drive
    # Establish connection service
    print("\nPlease wait.  Now publishing changes to Google Drive. . . . .")
    service = getService()
    # Remove the Book file from Google drive
    #input("(DEBUG) Will now get mixedNutsFilesId...")
    mixedNutsFilesId = getFolderId(service, 'Mixed Nuts Files', 'root')
    #print("mixedNutsFilesId  = " + mixedNutsFilesId)
    #input("(DEBUG) Will now get aaMusicBooksId...")
    aaMusicBooksId = getFolderId(service, 'AA Music Books', mixedNutsFilesId)
    #("aaMusicBooksId  = " + aaMusicBooksId)
    #input("(DEBUG) Will now get bookId...")
    bookId = getItemId(service, setNameSubString, aaMusicBooksId)
    if bookId != None :
        print("bookId to trash: " + bookId)
        trashItemInFolder(service, aaMusicBooksId, bookId)
        if specialRun == 'Y' :
            input("Was book trashed?  Will upload book next...")
    uploadItemToDrive(service, aaMusicBooksId, booksDir, bookFileName)
    #input("(DEBUG) Will now get aaMusicSetsId...")
    aaMusicSetsId = getFolderId(service, 'AA Music Sets', mixedNutsFilesId)
    #print("aaMusicSetsId  = " + aaMusicSetsId)
    setFolderName = "Set " + setId
    if zzSet == "Y":
        setFolderName = zzSetId + " Set" # Should be the one and only set
    #input("(DEBUG) Will now get setFolderId...")
    setFolderId = getFolderId(service, setFolderName, aaMusicSetsId)
    #print("setFolderId  = " + setFolderId)
    regExPattern = setId + "[0-9][0-9]-*"  # the digits 0-9 (in pos 1) and 0-9 (in pos 2).
    pattern = re.compile(regExPattern)
    for filename in listdir(markedDir):
        # if a matching file is found, trash it
        if re.match(pattern, filename) and filename.endswith('.pdf') and todaysDate in filename:
            fileId = getItemId(service, filename.split('.')[0], setFolderId)
            if fileId != None: # if older version found, trash it.
                trashItemInFolder(service, setFolderId, fileId)
                #input("(DEBUG) Was " + filename.split('.')[0] + " trashed?  Press Enter to continue...")
            #time.sleep(2) # going too fast causes issues
            uploadItemToDrive(service, setFolderId, markedDir, filename)
            #time.sleep(5) # going too fast causes issues
            #input("(DEBUG) Was " + filename + " uploaded?  Press Enter to continue...")
 
    print("\n============= The program has finished. ====================")
    input("Press Enter to close the terminal.")
    
def rename_files_in_directory(subdirectory_path):
    # Check if the subdirectory exists
    if not os.path.exists(subdirectory_path):
        print(f"Subdirectory '{subdirectory_path}' does not exist.")
        return

    # Iterate through files in the subdirectory
    for filename in os.listdir(subdirectory_path):
        old_path = os.path.join(subdirectory_path, filename)

        # Create a sanitized version of the filename
        new_filename = sanitize_filename(filename)
        new_path = os.path.join(subdirectory_path, new_filename)

        # Rename the file
        os.rename(old_path, new_path)
        print(f"Renamed '{filename}' to '{new_filename}'")

        
# sanitize by stripping invalid ascii letters and string digits and periods.
# so any of these chars (and other wierd stuff) in the file name get dropped out: !@#$%^&*+,.'":;<>?
# Leave $ on beginning of $taking scripts.
def sanitize_filename(filename):
    root, ext = os.path.splitext(filename)
    valid_chars = f"-_() {string.ascii_letters}{string.digits}"
    # Check if the first character is "$"
    if root.startswith("$"):
        new_root = "$" + ''.join(c if c in valid_chars else '' for c in root[1:])
    else:
        new_root = ''.join(c if c in valid_chars else '' for c in root)
    return f"{new_root}.{ext.strip('.')}"
    
if __name__ == '__main__':
    # Set environment variable
    # os.environ['FRED'] = 'C:/Users/Keith.day/yup'
    # get environment variable
    # import os
    # fred = os.environ.get('FRED',None)
    # print("fred: ", fred)
    # reg_path = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
    # reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
    # system_environment_variables = winreg.QueryValueEx(reg_key, 'OneDrive')[0]
    # print("system_environment_variables: ", system_environment_variables)
    # input("Press Enter to continue...")
    chdir('C:/Users/keith/OneDrive/Documents/GitHub/MixedNutsLib')
    print('Current working directory has been set to: ' + getcwd())
    main()
