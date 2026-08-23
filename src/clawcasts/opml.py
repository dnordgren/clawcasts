from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom


def build_opml(title: str, outlines: list[tuple[str, str]]) -> bytes:
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(root, "body")
    for text, xml_url in outlines:
        ET.SubElement(body, "outline", text=text, type="rss", xmlUrl=xml_url)
    raw = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(raw)
    return parsed.toprettyxml(indent="  ", encoding="utf-8")
