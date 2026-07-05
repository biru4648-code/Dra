#!/usr/bin/env python3

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import time
import re
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== KONFIGURASI (GANTI SESUAI KEBUTUHAN) =====
BOT_TOKEN = "8907964626:AAEzd2HVCXRNDS0PFBB8OSoaxftl-Crmmhg"
EMAIL_SENDER = "biru4648@gmail.com"
EMAIL_PASSWORD = "otxd txxo pixl yydy"
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

# ===== CEK EMAIL =====
def check_emails():
    results = []
    try:
        imap = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER, EMAIL_IMAP_PORT)
        imap.login(EMAIL_SENDER, EMAIL_PASSWORD)
        folders = ['INBOX', '[Gmail]/Spam', 'Spam']
        for folder in folders:
            try:
                imap.select(folder)
                status, messages = imap.uid('search', None, f'(FROM "{EMAIL_TARGET}")')
                if status == 'OK' and messages[0]:
                    uid_list = messages[0].split()
                    latest_uids = uid_list[-10:] if len(uid_list) > 10 else uid_list
                    for uid in latest_uids:
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
                                        break
                imap.close()
            except:
                pass
        imap.logout()
    except Exception as e:
        logger.error(f"Error cek email: {e}")
    return results

# ===== JOB CEK BALASAN =====
async def check_replies_job(context: ContextTypes.DEFAULT_TYPE):
    current_time = time.time()
    logger.info(f"🔍 Cek email... ({len(sent_emails)} diproses)")
    
    replies = check_emails()
    if replies:
        logger.info(f"📨 Ditemukan {len(replies)} balasan!")
        for reply in replies:
            phone = reply['phone']
            if phone in sent_emails:
                data = sent_emails[phone]
                # ===== PESAN BALASAN BARU =====
                message = f"""📬 WHATSAPP SUDAH MERESPON ✅

📱 Nomor: {phone}
✅ STATUS: SUCCESS (Dibalas)

🚀 GAS LOGIN BRAY.. LET'S GO!🤗"""
                try:
                    await context.bot.send_message(chat_id=data['chat_id'], text=message, parse_mode='Markdown')
                    logger.info(f"✅ Notif untuk {phone}")
                except Exception as e:
                    logger.error(f"❌ Gagal notif: {e}")
                del sent_emails[phone]
    
    # Cek timeout (1 menit)
    expired = []
    for phone, data in sent_emails.items():
        if current_time - data['timestamp'] > TIMEOUT_SECONDS:
            expired.append(phone)
    for phone in expired:
        message = f"""⏰ **TIMEOUT!**

📱 Nomor: {phone}
❌ WhatsApp tidak membalas dalam 1 menit.

Silakan coba kirim ulang."""
        try:
            await context.bot.send_message(chat_id=sent_emails[phone]['chat_id'], text=message, parse_mode='Markdown')
            logger.info(f"⏰ Timeout {phone}")
        except:
            pass
        del sent_emails[phone]
    
    logger.info(f"📊 Status: {len(sent_emails)} diproses")

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
    print("🤖 BOT WHATSAPP VERIFICATION (1 MENIT)")
    print("="*50)
    print(f"⏱️ Timeout: {TIMEOUT_SECONDS} detik")
    print(f"🔄 Cek email: setiap {CHECK_INTERVAL} detik")
    print("="*50)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cek", cek_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_replies_job, interval=CHECK_INTERVAL, first=5)
        print("✅ Job pengecekan email dijadwalkan.")
    else:
        print("❌ JobQueue tidak tersedia. Pastikan python-telegram-bot versi terbaru (>=20.0).")
        print("   Install ulang dengan: pip install python-telegram-bot --upgrade")
    
    print("✅ Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
