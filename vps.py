#!/usr/bin/env python3

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import threading
import time
import re
import asyncio
from bs4 import BeautifulSoup
import logging
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== KONFIGURASI =====
BOT_TOKEN = "8907964626:AAEzd2HVCXRNDS0PFBB8OSoaxftl-Crmmhg"
EMAIL_SENDER = "dinamarianadina62@gmail.com"
EMAIL_PASSWORD = "gioy fgfm nagp hpla"
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_IMAP_SERVER = "imap.gmail.com"
EMAIL_IMAP_PORT = 993
EMAIL_TARGET = "support@support.whatsapp.com"
MESSAGE_TEMPLATE = "i can't verify my number please help"

TIMEOUT_SECONDS = 60   # 1 MENIT
CHECK_INTERVAL = 15    # detik

sent_emails = {}
processed_uids = set()

# ===== SIMPAN UID KE FILE =====
def load_processed_uids():
    global processed_uids
    try:
        with open('processed_uids.json', 'r') as f:
            processed_uids = set(json.load(f))
        logger.info(f"✅ Load {len(processed_uids)} UID tersimpan")
    except:
        processed_uids = set()
        logger.info("📝 File UID baru dibuat")

def save_processed_uids():
    try:
        with open('processed_uids.json', 'w') as f:
            json.dump(list(processed_uids), f)
    except:
        pass

load_processed_uids()

# ===== FUNGSI KIRIM EMAIL =====
def send_email(phone_number):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_TARGET
        msg['Subject'] = f"Verification Help Request - {phone_number}"
        body = f"{MESSAGE_TEMPLATE} {phone_number}"
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, "OK"
    except Exception as e:
        return False, str(e)

# ===== EKSTRAK NOMOR =====
def extract_phone_from_text(text):
    patterns = [r'\+\d{10,15}', r'0\d{9,14}', r'\d{10,15}']
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            for match in matches:
                clean = re.sub(r'[\s\-\(\)]', '', match)
                if len(clean) >= 10:
                    return clean
    return None

# ===== CEK EMAIL (1 MENIT TERAKHIR) =====
def check_emails():
    results = []
    try:
        imap = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER, EMAIL_IMAP_PORT)
        imap.login(EMAIL_SENDER, EMAIL_PASSWORD)
        folders = ['INBOX', '[Gmail]/Spam', 'Spam']
        for folder in folders:
            try:
                imap.select(folder)
                # Cari email dari target dalam 1 MENIT terakhir
                date_since = (time.strftime("%d-%b-%Y", time.gmtime(time.time() - 60)))
                status, messages = imap.uid('search', None, f'(FROM "{EMAIL_TARGET}" SINCE "{date_since}")')
                if status == 'OK' and messages[0]:
                    uid_list = messages[0].split()
                    for uid in uid_list:
                        uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                        if uid_str in processed_uids:
                            continue
                        status, data = imap.uid('fetch', uid, '(RFC822)')
                        if status == 'OK':
                            raw_email = data[0][1]
                            msg = email.message_from_bytes(raw_email)
                            full_text = ""
                            subject_raw, encoding = decode_header(msg.get('Subject', ''))[0]
                            if isinstance(subject_raw, bytes):
                                subject = subject_raw.decode(encoding if encoding else 'utf-8', errors='ignore')
                            else:
                                subject = str(subject_raw) if subject_raw else ""
                            full_text += subject + " "
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    ct = part.get_content_type()
                                    if ct in ['text/plain', 'text/html']:
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            try:
                                                text = payload.decode('utf-8', errors='ignore')
                                                if ct == 'text/html':
                                                    soup = BeautifulSoup(text, 'html.parser')
                                                    text = soup.get_text()
                                                body += text + " "
                                            except:
                                                pass
                            else:
                                payload = msg.get_payload(decode=True)
                                if payload:
                                    try:
                                        body = payload.decode('utf-8', errors='ignore')
                                    except:
                                        pass
                            full_text += body
                            phone_found = extract_phone_from_text(full_text)
                            if not phone_found:
                                phone_found = extract_phone_from_text(subject)
                            if phone_found:
                                for sent_phone in list(sent_emails.keys()):
                                    sent_clean = re.sub(r'\D', '', sent_phone)
                                    found_clean = re.sub(r'\D', '', phone_found)
                                    if sent_clean.endswith(found_clean[-9:]) or found_clean.endswith(sent_clean[-9:]):
                                        results.append({'phone': sent_phone})
                                        processed_uids.add(uid_str)
                                        save_processed_uids()
                                        break
                imap.close()
            except Exception as e:
                logger.error(f"Folder {folder} error: {e}")
        imap.logout()
    except Exception as e:
        logger.error(f"Error cek email: {e}")
    return results

