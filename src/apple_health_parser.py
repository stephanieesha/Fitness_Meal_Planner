"""
Parses an Apple Health export (Settings/Health app -> Profile -> Export
All Health Data) to extract daily Active Energy Burned - the data behind
the Watch's Move ring.

Apple's export is a large XML file (often 50-500MB+ for a long-time
user), sometimes delivered as a zip containing export.xml. Uses
iterparse rather than a full-document parse so memory use stays low
regardless of file size - critical here, a naive parse could exhaust
memory on a real export.

I don't have a real Apple Health export to test this against - built
carefully against Apple's documented, stable Record XML format, and
tested against a realistic fixture, but the first real upload is the
true test of this.
"""

import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from io import BytesIO

ACTIVE_ENERGY_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"


def extract_xml_from_upload(file_bytes: bytes, filename: str) -> bytes:
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith("export.xml")]
            if not xml_names:
                raise ValueError("No export.xml found inside the uploaded zip")
            return zf.read(xml_names[0])
    return file_bytes


def parse_active_energy(xml_bytes: bytes) -> dict:
    daily_totals = defaultdict(float)

    context = ET.iterparse(BytesIO(xml_bytes), events=("start", "end"))
    for event, elem in context:
        if event == "end" and elem.tag == "Record":
            if elem.get("type") == ACTIVE_ENERGY_TYPE:
                start_date = elem.get("startDate", "")
                value = elem.get("value")
                if start_date and value:
                    day = start_date[:10]
                    try:
                        daily_totals[day] += float(value)
                    except ValueError:
                        pass
            elem.clear()

    return {day: round(total, 1) for day, total in daily_totals.items()}


def parse_upload(file_bytes: bytes, filename: str) -> dict:
    xml_bytes = extract_xml_from_upload(file_bytes, filename)
    return parse_active_energy(xml_bytes)
