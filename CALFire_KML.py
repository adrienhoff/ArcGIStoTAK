import requests
import json
import xml.etree.ElementTree as ET
from arcgis.gis import GIS
import socket
import ssl
import time
import os
from pyproj import Transformer

OUTPUT_DIR = r"G:\\My Drive\\KML"

def fetch_fire_data():
    url = "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/CA_Perimeters_NIFC_FIRIS_public_view/FeatureServer/0/query?where=source+%3D+%27CAL+FIRE+INTEL+FLIGHT+DATA%27&objectIds=&time=&geometry=&geometryType=esriGeometryEnvelope&inSR=&spatialRel=esriSpatialRelIntersects&resultType=none&distance=0.0&units=esriSRUnit_Meter&relationParam=&returnGeodetic=false&outFields=*&returnGeometry=true&returnCentroid=true&returnEnvelope=false&featureEncoding=esriDefault&multipatchOption=xyFootprint&maxAllowableOffset=&geometryPrecision=&outSR=&defaultSR=&datumTransformation=&applyVCSProjection=false&returnIdsOnly=false&returnUniqueIdsOnly=false&returnCountOnly=false&returnExtentOnly=false&returnQueryGeometry=false&returnDistinctValues=false&cacheHint=false&orderByFields=&groupByFieldsForStatistics=&outStatistics=&having=&resultOffset=&resultRecordCount=&returnZ=false&returnM=false&returnExceededLimitFeatures=true&quantizationParameters=&sqlFormat=none&f=json&token="
    response = requests.get(url)
    data = response.json()
    features = data["features"]
    return features

def create_polygon_placemark(attributes, polygon_data, description_data, centroid):
    transformer = Transformer.from_crs("EPSG:4269", "EPSG:4326", always_xy=True)
    
    placemark = ET.Element("Placemark")
    name = ET.SubElement(placemark, "name")
    name.text = attributes.get("incident_name", "")
    visibility = ET.SubElement(placemark, "visibility")
    visibility.text = "true"
    styleurl = ET.SubElement(placemark, "styleUrl")
    styleurl.text = "#-1073741762"
    description = ET.SubElement(placemark, "description")
    description.text = description_data

    # Add LookAt element to center the view on the centroid
    lookat = ET.SubElement(placemark, "Point")
    lon, lat = transformer.transform(centroid["x"], centroid["y"])
    altitudemode = ET.SubElement(lookat, "altitudeMode")
    altitudemode.text = "clampToGround"
    ET.SubElement(lookat, "coordinates").text = "{},{},0".format(lon, lat)
    ET.SubElement(lookat, "altitudeMode").text = "clampToGround"


    multigeom = ET.SubElement(placemark, "MultiGeometry")
    polygon = ET.SubElement(multigeom, "Polygon")
    altitudemode = ET.SubElement(polygon, "altitudeMode")
    altitudemode.text = "clampToGround"
    outer_boundary_is = ET.SubElement(polygon, "outerBoundaryIs")
    altitudemode = ET.SubElement(outer_boundary_is, "altitudeMode")
    altitudemode.text = "clampToGround"

    linear_ring = ET.SubElement(outer_boundary_is, "LinearRing")
    coordinates = ET.SubElement(linear_ring, "coordinates")

    outer_coords = polygon_data["rings"][0]
    transformed_outer_coords = []
    for coord in outer_coords:
        lon, lat = transformer.transform(coord[0], coord[1])
        transformed_outer_coords.append("{},{},0".format(lon, lat))

    coordinates.text = " ".join(transformed_outer_coords)

    for i in range(1, len(polygon_data["rings"])):
        inner_boundary_is = ET.SubElement(polygon, "innerBoundaryIs")
        altitudemode = ET.SubElement(inner_boundary_is, "altitudeMode")
        altitudemode.text = "clampToGround"
        inner_linear_ring = ET.SubElement(inner_boundary_is, "LinearRing")
        inner_coordinates = ET.SubElement(inner_linear_ring, "coordinates")

        inner_coords = polygon_data["rings"][i]
        transformed_inner_coords = []
        for coord in inner_coords:
            lon, lat = transformer.transform(coord[0], coord[1])
            transformed_inner_coords.append("{},{},0".format(lon, lat))

        inner_coordinates.text = " ".join(transformed_inner_coords)

    return placemark

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

def main():
    while True:
        print("Generating KML file...")
        
        features = fetch_fire_data()

        kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        document = ET.SubElement(kml, "Document")
        name = ET.SubElement(document, "name")
        name.text = "Cal_Fire_Intel_Boundary.kmz"
        description = ET.SubElement(document, "description")
        description.text = "Cal_Fire_Intel_Boundary.kmz"

        for feature in features:
            attributes = feature["attributes"]
            geometry = feature["geometry"]
            centroid = feature["centroid"]

            source = attributes.get("source", "")
            mission = attributes.get("mission", "")
            incident_name = attributes.get("incident_name", "")
            incident_number = attributes.get("incident_number", "")
            area_acres = attributes.get("area_acres", "")
            description = attributes.get("description", "")

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
                  </table>
                  <a href="https://www.arcgis.com/apps/mapviewer/index.html?layers=025fb2ea05f14890b2b11573341b5b18" style="font-size: large; font-weight: bold;">Open in Browser</a>
                </body>
            </html>
            """.format(source, mission, incident_name, incident_number, area_acres, description)

            style_id = "-1073741762"
            style = create_polygon_style(style_id)
            document.append(style)
            placemark = create_polygon_placemark(attributes, geometry, description_data, centroid)
            document.append(placemark)

        kml_path = os.path.join(OUTPUT_DIR, "Cal_Fire_Intel_Boundary.kml")
        tree = ET.ElementTree(kml)
        tree.write(kml_path, encoding="utf-8", xml_declaration=True)

        print("Restarting the script in 5 minutes...")
        time.sleep(300)

if __name__ == "__main__":
    main()
