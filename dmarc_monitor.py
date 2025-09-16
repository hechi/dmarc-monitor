#!/usr/bin/env python3

import argparse
import gzip
import imaplib
import re
import time
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

from prometheus_client import start_http_server, Gauge


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

ARGPARSER = argparse.ArgumentParser(
    description="Fetch, parse, and export Prometheus metrics from DMARC mail."
)
ARGPARSER.add_argument("-c", "--config", type=str, required=True,
                       help="load specified configuration file")
ARGS = ARGPARSER.parse_args()

with open(Path(ARGS.config), "rb") as f:
    CONFIG = tomllib.load(f)


def get_email_attachments():
    """Connects to an email inbox and retrieves DMARC report attachments."""
    attachments = []

    try:
        mail = imaplib.IMAP4_SSL(CONFIG["email"]["imap_server"])
        mail.login(CONFIG["email"]["username"], CONFIG["email"]["password"])
        mail.select(CONFIG["email"].get("folder", "INBOX"))

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
    try:
        interval = CONFIG["prometheus"].get("interval", 60)
    except KeyError:
        pass

    if interval < 30:
        print("Warning: Configured interval too low; Setting minimum 30 seconds")
        interval = 30
    while True:
        xml_reports = extract_dmarc_reports()
        if xml_reports:
            for xml_data in xml_reports:
                parse_dmarc_report(xml_data)

        time.sleep(interval)


def main():
    """Starts the Prometheus server and monitoring loop."""

    try:
        assert CONFIG["email"]["username"]
        assert CONFIG["email"]["password"]
        assert CONFIG["email"]["imap_server"]
    except KeyError as err:
        raise KeyError("Invalid config file. Refer to the example file.") from err

    # Start Prometheus HTTP server
    try:
        prom_port = CONFIG["prometheus"].get("port", 8000)
    except KeyError:
        pass
    start_http_server(prom_port)
    print(f"Started dmarc_monitor server. Listening on :{prom_port}...")

    # Start monitoring loop
    update_metrics()


if __name__ == "__main__":
    main()
