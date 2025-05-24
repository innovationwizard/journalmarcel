import imaplib
import email
from email.header import decode_header
import html2text
import os
import re
from datetime import datetime
import uuid

IMAP_SERVER = 'imap.zoho.com'
EMAIL_ACCOUNT = os.environ.get('ZOHO_EMAIL')
PASSWORD = os.environ.get('ZOHO_APP_PASSWORD')

POSTS_DIR = 'public/posts'
ATTACHMENTS_DIR = 'public/posts/attachments'

os.makedirs(POSTS_DIR, exist_ok=True)
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9\- ]', '', text).strip().replace(' ', '-').lower()

def decode_mime_words(s):
    decoded_fragments = decode_header(s)
    return ''.join(
        fragment.decode(encoding or 'utf-8') if isinstance(fragment, bytes) else fragment
        for fragment, encoding in decoded_fragments
    )

def save_attachment(part):
    filename = part.get_filename()
    if filename:
        filename = decode_mime_words(filename)
        safe_filename = clean_text(filename)
        filepath = os.path.join(ATTACHMENTS_DIR, safe_filename)
        counter = 1
        # Avoid overwriting files
        while os.path.exists(filepath):
            filepath = os.path.join(ATTACHMENTS_DIR, f"{counter}_{safe_filename}")
            counter += 1
        with open(filepath, 'wb') as f:
            f.write(part.get_payload(decode=True))
        return filepath
    return None

def get_email_content(msg):
    body = None
    html = None
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "")
            content_type = part.get_content_type()

            if content_disposition:
                dispositions = content_disposition.strip().split(";")
                if dispositions[0].lower() == "attachment":
                    filepath = save_attachment(part)
                    if filepath:
                        attachments.append(filepath)
            elif content_type == "text/plain" and body is None:
                charset = part.get_content_charset() or 'utf-8'
                body = part.get_payload(decode=True).decode(charset, errors='replace')
            elif content_type == "text/html" and html is None:
                charset = part.get_content_charset() or 'utf-8'
                html = part.get_payload(decode=True).decode(charset, errors='replace')
                body = html2text.html2text(html)  # Convert HTML to markdown
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            charset = msg.get_content_charset() or 'utf-8'
            body = msg.get_payload(decode=True).decode(charset, errors='replace')
        elif content_type == "text/html":
            charset = msg.get_content_charset() or 'utf-8'
            html = msg.get_payload(decode=True).decode(charset, errors='replace')

    return body, html, attachments

def create_markdown_file(subject, date, body, attachments):
    date_str = date.strftime('%Y-%m-%d-%H-%M-%S')
    filename_subject = clean_text(subject) or 'untitled'
    filename = f"{date_str}-{filename_subject}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    # Embed attachments as relative links in markdown (if any)
    attachment_links = ""
    if attachments:
        attachment_links = "\n\n## Attachments\n"
        for path in attachments:
            rel_path = os.path.relpath(path, POSTS_DIR)
            attachment_links += f"![{os.path.basename(path)}]({rel_path})\n"

    front_matter = f"""+++
title = "{subject.replace('"', '\\"')}"
date = "{date.strftime('%Y-%m-%dT%H:%M:%S%z')}"
draft = false
+++

{body if body else ''}

{attachment_links}
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(front_matter)
    print(f"Created post: {filepath}")

def main():
    try:
        # Connect to IMAP server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, PASSWORD)
        mail.select("inbox")
    except Exception as e:
        print(f"Failed to connect or login to IMAP server: {e}")
        return

    try:
        # Search for unread emails
        status, messages = mail.search(None, 'UNSEEN')
        if status != 'OK':
            print("Failed to search for unread emails!")
            mail.logout()
            return

        email_ids = messages[0].split()
        print(f"Found {len(email_ids)} unread emails.")

        for eid in email_ids:
            try:
                # Fetch email
                status, msg_data = mail.fetch(eid, '(RFC822)')
                if status != 'OK':
                    print(f"Failed to fetch email ID {eid}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Extract subject
                subject = msg['Subject']
                if subject:
                    subject = decode_mime_words(subject)
                else:
                    subject = "No Subject"

                # Extract date
                date_tuple = email.utils.parsedate_tz(msg['Date'])
                if date_tuple:
                    date = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                else:
                    date = datetime.now()

                # Get email content and attachments
                body, html, attachments = get_email_content(msg)
                content = body or (html if html else "")

                # Create markdown file; mark email as "read" only on success
                try:
                    create_markdown_file(subject, date, content, attachments)
                    mail.store(eid, '+FLAGS', '\\Seen')  # Mark as "read" after success
                except Exception as e:
                    print(f"Failed to create markdown file for email ID {eid}: {e}")
                    continue

            except Exception as e:
                print(f"Error processing email ID {eid}: {e}")
                continue

    except Exception as e:
        print(f"Error during email processing: {e}")
    finally:
        try:
            mail.logout()
        except Exception as e:
            print(f"Failed to logout from IMAP server: {e}")

if __name__ == "__main__":
    main()
