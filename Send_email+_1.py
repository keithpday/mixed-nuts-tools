import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email():
    # Sender and recipient details
    sender_email = "keith.day@appsoni.com"
    recipient_email = "keith.day@appsoni.com"

    # Email content
    subject = "Hello"
    body = "Test from Chat GPT"

    # Create a multipart message
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject

    # Add the body to the email
    message.attach(MIMEText(body, "plain"))

    try:
        # Connect to the SMTP server (Thunderbird)
        smtp_server = "localhost"
        smtp_port = 1025
        smtp_connection = smtplib.SMTP(smtp_server, smtp_port)
        smtp_connection.ehlo()

        # Send the email
        smtp_connection.sendmail(sender_email, recipient_email, message.as_string())
        smtp_connection.quit()

        print("Email sent successfully!")

    except Exception as e:
        print("An error occurred while sending the email:", str(e))

# Call the function to send the email
send_email()
