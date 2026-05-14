#!/usr/bin/env python3

import argparse
import gzip
import imaplib
import json
import re
import signal
import sys
import threading
import time
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

import defusedxml.ElementTree as ET
from loguru import logger
from prometheus_client import (
    GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR, REGISTRY,
    Counter, Gauge, start_http_server,
)

REGISTRY.unregister(GC_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)
REGISTRY.unregister(PROCESS_COLLECTOR)

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

log_level = CONFIG.get("log", {}).get("level", "INFO").upper()
logger.remove()
logger.add(sys.stderr, level=log_level,
           format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

# In-memory state: "domain\x00provider\x00disposition" -> cumulative count
_state: dict[str, int] = {}
_stop_event = threading.Event()


def _handle_shutdown(signum, frame):
    logger.info("Shutdown signal received, stopping...")
    _stop_event.set()


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


def _state_path() -> Path:
    return Path(CONFIG.get("state_file", "data/dmarc_state.json"))


def load_state():
    path = _state_path()
    if not path.exists():
        logger.info("No state file found at {}, starting fresh", path)
        return
    try:
        with open(path) as f:
            saved = json.load(f)
        for key, count in saved.items():
            _state[key] = count
            domain, provider, disposition = key.split("\x00", 2)
            dmarc_reports_total.labels(
                domain=domain, provider=provider, disposition=disposition
            ).inc(count)
        logger.info("Resumed state from {} ({} series)", path, len(_state))
    except Exception as e:
        logger.warning("Could not load state file, starting fresh: {}", e)


def _save_state():
    try:
        with open(_state_path(), "w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        logger.error("Could not save state: {}", e)


def check_imap_folders():
    source = CONFIG["email"].get("folder", "INBOX")
    archive = CONFIG["email"].get("archive_folder", "Archive")
    logger.info("Checking IMAP folders: '{}' and '{}'", source, archive)
    try:
        mail = imaplib.IMAP4_SSL(CONFIG["email"]["imap_server"])
        mail.login(CONFIG["email"]["username"], CONFIG["email"]["password"])
        missing = []
        for folder in dict.fromkeys([source, archive]):
            result, _ = mail.select(f'"{folder}"')
            if result != 'OK':
                missing.append(folder)
        mail.logout()
        if missing:
            raise SystemExit(f"IMAP folder(s) not found: {', '.join(missing)}")
        logger.info("IMAP folders OK: '{}' → '{}'", source, archive)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"IMAP connection failed during folder check: {e}")


def _matches_filter(msg):
    conditions = CONFIG["email"].get("filter", [])
    if not conditions:
        return True
    # OR between blocks, AND within each block
    return any(
        all(re.search(pattern, msg.get(header, ""), re.IGNORECASE)
            for header, pattern in condition.items())
        for condition in conditions
    )


def get_email_attachments():
    attachments = []
    archive_folder = CONFIG["email"].get("archive_folder", "Archive")
    folder = CONFIG["email"].get("folder", "INBOX")
    logger.debug("Connecting to {}", CONFIG["email"]["imap_server"])
    try:
        mail = imaplib.IMAP4_SSL(CONFIG["email"]["imap_server"])
        mail.login(CONFIG["email"]["username"], CONFIG["email"]["password"])
        mail.select(folder)

        result, data = mail.search(None, '(UNSEEN)')
        if result == 'OK':
            msg_nums = data[0].split()
            logger.debug("Found {} unseen message(s) in '{}'", len(msg_nums), folder)
            for num in msg_nums:
                result, msg_data = mail.fetch(num, '(RFC822)')
                if result != 'OK':
                    logger.warning("Failed to fetch message #{}", num.decode())
                    continue
                msg = BytesParser(policy=policy.default).parsebytes(msg_data[0][1])
                subject = msg.get("subject", "(no subject)")
                sender = msg.get("from", "(unknown sender)")
                if not _matches_filter(msg):
                    logger.debug("Skipping (filter no match): subject='{}', from='{}'", subject, sender)
                    continue
                logger.debug("Processing: subject='{}', from='{}'", subject, sender)
                found = 0
                for part in msg.iter_attachments():
                    filename = part.get_filename()
                    if filename and (filename.endswith('.zip') or filename.endswith('.gz')):
                        logger.debug("Found attachment: {}", filename)
                        attachments.append((filename, part.get_payload(decode=True)))
                        found += 1
                if found == 0:
                    logger.debug("No DMARC attachments in: subject='{}'", subject)
                mail.store(num, '+FLAGS', '\\Seen')
                mail.copy(num, f'"{archive_folder}"')
                mail.store(num, '+FLAGS', '\\Deleted')
            mail.expunge()
        mail.logout()
    except Exception as e:
        logger.error("Error retrieving emails: {}", e)
    return attachments


def clean_xml(xml_data):
    cleaned = re.sub(r'xmlns="[^"]+"', '', xml_data.replace('\r\n', '').replace('\n', '')).strip()
    try:
        ET.fromstring(cleaned)
        return cleaned
    except Exception:
        logger.warning("Invalid XML detected, skipping")
        return None


def extract_dmarc_reports():
    xml_reports = []
    for filename, file_data in get_email_attachments():
        extracted_xml = None
        if filename.endswith('.zip'):
            with zipfile.ZipFile(BytesIO(file_data), 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.xml'):
                        logger.debug("Extracting XML from zip: {} → {}", filename, name)
                        with zf.open(name) as xml_file:
                            extracted_xml = xml_file.read().decode('utf-8')
        elif filename.endswith('.gz'):
            logger.debug("Extracting XML from gz: {}", filename)
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

        disposition_counts = {}
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
            disposition_counts[disposition] = disposition_counts.get(disposition, 0) + count
            key = f"{domain}\x00{org_name}\x00{disposition}"
            _state[key] = _state.get(key, 0) + count

        dmarc_last_processed_timestamp_seconds.labels(
            domain=domain, provider=org_name
        ).set(time.time())

        _save_state()

        counts_str = ", ".join(f"{d}={n}" for d, n in disposition_counts.items())
        logger.info("Processed report — provider: {}, domain: {}, counts: [{}]",
                    org_name, domain, counts_str)

    except Exception as e:
        logger.error("Error parsing DMARC XML: {}", e)


def update_metrics():
    interval = max(CONFIG.get("prometheus", {}).get("interval", 60), 30)
    while not _stop_event.is_set():
        logger.debug("Checking mailbox for new DMARC reports...")
        reports = extract_dmarc_reports()
        if not reports:
            logger.debug("No new DMARC reports found")
        for xml_data in reports:
            parse_dmarc_report(xml_data)
        logger.debug("Next check in {}s", interval)
        _stop_event.wait(timeout=interval)
    logger.info("Stopped.")


def main():
    logger.info("dmarc_monitor starting up")
    email_cfg = CONFIG.get("email", {})
    missing = [k for k in ("username", "password", "imap_server") if not email_cfg.get(k)]
    if missing:
        raise SystemExit(f"Missing required config keys: {', '.join(f'email.{k}' for k in missing)}")

    load_state()
    check_imap_folders()

    port = CONFIG.get("prometheus", {}).get("port", 8000)
    start_http_server(port)
    logger.info("Prometheus metrics server started on :{}", port)
    update_metrics()


if __name__ == "__main__":
    main()
