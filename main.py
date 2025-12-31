import os
import json
import base64
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from firebase_admin import firestore
from googleapiclient.errors import HttpError
from datetime import datetime

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly'
]

_sheet_metadata_cache = {}

def get_google_services(user_email):
    db = firestore.client()
    doc = db.collection("users").document(user_email).get()
    if not doc.exists:
        raise Exception("❌ Không tìm thấy token cho người dùng")

    creds = Credentials.from_authorized_user_info(json.loads(doc.to_dict()["token"]), SCOPES)
    return (
        build('gmail', 'v1', credentials=creds),
        build('sheets', 'v4', credentials=creds),
        build('drive', 'v3', credentials=creds)
    )

def get_sheet_metadata(sheets_service, spreadsheet_id):
    global _sheet_metadata_cache
    if spreadsheet_id not in _sheet_metadata_cache:
        try:
            _sheet_metadata_cache[spreadsheet_id] = sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
        except Exception as e:
            print(f"❌ get_sheet_metadata error: {e}")
            return None
    return _sheet_metadata_cache.get(spreadsheet_id)

def get_sheet_id_by_name(sheets_service, spreadsheet_id, sheet_name):
    try:
        spreadsheet = get_sheet_metadata(sheets_service, spreadsheet_id)
        if spreadsheet:
            for sheet in spreadsheet.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    return sheet['properties']['sheetId']
    except Exception as e:
        print(f"❌ get_sheet_id_by_name error: {e}")
    return None

def safe_batch_update(service, spreadsheet_id, body, retries=3):
    for attempt in range(retries):
        try:
            return service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
        except HttpError as e:
            if e.resp.status in [503, 500, 429]:
                wait = 2 ** attempt
                print(f"⚠️ Retry batchUpdate (attempt {attempt + 1}) after {wait}s due to error: {e}")
                time.sleep(wait)
            else:
                raise e

def batch_delete_rows_from_output_sheet(sheets_service, spreadsheet_id, row_indices, start_row=3, sheet_name="Output"):
    try:
        if not row_indices:
            return True
            
        output_sheet_id = get_sheet_id_by_name(sheets_service, spreadsheet_id, sheet_name)
        if output_sheet_id is None:
            return False

        sorted_indices = sorted(row_indices, reverse=True)
        delete_requests = []
        
        for row_index in sorted_indices:
            actual_row_index = row_index + start_row - 1
            delete_requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": output_sheet_id,
                        "dimension": "ROWS",
                        "startIndex": actual_row_index - 1,
                        "endIndex": actual_row_index
                    }
                }
            })

        if delete_requests:
            batch_request = {"requests": delete_requests}
            safe_batch_update(sheets_service, spreadsheet_id, batch_request)

        
        return True
    except Exception as e:
        print(f"❌ batch_delete_rows_from_output_sheet error: {e}")
        return False

def batch_move_to_send_email_sheet(sheets_service, spreadsheet_id, rows_data, send_sheet_name="send_email"):
    spreadsheet = get_sheet_metadata(sheets_service, spreadsheet_id)

    if send_sheet_name not in [s['properties']['title'] for s in spreadsheet.get('sheets', [])]:
        create_sheet_request = {"requests": [{"addSheet": {"properties": {"title": send_sheet_name}}}]}
        sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=create_sheet_request).execute()
        _sheet_metadata_cache.pop(spreadsheet_id, None)

    if rows_data:
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{send_sheet_name}!A:N",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows_data}
        ).execute()

