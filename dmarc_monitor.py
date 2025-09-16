#!/usr/bin/env python3

import os
import time
import xml.etree.ElementTree as ET
import zipfile
import gzip
import imaplib
import re
from prometheus_client import start_http_server, Gauge
from email import policy
from email.parser import BytesParser
from io import BytesIO

# Read email credentials from environment variables
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
IMAP_SERVER = os.getenv("IMAP_SERVER")

# Define Prometheus metrics with labels (domain, provider, report_id, report_date)
dmarc_passed = Gauge(
    'dmarc_passed_count',
    'Number of emails that passed DMARC',
    ['domain', 'provider', 'report_id', 'report_date']
)
dmarc_failed = Gauge(
    'dmarc_failed_count',
    'Number of emails that failed DMARC',
    ['domain', 'provider', 'report_id', 'report_date']
)
dmarc_last_processed_timestamp_seconds = Gauge(
    'dmarc_last_processed_timestamp_seconds',
    'Timestamp of last processed DMARC report',
    ['domain', 'provider', 'report_id', 'report_date']
)

def get_email_attachments():
    """Connects to an email inbox and retrieves DMARC report attachments."""
    attachments = []
    
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select('inbox')

        # Search for unread emails with attachments
        result, data = mail.search(None, '(UNSEEN)')

        if result == 'OK':
            for num in data[0].split():
                result, msg_data = mail.fetch(num, '(RFC822)')
                if result != 'OK':
                    continue

                msg = BytesParser(policy=policy.default).parsebytes(msg_data[0][1])

                for part in msg.iter_attachments():
                    filename = part.get_filename()
                    if filename and (filename.endswith('.zip') or filename.endswith('.gz')):
                        attachments.append((filename, part.get_payload(decode=True)))

                # Mark email as seen
                mail.store(num, '+FLAGS', '\\Seen')

        mail.logout()

    except Exception as e:
        print(f"Error retrieving emails: {e}")

    return attachments

def clean_xml(xml_data):
    """Strips unwanted characters, removes namespaces, and validates XML format."""
    cleaned_xml = xml_data.replace('\r\n', '').replace('\n', '').strip()
    
    # Remove XML namespace definitions
    cleaned_xml = re.sub(r'xmlns="[^"]+"', '', cleaned_xml)

    # Check if XML is still valid
    try:
        ET.fromstring(cleaned_xml)
        return cleaned_xml  # Return only if valid
    except ET.ParseError:
        print("Invalid XML detected. Skipping.")
        return None  # Skip invalid XMLs

def extract_dmarc_reports():
    """Extracts DMARC XML reports from email attachments."""
    xml_reports = []
    attachments = get_email_attachments()

    for filename, file_data in attachments:
        extracted_xml = None

        if filename.endswith('.zip'):
            with zipfile.ZipFile(BytesIO(file_data), 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.xml'):
                        with zf.open(name) as xml_file:
                            extracted_xml = xml_file.read().decode('utf-8')

        elif filename.endswith('.gz'):
            with gzip.open(BytesIO(file_data), 'rb') as gz_file:
                extracted_xml = gz_file.read().decode('utf-8')

        if extracted_xml:
            cleaned_xml = clean_xml(extracted_xml)
            if cleaned_xml:
                xml_reports.append(cleaned_xml)

    return xml_reports

def parse_dmarc_report(xml_data):
    """Parses a single DMARC XML report and updates Prometheus metrics."""
    try:
        root = ET.fromstring(xml_data)

        # Extract domain, provider, report ID, and date
        report_metadata = root.find('.//report_metadata')
        org_name = report_metadata.find('org_name').text if report_metadata.find('org_name') is not None else "unknown"
        report_id = report_metadata.find('report_id').text if report_metadata.find('report_id') is not None else "unknown"
        date_range = report_metadata.find('date_range')
        report_date = time.strftime('%Y-%m-%d', time.gmtime(int(date_range.find('begin').text))) if date_range is not None else "unknown"
        domain = root.find('.//policy_published/domain').text if root.find('.//policy_published/domain') is not None else "unknown"

        passed_count = 0
        failed_count = 0

        for record in root.findall('.//record'):
            count = int(record.find('./row/count').text)
            disposition = record.find('./row/policy_evaluated/disposition').text

            if disposition in ['none', 'quarantine']:
                passed_count += count
            else:
                failed_count += count

        # Update Prometheus metrics with labels
        dmarc_passed.labels(domain=domain, provider=org_name, report_id=report_id, report_date=report_date).inc(passed_count)
        dmarc_failed.labels(domain=domain, provider=org_name, report_id=report_id, report_date=report_date).inc(failed_count)
        dmarc_last_processed_timestamp_seconds.labels(domain=domain, provider=org_name, report_id=report_id, report_date=report_date).set(time.time())

        print(f"Updated metrics - Domain: {domain}, Provider: {org_name}, Report ID: {report_id}, Date: {report_date}, Passed: {passed_count}, Failed: {failed_count}")

    except ET.ParseError:
        print("Error parsing DMARC XML")

def update_metrics():
    """Periodically fetches new emails, extracts, and updates metrics."""
    while True:
        xml_reports = extract_dmarc_reports()
        if xml_reports:
            for xml_data in xml_reports:
                parse_dmarc_report(xml_data)
        time.sleep(60)

def main():
    """Starts the Prometheus server and monitoring loop."""
    if not EMAIL_USER or not EMAIL_PASS or not IMAP_SERVER:
        print("Error: Missing environment variables. Set EMAIL_USER, EMAIL_PASS, and IMAP_SERVER.")
        return

    # Start Prometheus HTTP server
    start_http_server(8000)
    print("Started dmarc_monitor server")

    # Start monitoring loop
    update_metrics()

if __name__ == "__main__":
    main()
