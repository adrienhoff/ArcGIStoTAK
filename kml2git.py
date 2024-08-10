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

OUTPUT_DIR = r"C:\Users\adrie\ArcGIStoTAK"


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
            f"where=source+%3D+%27CAL+FIRE+INTEL+FLIGHT+DATA%27"
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

        description = ET.SubElement(inner_placemark, "description")
        description.text = full_description

            


        # Add Polygon to inner Placemark
        inner_polygon = ET.SubElement(inner_placemark, "Polygon")
        inner_extrude = ET.SubElement(inner_polygon, "extrude")
        inner_extrude.text = "0"  # Set to '0' to disable extrusion
        inner_altitude_mode = ET.SubElement(inner_polygon, "altitudeMode")
        inner_altitude_mode.text = "clampToGround"
        inner_boundary_is = ET.SubElement(inner_polygon, "outerBoundaryIs")
        inner_linear_ring = ET.SubElement(inner_boundary_is, "LinearRing")
        inner_coordinates = ET.SubElement(inner_linear_ring, "coordinates")

        inner_coords = polygon_data["rings"][i]
        transformed_inner_coords = ["{},{},0".format(coord[0], coord[1]) for coord in inner_coords]
        inner_coordinates.text = " ".join(transformed_inner_coords)

        inner_placemarks.append(inner_placemark)

    return [placemark_outer] + inner_placemarks

def create_polygon_style(style_id):
    style = ET.Element("Style", id=style_id)
    line_style = ET.SubElement(style, "LineStyle")
    line_color = ET.SubElement(line_style, "color")
    line_color.text = "ffa9e600"
    line_width = ET.SubElement(line_style, "width")
    line_width.text = "2"

    poly_style = ET.SubElement(style, "PolyStyle")
    poly_fill = ET.SubElement(poly_style, "fill")
    poly_fill.text = "false"
    poly_outline = ET.SubElement(poly_style, "outline")
    poly_outline.text = "true"

    return style

def commit_and_push_to_github(repo_dir, file_name):
    try:
        # Navigate to the local repository directory
        os.chdir(repo_dir)

       # subprocess.run(["git", "pull"], check=True)
        
        # Add the file to the staging area
        subprocess.run(["git", "add", file_name], check=True)
        print(f"Staged {file_name} for commit.")
        
        # Check the status before committing
        subprocess.run(["git", "status"], check=True)
        
        # Commit the changes with a message
        commit_message = f"Add {file_name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result = subprocess.run(["git", "commit", "-m", commit_message], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Git commit error: {result.stderr}")
            return
        print(f"Committed {file_name} to Git.")
        
        # Push the changes to the GitHub repository
        subprocess.run(["git", "push"], check=True)
        
        print(f"Committed and pushed {file_name} to GitHub successfully.")
    
    except subprocess.CalledProcessError as e:
        print(f"Error during Git operations: {e}")



def main():
    while True:
        print("Generating KML file...")

        features = fetch_fire_data()
        if not features:
            print("No features fetched. Waiting for 1 minute before retrying...")
            time.sleep(60)
            continue

        kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        document = ET.SubElement(kml, "Document")
        name = ET.SubElement(document, "name")
        name.text = "Cal_Fire_Intel_Boundary.kmz"
        description = ET.SubElement(document, "description")
        description.text = "Cal_Fire_Intel_Boundary.kmz"

        style_id = "-1073741762"
        style = create_polygon_style(style_id)
        document.append(style)

        for feature in features:
            attributes = feature.get("attributes", {})
            geometry = feature.get("geometry", {})

            source = attributes.get("source", "")
            mission = attributes.get("mission", "")
            incident_name = attributes.get("incident_name", "")
            incident_number = attributes.get("incident_number", "")
            area_acres = attributes.get("area_acres", "")
            Date = format_date(attributes.get("poly_DateCurrent", ""))
            description_text = attributes.get("description", "")
            OID = attributes.get("OBJECTID", "")

            description_data = """<html>
                <body>
                  <table border="1">
                    <tr>
                      <th>Source</th>
                      <th>{}</th>
                    </tr>
                    <tr bgcolor = "#D4E4F3">
                      <td>Mission</td>
                      <td>{}</td>
                    </tr>
                    <tr>
                      <td>Incident Name</td>
                      <td>{}</td>
                    </tr>
                    <tr bgcolor = "#D4E4F3">
                      <td>Incident Number</td>
                      <td>{}</td>
                    </tr>
                    <tr>
                      <td>Area in Acres</td>
                      <td>{}</td>
                    </tr>
                    <tr bgcolor = "#D4E4F3">
                      <td>Description</td>
                      <td>{}</td>
                    </tr>
                    <tr>
                      <td>Date</td>
                      <td>{}</td>
                    </tr>
                    <tr bgcolor = "#D4E4F3">
                      <td>OID</td>
                      <td>{}</td>
                    </tr>
                  </table>
                  <a href="https://www.arcgis.com/apps/mapviewer/index.html?layers=025fb2ea05f14890b2b11573341b5b18" style="font-size: large; font-weight: bold;">Open in Browser</a>
                </body>
            </html>
            """.format(source, mission, incident_name, incident_number, area_acres, description_text, Date, OID)

            placemarks = create_polygon_placemark(attributes, geometry, description_data)
            for placemark in placemarks:
                document.append(placemark)

        kml_path = os.path.join(OUTPUT_DIR, "Cal_Fire_Intel_Boundary.kml")
        tree = ET.ElementTree(kml)
        tree.write(kml_path, encoding="utf-8", xml_declaration=True)

        with open(kml_path, "r") as f:
            kml_content = f.read()
            unescaped_kml_content = unescape(kml_content)

        with open(kml_path, "w") as f:
            f.write(unescaped_kml_content)

        commit_and_push_to_github(OUTPUT_DIR, "Cal_Fire_Intel_Boundary.kml")

        print("KML file generated.")

        print("Restarting the script in 5 minutes...")
        time.sleep(300)

if __name__ == "__main__":
    main()