def batch_format_send_email_sheet(sheets_service, spreadsheet_id, start_row, status_list, send_sheet_name="send_email"):
    try:
        sheet_id = get_sheet_id_by_name(sheets_service, spreadsheet_id, send_sheet_name)
        if sheet_id is None:
            return True

        format_requests = []
        for i, status in enumerate(status_list):
            # Chọn màu theo Status
            if status == "Reply vào luồng mail đã có":
                # xanh lá nhạt
                color = {"red": 0.8, "green": 0.94, "blue": 0.8}
            elif status == "Tạo luồng mail mới":
                # vàng nhạt
                color = {"red": 1.0, "green": 0.95, "blue": 0.8}
            elif status == "Lỗi khi gửi mail":
                # đỏ nhạt
                color = {"red": 1.0, "green": 0.8, "blue": 0.8}
            else:
                # fallback: xám nhạt cho các trạng thái khác
                color = {"red": 0.9, "green": 0.9, "blue": 0.9}

            format_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        # start_row là 1-based, Sheets API dùng 0-based → -1
                        "startRowIndex": start_row + i - 1,
                        "endRowIndex": start_row + i,
                        "startColumnIndex": 13,  # cột N (0-based)
                        "endColumnIndex": 14
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })

        if format_requests:
            batch_request = {"requests": format_requests}
            safe_batch_update(sheets_service, spreadsheet_id, batch_request)
        
        return True
    except Exception as e:
        print(f"❌ batch_format_send_email_sheet error: {e}")
        return True

def get_sheet_data(sheets_service, spreadsheet_id, sheet_name, start_row=3):
    try:
        range_name = f"{sheet_name}!A{start_row}:L"
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        return result.get('values', [])
    except Exception as e:
        print(f"❌ get_sheet_data error: {e}")
        return []

def download_excel_file(drive_service, file_url):
    try:
        if '/d/' in file_url:
            file_id = file_url.split('/d/')[1].split('/')[0]
        else:
            return None
        return drive_service.files().export(
            fileId=file_id,
            mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ).execute()
    except Exception as e:
        print(f"❌ download_excel_file error: {e}")
        return None

def parse_sheet_data_to_email_list(sheet_data):
    email_list = []
    for i, row in enumerate(sheet_data):
        try:
            if len(row) > 11 and str(row[11]).strip().upper() == 'TRUE':
                time_value = row[7] if len(row) > 7 else ""
                formatted_time = format_datetime(time_value)
                email_data = {
                    'row_index': i + 1,
                    'subject': row[2] if len(row) > 2 else "",
                    'recipient': row[4] if len(row) > 4 else "",
                    'cc': row[3] if len(row) > 3 else "",
                    'lh_trip': row[1] if len(row) > 1 else "",
                    'time': formatted_time,
                    'quantity_to': row[8] if len(row) > 8 else "",
                    'quantity_order': row[9] if len(row) > 9 else "",
                    'hub': row[5] if len(row) > 5 else "",
                    'file_link': row[10] if len(row) > 10 else "",
                    'date': row[0] if len(row) > 0 else "",
                    'cot': row[6] if len(row) > 6 else "",
                    'original_row_data': row
                }
                email_list.append(email_data)
        except Exception as e:
            print(f"❌ parse_sheet_data_to_email_list error on row {i+1}: {e}")
    return email_list

def create_message_with_attachment(to, cc, subject, message_text, attachment_data=None, attachment_name=None, in_reply_to=None, references=None):
    if attachment_data:
        message = MIMEMultipart()
        message.attach(MIMEText(message_text, 'plain'))
        attachment = MIMEApplication(attachment_data, _subtype='xlsx')
        attachment.add_header('Content-Disposition', 'attachment', filename=attachment_name)
        message.attach(attachment)
    else:
        message = MIMEText(message_text)
    message['To'] = to
    message['Cc'] = cc
    message['Subject'] = subject
    if in_reply_to:
        message['In-Reply-To'] = in_reply_to
    if references:
        message['References'] = references
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}

def send_message(service, user_id, message, thread_id=None):
    body = {'raw': message['raw']}
    if thread_id:
        body['threadId'] = thread_id
    return service.users().messages().send(userId=user_id, body=body).execute()

def get_header_value(headers, header_name):
    for header in headers:
        if header['name'].lower() == header_name.lower():
            return header['value']
    return None

