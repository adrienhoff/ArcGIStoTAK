import requests
import json
import xml.etree.ElementTree as ET
from arcgis.gis import GIS
from arcgis.geometry import SpatialReference, Geometry
from arcgis.geometry.functions import project
import time
import os
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
from datetime import datetime, timedelta
import subprocess

OUTPUT_DIR = r"/path/to/your/local/repository"

def unescape(s):
    s = s.replace("&lt;", "<")
    s = s.replace("&gt;", ">")
    s = s.replace("&amp;", "&")
    return s

def format_date(timestamp):
    if timestamp:
        try:
            if timestamp < 0:
                return "Invalid Date"
            
            # Convert the timestamp to a UTC datetime object
            utc_time = datetime.utcfromtimestamp(timestamp / 1000)

            # Manually handle daylight saving time for PDT (UTC-7 in summer, UTC-8 otherwise)
            if is_daylight_saving(utc_time):
                pdt_time = utc_time - timedelta(hours=7)
            else:
                pdt_time = utc_time - timedelta(hours=8)

            return pdt_time.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return " "
    return "None"

def is_daylight_saving(dt):
    """Check if the given datetime is in daylight saving time for PDT."""
    year = dt.year
    # Second Sunday in March
    dst_start = datetime(year, 3, 8 + (6 - datetime(year, 3, 1).weekday()) % 7)
    # First Sunday in November
    dst_end = datetime(year, 11, 1 + (6 - datetime(year, 11, 1).weekday()) % 7)
    return dst_start <= dt < dst_end

def fetch_fire_data():
    try:
        # Calculate the date three days ago
        three_days_ago = datetime.now() - timedelta(days=3)
        filter_date = three_days_ago.strftime('%Y-%m-%d')

        # URL with date filter included
        url = (
            f"https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/CA_Perimeters_NIFC_FIRIS_public_view/FeatureServer/0/query?"
            f"where=source+%3D+%27CAL+FIRE+INTEL+FLIGHT+DATA%27+AND+poly_DateCurrent+%3E%3D+date%27{filter_date}%27"
            f"&objectIds=&time=&geometry=&geometryType=esriGeometryEnvelope&inSR=&spatialRel=esriSpatialRelIntersects&resultType=none&distance=0.0"
            f"&units=esriSRUnit_Meter&relationParam=&returnGeodetic=false&outFields=*&returnGeometry=true&returnCentroid=false&returnEnvelope=false"
            f"&featureEncoding=esriDefault&multipatchOption=xyFootprint&maxAllowableOffset=&geometryPrecision=&outSR=&defaultSR=&datumTransformation="
            f"&applyVCSProjection=false&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnExtentOnly=false&returnQueryGeometry=false"
            f"&returnDistinctValues=false&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount="
            f"&returnZ=false&returnM=false&returnExceededLimitFeatures=true&quantizationParameters=&sqlFormat=none&f=json&token="
        )
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
        features = data.get("features", [])
        print(f"Fetched {len(features)} features")

        # Dictionary to store the most recent feature for each name
        most_recent_features = {}

        for feature in features:
            attributes = feature.get("attributes", {})
            name = attributes.get("mission")
            oid = attributes.get("OBJECTID")

            if name is None or oid is None:
                continue

            # Check if this name is already in the dictionary
            if name in most_recent_features:
                # Compare OID to keep the most recent one
                if oid > most_recent_features[name].get("attributes", {}).get("OBJECTID"):
                    most_recent_features[name] = feature
            else:
                most_recent_features[name] = feature

        # Get the list of the most recent features
        filtered_features = list(most_recent_features.values())
        print(f"Filtered to {len(filtered_features)} most recent features")

        return filtered_features

    except requests.RequestException as e:
        print(f"Error fetching fire data: {e}")
        return []

