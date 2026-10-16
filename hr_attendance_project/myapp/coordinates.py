import math

def meters_to_lat_lon_offset(meters, latitude):
    lat_offset = meters / 111_000
    lon_offset = meters / (111_000 * math.cos(math.radians(latitude)))
    return lat_offset, lon_offset

def generate_bounding_box(center_lat, center_lon, size_meters=300):
    half_size = size_meters / 2
    lat_offset, lon_offset = meters_to_lat_lon_offset(half_size, center_lat)
    return {
        "lat_min": center_lat - lat_offset,
        "lat_max": center_lat + lat_offset,
        "lon_min": center_lon - lon_offset,
        "lon_max": center_lon + lon_offset,
    }