def search_email_threads_by_subject(service, user_id, subject):
    try:
        query = f'subject:"{subject}"'
        results = service.users().messages().list(userId=user_id, q=query, maxResults=50).execute()
        messages = results.get('messages', [])
        threads = {}
        for msg in messages:
            thread_id = msg['threadId']
            if thread_id not in threads:
                threads[thread_id] = []
            threads[thread_id].append(msg)
        return list(threads.keys())
    except Exception as e:
        print(f"❌ search_email_threads_by_subject error: {e}")
        return []

def get_thread_messages(service, user_id, thread_id):
    try:
        thread = service.users().threads().get(userId=user_id, id=thread_id).execute()
        messages = thread.get('messages', [])
        message_details = []
        for msg in messages:
            msg_detail = service.users().messages().get(userId=user_id, id=msg['id'], format='metadata').execute()
            headers = msg_detail['payload']['headers']
            subject = get_header_value(headers, 'Subject')
            message_id = get_header_value(headers, 'Message-ID')
            message_details.append({
                'id': msg['id'],
                'subject': subject,
                'message_id': message_id,
                'headers': headers
            })
        return message_details
    except Exception as e:
        print(f"❌ get_thread_messages error: {e}")
        return []

def filter_original_messages(messages):
    return [msg for msg in messages if msg['subject'] and not (msg['subject'].startswith("Re:") or "(Failure)" in msg['subject'] or msg['subject'].startswith("Fwd:"))]

def send_email_smart_reply(service, to_email, cc_email, subject, message_text,
                           attachment_data=None, attachment_name=None):
    """
    Trả về:
        sent: dict response của Gmail API
        original_subject: subject của mail gốc trong thread (hoặc subject hiện tại nếu thread mới)
        current_subject: subject đang dùng để gửi (từ sheet)
        mode: "new_thread" | "reply_thread"
    """
    # 1) Tìm thread theo subject
    thread_ids = search_email_threads_by_subject(service, "me", subject)

    # ❌ Không tìm thấy thread nào -> gửi mail mới
    if not thread_ids:
        message = create_message_with_attachment(
            to_email, cc_email, subject, message_text,
            attachment_data, attachment_name
        )
        sent = send_message(service, "me", message)
        # Nếu gửi lỗi, send_message sẽ raise HttpError -> để exception bay ra ngoài
        return sent, subject, subject, "new_thread"

    # ✅ Có thread -> lọc các thread hợp lệ
    valid_threads = []
    for thread_id in thread_ids:
        messages = get_thread_messages(service, "me", thread_id)
        if messages:
            first_message = messages[0]
            if first_message['subject'] and not first_message['subject'].startswith("Re:"):
                valid_threads.append((thread_id, messages))

    # Không có thread hợp lệ (toàn Re:...) -> tạo thread mới
    if not valid_threads:
        message = create_message_with_attachment(
            to_email, cc_email, subject, message_text,
            attachment_data, attachment_name
        )
        sent = send_message(service, "me", message)
        return sent, subject, subject, "new_thread"

    # 👉 Chọn thread hợp lệ mới nhất
    selected_thread_id, thread_messages = valid_threads[0]

    filtered_messages = filter_original_messages(thread_messages)
    # Nếu không lọc được message gốc -> coi như thread mới
    if not filtered_messages:
        message = create_message_with_attachment(
            to_email, cc_email, subject, message_text,
            attachment_data, attachment_name
        )
        sent = send_message(service, "me", message)
        return sent, subject, subject, "new_thread"

    last_message = filtered_messages[-1]
    message_id_header = last_message['message_id']
    references_header = get_header_value(last_message['headers'], 'References')
    if references_header and message_id_header:
        new_references = f"{references_header} {message_id_header}"
    else:
        new_references = message_id_header

    # Tạo message reply + giữ threadId
    message = create_message_with_attachment(
        to_email, cc_email, subject, message_text,
        attachment_data, attachment_name,
        in_reply_to=message_id_header,
        references=new_references
    )
    sent = send_message(service, "me", message, thread_id=selected_thread_id)
    return sent, last_message['subject'], subject, "reply_thread"