def create_polygon_placemark(attributes, polygon_data, description_data):
    base_id = attributes.get("OBJECTID", str(time.time()))
    
    # Create the main Placemark for the outer polygon
    placemark_outer = ET.Element("Placemark")
    name = ET.SubElement(placemark_outer, "name")
    name.text = attributes.get("incident_name", "")
    visibility = ET.SubElement(placemark_outer, "visibility")
    visibility.text = "true"
    styleurl = ET.SubElement(placemark_outer, "styleUrl")
    styleurl.text = "#-1073741762"
    
    # Define the HTML structure to be prepended
    html_structure = """<![CDATA[<html xmlns:fo="http://www.w3.org/1999/XSL/Format" xmlns:msxsl="urn:schemas-microsoft-com:xslt">
<head><meta http-equiv="content-type" content="text/html; charset=UTF-16"></head>
<body style="margin:0px 0px 0px 0px;overflow:auto;background:#FFFFFF;"><table style="font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-collapse:collapse;padding:3px 3px 3px 3px">
<tr style="text-align:center;font-weight:bold;background:#9CBCE2"><td></td></tr>
<tr><td><table style="font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-spacing:0px; padding:3px 3px 3px 3px]]>">
"""

    # Concatenate the HTML structure with the description data
    full_description = html_structure + description_data

    description = ET.SubElement(placemark_outer, "description")
    description.text = full_description

    # Define the outer Polygon element
    ET.SubElement(placemark_outer, "Polygon")
    extrude = ET.SubElement(placemark_outer, "extrude")
    extrude.text = "0"  # Set to '0' to disable extrusion
    altitude_mode = ET.SubElement(placemark_outer, "altitudeMode")
    altitude_mode.text = "clampToGround"
    outer_boundary_is = ET.SubElement(placemark_outer, "outerBoundaryIs")
    linear_ring = ET.SubElement(outer_boundary_is, "LinearRing")
    coordinates = ET.SubElement(linear_ring, "coordinates")

    if "rings" in polygon_data and len(polygon_data["rings"]) > 0:
        # Handle outer boundary
        outer_coords = polygon_data["rings"][0]
        transformed_outer_coords = ["{},{},0".format(coord[0], coord[1]) for coord in outer_coords]
        coordinates.text = " ".join(transformed_outer_coords)

    # Create separate Placemarks for each inner polygon
    inner_placemarks = []
    for i in range(1, len(polygon_data["rings"])):
        inner_placemark = ET.Element("Placemark")
        inner_placemark.set("id", f"{base_id}_{i}")
        inner_name = ET.SubElement(inner_placemark, "name")
        inner_name.text = f"{attributes.get('incident_name', '')}_ring_{i}"
        inner_visibility = ET.SubElement(inner_placemark, "visibility")
        inner_visibility.text = "true"
        inner_styleurl = ET.SubElement(inner_placemark, "styleUrl")
        inner_styleurl.text = "#-1073741762"

    
        # Define the HTML structure to be prepended
        html_structure = """<![CDATA[<html xmlns:fo="http://www.w3.org/1999/XSL/Format" xmlns:msxsl="urn:schemas-microsoft-com:xslt">
    <head><meta http-equiv="content-type" content="text/html; charset=UTF-16"></head>
    <body style="margin:0px 0px 0px 0px;overflow:auto;background:#FFFFFF;"><table style="font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-collapse:collapse;padding:3px 3px 3px 3px">
    <tr style="text-align:center;font-weight:bold;background:#9CBCE2"><td></td></tr>
    <tr><td><table style="font-family:Arial,Verdana,Times;font-size:12px;text-align:left;width:100%;border-spacing:0px; padding:3px 3px 3px 3px]]>">
    """

        # Concatenate the HTML structure with the description data
        full_description = html_structure + description_data

        inner_description = ET.SubElement(inner_placemark, "description")
        inner_description.text = full_description

        # Define the inner Polygon element
        ET.SubElement(inner_placemark, "Polygon")
        inner_extrude = ET.SubElement(inner_placemark, "extrude")
        inner_extrude.text = "0"  # Set to '0' to disable extrusion
        inner_altitude_mode = ET.SubElement(inner_placemark, "altitudeMode")
        inner_altitude_mode.text = "clampToGround"
        inner_boundary_is = ET.SubElement(inner_placemark, "outerBoundaryIs")
        inner_linear_ring = ET.SubElement(inner_boundary_is, "LinearRing")
        inner_coordinates = ET.SubElement(inner_linear_ring, "coordinates")

        # Handle inner boundary
        inner_coords = polygon_data["rings"][i]
        transformed_inner_coords = ["{},{},0".format(coord[0], coord[1]) for coord in inner_coords]
        inner_coordinates.text = " ".join(transformed_inner_coords)

        inner_placemarks.append(inner_placemark)

    return placemark_outer, inner_placemarks

def write_kml(features, kml_filename):
    kml = ET.Element("kml")
    document = ET.SubElement(kml, "Document")

    # Parse and process the filtered features
    for feature in features:
        attributes = feature.get("attributes", {})
        geometry = feature.get("geometry", {})

        if not geometry:
            continue

        description = f"""<tr><td>Fire Name: {attributes.get('incident_name')}</td></tr>
<tr><td>Date: {format_date(attributes.get('poly_DateCurrent'))}</td></tr>
<tr><td>Fire Number: {attributes.get('fire_number')}</td></tr>
<tr><td>Source: {attributes.get('source')}</td></tr>
<tr><td>Notes: {attributes.get('notes')}</td></tr>
<tr><td>State: {attributes.get('state')}</td></tr>
</table></body></html>]]>"""

        placemark_outer, inner_placemarks = create_polygon_placemark(attributes, geometry, description)

        document.append(placemark_outer)
        for inner_placemark in inner_placemarks:
            document.append(inner_placemark)

    # Convert the ElementTree to a string
    kml_data = ET.tostring(kml, encoding="utf-8", method="xml")
    kml_data = unescape(kml_data.decode("utf-8"))

    with open(kml_filename, "w", encoding="utf-8") as f:
        f.write(kml_data)

    print(f"KML file created at {kml_filename}")

def commit_and_push_to_github(repo_dir, file_name):
    try:
        # Navigate to the local repository directory
        os.chdir(repo_dir)
        
        # Add the file to the staging area
        subprocess.run(["git", "add", file_name], check=True)
        
        # Commit the changes with a message
        commit_message = f"Add {file_name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        
        # Push the changes to the GitHub repository
        subprocess.run(["git", "push"], check=True)
        
        print(f"Committed and pushed {file_name} to GitHub successfully.")
    
    except subprocess.CalledProcessError as e:
        print(f"Error during Git operations: {e}")

def main():
    # Fetch the fire data
    fire_data = fetch_fire_data()

    # Check if fire data was fetched successfully
    if not fire_data:
        print("No fire data to process.")
        return

    # Define the path to save the KML file
    kml_filename = os.path.join(OUTPUT_DIR, "california_fire_data.kml")

    # Write the KML file
    write_kml(fire_data, kml_filename)

    # Commit and push the file to GitHub
    commit_and_push_to_github(OUTPUT_DIR, "california_fire_data.kml")

if __name__ == "__main__":
    main()
