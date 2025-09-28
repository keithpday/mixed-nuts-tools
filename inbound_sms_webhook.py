#!/usr/bin/env python3
# Minimal Twilio SMS inbound webhook -> saves to SQLite and auto-replies.
from flask import Flask, request, Response
import sqlite3
import os

DB_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/MyScheduler/myscheduler.db"
app = Flask(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sms_replies (
  id INTEGER PRIMARY KEY,
  from_number TEXT NOT NULL,
  to_number   TEXT NOT NULL,
  body        TEXT NOT NULL,
  received_utc TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

def save_reply(frm, to, body):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute(
            "INSERT INTO sms_replies (from_number, to_number, body) VALUES (?,?,?)",
            (frm, to, body),
        )
        conn.commit()
    finally:
        conn.close()

@app.post("/twilio/sms")
def inbound_sms():
    # Twilio sends application/x-www-form-urlencoded
    frm  = request.form.get("From", "")
    to   = request.form.get("To", "")
    body = request.form.get("Body", "")
    save_reply(frm, to, body)

    # Simple auto-reply (optional)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response><Message>Thanks! We got your reply.</Message></Response>'
    )
    return Response(twiml, mimetype="text/xml")

if __name__ == "__main__":
    init_db()
    # Listen on 0.0.0.0 so the tunnel can reach it
    app.run(host="0.0.0.0", port=5001)