def format_datetime(dt_str):
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except:
        try:
            dt = datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")
        except:
            return dt_str

    return dt.strftime("%d/%m/%Y %H:%M:%S")

def process_email_batch(email_data_list, drive_service, sheets_service, gmail_service, spreadsheet_id, send_sheet_name="send_email", output_sheet_name="Output", start_row=3):
    results = []
    rows_to_delete = []
    rows_to_add = []
    status_list = []
    
    for email_data in email_data_list:
        try:
            email_data['time'] = format_datetime(email_data['time'])
            content = f"""Dear Team,\nSOC gửi bàn giao hàng theo thông tin như sau:\nLH_Trip : {email_data['lh_trip']}\nThời gian: {email_data['time']}\nSố lượng TO: {email_data['quantity_to']}\nSố lượng Order: {email_data['quantity_order']}\nChi tiết file đính kèm: """
            
            attachment_data = download_excel_file(drive_service, email_data['file_link']) if email_data['file_link'] else None
            attachment_name = f"{email_data['hub']}.xlsx"
            
            sent, original_subject, current_subject, mode = send_email_smart_reply(
                service=gmail_service,
                to_email=email_data['recipient'],
                cc_email=email_data['cc'],
                subject=email_data['subject'],
                message_text=content,
                attachment_data=attachment_data,
                attachment_name=attachment_name
            )

            # Map mode -> Status hiển thị trong sheet
            if mode == "reply_thread":
                subject_status = "Reply vào luồng mail đã có"
            elif mode == "new_thread":
                subject_status = "Tạo luồng mail mới"
            else:
                # fallback, phòng sau này có mode khác
                subject_status = f"Khác: {mode}"
            
            extended_row = list(email_data['original_row_data']) + [str(original_subject), str(subject_status)]
            rows_to_add.append(extended_row)
            status_list.append(subject_status)
            rows_to_delete.append(email_data['row_index'])
            
            results.append({'success': True})
        except Exception as e:
            print(f"❌ process_email_batch error: {e}")
            results.append({'success': False, 'error': str(e)})
    
    if rows_to_add:
        try:
            current_rows = len(sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"{send_sheet_name}!A:A"
            ).execute().get('values', []))
            start_format_row = current_rows + 1
        except:
            start_format_row = 1
        
        batch_move_to_send_email_sheet(sheets_service, spreadsheet_id, rows_to_add, send_sheet_name)
        batch_format_send_email_sheet(sheets_service, spreadsheet_id, start_format_row, status_list, send_sheet_name)
    
    batch_delete_rows_from_output_sheet(sheets_service, spreadsheet_id, rows_to_delete, start_row, output_sheet_name)
    
    print(f"✅ Processed {len(email_data_list)} emails, deleted {len(rows_to_delete)} rows.")
    return results

def main(user_email: str, spreadsheet_id: str):
    gmail_service, sheets_service, drive_service = get_google_services(user_email)

    OUTPUT_SHEET = "Output"
    SEND_SHEET = "send_email"
    START_ROW = 3

    sheet_data = get_sheet_data(sheets_service, spreadsheet_id, OUTPUT_SHEET, START_ROW)
    if not sheet_data:
        print("⚠️ Không có dữ liệu cần gửi.")
        return

    email_data_list = parse_sheet_data_to_email_list(sheet_data)
    if not email_data_list:
        print("⚠️ Không có dòng nào được đánh dấu gửi.")
        return

    # optional: giới hạn 10 mail (đúng note UI)
    email_data_list = email_data_list[:10]

    process_email_batch(
        email_data_list,
        drive_service,
        sheets_service,
        gmail_service,
        spreadsheet_id=spreadsheet_id,
        send_sheet_name=SEND_SHEET,
        output_sheet_name=OUTPUT_SHEET,
        start_row=START_ROW,
    )

if __name__ == "__main__":
    print("This module is intended to be called from app.py with main(user_email, spreadsheet_id).")