import pytesseract
from PIL import Image

# Specify the path to the Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Load the image
image_path = r"C:\Users\keith\OneDrive\Documents\GitHub\MixedNutsLib\MixedNutsImages\Bob's Summary of 2014.JPG"
image = Image.open(image_path)

# Perform OCR
extracted_text = pytesseract.image_to_string(image)

# Display the extracted text
print("Extracted Text:")
print(extracted_text)