# ===== KIRIM NOTIFIKASI =====
def send_notification_sync(app, chat_id, message):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(app.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown'))
        loop.close()
        return True
    except Exception as e:
        logger.error(f"Notif error: {e}")
        return False

# ===== THREAD CEK BALASAN =====
def check_replies_loop(app):
    logger.info("🔄 Monitoring balasan... (interval 15s, timeout 1 menit)")
    last_check = 0
    
    while True:
        try:
            current_time = time.time()
            
            if current_time - last_check >= CHECK_INTERVAL:
                last_check = current_time
                logger.info(f"🔍 Cek email... ({len(sent_emails)} diproses)")
                
                replies = check_emails()
                if replies:
                    logger.info(f"📨 Ditemukan {len(replies)} balasan baru!")
                    for reply in replies:
                        phone = reply['phone']
                        if phone in sent_emails:
                            data = sent_emails[phone]
                            message = f"""📬 WHATSAPP SUDAH MERESPON ✅

📱 Nomor: {phone}
✅ STATUS: SUCCESS (Dibalas)

🚀 GAS LOGIN BRAY.. LET'S GO!🤗"""
                            send_notification_sync(app, data['chat_id'], message)
                            logger.info(f"✅ Notif untuk {phone}")
                            del sent_emails[phone]
                
                # Cek timeout 1 menit
                expired = []
                for phone, data in sent_emails.items():
                    if current_time - data['timestamp'] > TIMEOUT_SECONDS:
                        expired.append(phone)
                
                for phone in expired:
                    message = f"""⏰ **TIMEOUT!**

📱 Nomor: {phone}
❌ WhatsApp tidak membalas dalam 1 menit.

Silakan coba kirim ulang atau cek email manual."""
                    send_notification_sync(app, sent_emails[phone]['chat_id'], message)
                    logger.info(f"⏰ Timeout {phone}")
                    del sent_emails[phone]
                
                logger.info(f"📊 Status: {len(sent_emails)} diproses")
                
        except Exception as e:
            logger.error(f"❌ Error loop: {e}")
        
        time.sleep(CHECK_INTERVAL)

# ===== HANDLER =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Kirim nomor: `+628123456789`", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    chat_id = update.message.chat_id
    if not phone.startswith('+') or not phone[1:].isdigit():
        await update.message.reply_text("❌ Format salah! Gunakan: `+628123456789`", parse_mode='Markdown')
        return
    if phone in sent_emails:
        await update.message.reply_text(f"⏳ `{phone}` sedang diproses...", parse_mode='Markdown')
        return
    await update.message.reply_text(f"📤 Mengirim untuk: `{phone}`...", parse_mode='Markdown')
    success, msg = send_email(phone)
    if success:
        sent_emails[phone] = {'timestamp': time.time(), 'chat_id': chat_id}
        await update.message.reply_text(
            f"""✅ **BERHASIL!**

📱 Nomor: `{phone}`
🔄 Mengecek balasan...
⏱️ Maksimal 1 menit""",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ {msg}")

async def cek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not sent_emails:
        await update.message.reply_text("📭 Kosong")
        return
    status = "📊 **Status:**\n\n"
    for phone, data in sent_emails.items():
        elapsed = int(time.time() - data['timestamp'])
        menit = elapsed // 60
        detik = elapsed % 60
        status += f"📱 `{phone}` - {menit}m{detik}s\n"
    await update.message.reply_text(status, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 Kirim nomor: `+628123456789`", parse_mode='Markdown')

# ===== MAIN =====
def main():
    print("="*50)
    print("🤖 BOT WHATSAPP VERIFICATION (FIX - 1 MENIT)")
    print("="*50)
    print(f"⏱️ Timeout: {TIMEOUT_SECONDS} detik (1 menit)")
    print(f"🔄 Cek email: setiap {CHECK_INTERVAL} detik")
    print(f"📁 UID tersimpan: {len(processed_uids)}")
    print("="*50)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cek", cek_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    thread = threading.Thread(target=check_replies_loop, args=(app,), daemon=True)
    thread.start()
    print("✅ Thread pengecekan email dimulai.")
    
    print("✅ Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()