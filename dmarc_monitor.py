#!/usr/bin/env python3

import argparse
import gzip
import imaplib
import re
import time
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

import defusedxml.ElementTree as ET
from prometheus_client import Counter, Gauge, start_http_server

dmarc_reports_total = Counter(
    'dmarc_reports_total',
    'Total DMARC disposition counts from processed reports',
    ['domain', 'provider', 'disposition']
)
dmarc_last_processed_timestamp_seconds = Gauge(
    'dmarc_last_processed_timestamp_seconds',
    'Unix timestamp of the last processed DMARC report',
    ['domain', 'provider']
)

ARGPARSER = argparse.ArgumentParser(
    description="Fetch, parse, and export Prometheus metrics from DMARC mail."
)
ARGPARSER.add_argument("-c", "--config", type=str, required=True,
                       help="path to TOML configuration file")
ARGS = ARGPARSER.parse_args()

with open(Path(ARGS.config), "rb") as f:
    CONFIG = tomllib.load(f)


def get_email_attachments():
    attachments = []
    try:
        mail = imaplib.IMAP4_SSL(CONFIG["email"]["imap_server"])
        mail.login(CONFIG["email"]["username"], CONFIG["email"]["password"])
        mail.select(CONFIG["email"].get("folder", "INBOX"))

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
                mail.store(num, '+FLAGS', '\\Seen')
        mail.logout()
    except Exception as e:
        print(f"Error retrieving emails: {e}")
    return attachments


def clean_xml(xml_data):
    cleaned = re.sub(r'xmlns="[^"]+"', '', xml_data.replace('\r\n', '').replace('\n', '')).strip()
    try:
        ET.fromstring(cleaned)
        return cleaned
    except Exception:
        print("Invalid XML detected. Skipping.")
        return None


def extract_dmarc_reports():
    xml_reports = []
    for filename, file_data in get_email_attachments():
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
            cleaned = clean_xml(extracted_xml)
            if cleaned:
                xml_reports.append(cleaned)
    return xml_reports


def parse_dmarc_report(xml_data):
    try:
        root = ET.fromstring(xml_data)

        report_metadata = root.find('.//report_metadata')
        org_name = (
            report_metadata.find('org_name').text
            if report_metadata is not None and report_metadata.find('org_name') is not None
            else "unknown"
        )
        domain_el = root.find('.//policy_published/domain')
        domain = domain_el.text if domain_el is not None else "unknown"

        for record in root.findall('.//record'):
            count_el = record.find('./row/count')
            disposition_el = record.find('./row/policy_evaluated/disposition')
            if count_el is None or disposition_el is None:
                continue
            count = int(count_el.text)
            # 'none' = pass, 'quarantine' = soft-fail, 'reject' = hard-fail
            disposition = disposition_el.text or "unknown"
            dmarc_reports_total.labels(
                domain=domain, provider=org_name, disposition=disposition
            ).inc(count)

        dmarc_last_processed_timestamp_seconds.labels(
            domain=domain, provider=org_name
        ).set(time.time())
        print(f"Processed report — domain: {domain}, provider: {org_name}")

    except Exception as e:
        print(f"Error parsing DMARC XML: {e}")


def update_metrics():
    interval = max(CONFIG.get("prometheus", {}).get("interval", 60), 30)
    while True:
        for xml_data in extract_dmarc_reports():
            parse_dmarc_report(xml_data)
        time.sleep(interval)


def main():
    email_cfg = CONFIG.get("email", {})
    missing = [k for k in ("username", "password", "imap_server") if not email_cfg.get(k)]
    if missing:
        raise SystemExit(f"Missing required config keys: {', '.join(f'email.{k}' for k in missing)}")

    port = CONFIG.get("prometheus", {}).get("port", 8000)
    start_http_server(port)
    print(f"Started dmarc_monitor. Prometheus metrics on :{port}")
    update_metrics()


if __name__ == "__main__":
    main()
