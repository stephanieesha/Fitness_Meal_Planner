import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from apple_health_parser import extract_xml_from_upload, parse_active_energy, parse_upload

FIXTURE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Stephanie's Apple Watch" unit="kcal" creationDate="2026-01-01 08:00:00 -0500" startDate="2026-01-01 07:55:00 -0500" endDate="2026-01-01 08:00:00 -0500" value="12.5"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Stephanie's Apple Watch" unit="kcal" creationDate="2026-01-01 09:00:00 -0500" startDate="2026-01-01 08:55:00 -0500" endDate="2026-01-01 09:00:00 -0500" value="8.3"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Stephanie's Apple Watch" unit="count" creationDate="2026-01-01 09:00:00 -0500" startDate="2026-01-01 08:55:00 -0500" endDate="2026-01-01 09:00:00 -0500" value="450"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Stephanie's Apple Watch" unit="kcal" creationDate="2026-01-02 07:10:00 -0500" startDate="2026-01-02 07:05:00 -0500" endDate="2026-01-02 07:10:00 -0500" value="20.0"/>
</HealthData>
"""


def test_parses_and_sums_active_energy_per_day():
    result = parse_active_energy(FIXTURE_XML)
    assert result["2026-01-01"] == 20.8
    assert result["2026-01-02"] == 20.0


def test_ignores_unrelated_record_types():
    result = parse_active_energy(FIXTURE_XML)
    assert len(result) == 2


def test_handles_empty_xml_gracefully():
    empty_xml = b'<?xml version="1.0" encoding="UTF-8"?><HealthData></HealthData>'
    result = parse_active_energy(empty_xml)
    assert result == {}


def test_skips_malformed_value_without_crashing():
    xml_with_bad_value = b"""<?xml version="1.0" encoding="UTF-8"?>
    <HealthData>
      <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" startDate="2026-01-01 08:00:00 -0500" value="not-a-number"/>
      <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" startDate="2026-01-01 09:00:00 -0500" value="5.0"/>
    </HealthData>"""
    result = parse_active_energy(xml_with_bad_value)
    assert result["2026-01-01"] == 5.0


def test_extract_xml_from_zip_upload():
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("apple_health_export/export.xml", FIXTURE_XML)
    zip_bytes = zip_buffer.getvalue()

    extracted = extract_xml_from_upload(zip_bytes, "export.zip")
    assert extracted == FIXTURE_XML


def test_extract_xml_passthrough_for_raw_xml_upload():
    extracted = extract_xml_from_upload(FIXTURE_XML, "export.xml")
    assert extracted == FIXTURE_XML


def test_zip_without_export_xml_raises_clear_error():
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("some_other_file.txt", b"not health data")
    zip_bytes = zip_buffer.getvalue()

    with pytest.raises(ValueError):
        extract_xml_from_upload(zip_bytes, "export.zip")


def test_parse_upload_handles_zip_end_to_end():
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("apple_health_export/export.xml", FIXTURE_XML)
    zip_bytes = zip_buffer.getvalue()

    result = parse_upload(zip_bytes, "export.zip")
    assert result["2026-01-01"] == 20.8


def test_parses_a_large_synthetic_file_without_excessive_memory():
    records = []
    for i in range(50000):
        day = f"2026-01-{(i % 28) + 1:02d}"
        records.append(
            f'<Record type="HKQuantityTypeIdentifierActiveEnergyBurned" '
            f'startDate="{day} 08:00:00 -0500" value="1.0"/>'
        )
    large_xml = ('<?xml version="1.0"?><HealthData>' + "".join(records) + "</HealthData>").encode()

    result = parse_active_energy(large_xml)
    assert len(result) == 28
    assert result["2026-01-01"] > 0
