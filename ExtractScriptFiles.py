import os
import shutil

# Set the source and destination directories
source_dir = r"C:\Users\keith\OneDrive\Documents\GitHub\MixedNutsLib\Scripts and Programs\AA Sax Sets"
dest_dir = r"C:\Users\keith\OneDrive\Desktop\Script Extraction"

# Define a function to recursively search for files containing "$Music" in their name
def find_music_files(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if "$Music" in file:
                yield os.path.join(root, file)

# Find all files containing "$Music" in their name and copy them to the destination directory
for music_file in find_music_files(source_dir):
    shutil.copy(music_file, dest_dir)


