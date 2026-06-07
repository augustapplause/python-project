import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import ArcGIS
from shapely.geometry import Point
import unicodedata
import requests
import io

# Page configuration
st.set_page_config(layout="wide")
st.title("Canadian Census by DA")

# Constants
metric_labels = {
    'Pop_Total': 'Total Population', 'Age_0_4': 'Children (Age 0-4)', 'Age_5_9': 'Children (Age 5-9)',
    'Pop_Seniors_65_Plus': 'Seniors (Age 65+)', 'Daily_Diff_Often': 'Daily Difficulties (Often)',
    'Daily_Diff_Sometimes': 'Daily Difficulties (Sometimes)', 'One_Person_Households': 'One-Person Households',
    'Median_Household_Income': 'Median Household Income ($)', 'Low_Income_Prevalence_Pct': 'Low Income Prevalence (%)',
    'Commute_Transit_Walk_Bike': 'Sustainable Commuters (Transit/Walk/Bike)'
}

PROVINCE_ROUTER = {
    'ontario': '35', 'quebec': '24', 'british columbia': '59', 'alberta': '48', 
    'manitoba': '46', 'saskatchewan': '47', 'nova scotia': '12', 'new brunswick': '13', 
    'newfoundland and labrador': '10', 'prince edward island': '11', 'yukon': '60', 
    'northwest territories': '61', 'nunavut': '62'
}

def strip_accents(text):
    if not text: return ""
    normalized = unicodedata.normalize('NFD', text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != 'Mn').lower().strip()

@st.cache_data
def load_provincial_sharded_data(province_name):
    prov_id = PROVINCE_ROUTER.get(strip_accents(province_name))
    if not prov_id:
        return None
    
    # URL construction
    base_url = "https://github.com/augustapplause/python-project/releases/download/v1.0/"
    file_url = f"{base_url}da_province_{prov_id}.geojson"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(file_url, headers=headers, timeout=10)
        if response.status_code == 200:
            gdf = gpd.read_file(io.BytesIO(response.content))
            if gdf.crs != "EPSG:4326": gdf = gdf.to_crs(epsg=4326)
            _ = gdf.sindex
            return gdf
        else:
            st.error(f"Failed to fetch {file_url}. Status Code: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Error accessing {file_url}: {e}")
        return None

# Sidebar UI
st.sidebar.header("Inputs & Outputs")
address_input = st.sidebar.text_input("Centre on Address or Postal Code:", "50 Victoria St, Gatineau, Quebec")
# radius_km = st.sidebar.slider("Radius (km):", 1, 50, 1)
radius_km = st.sidebar.slider("Radius (km):", 0.5, 10.0, 1.0, step=0.5)

selected_metric = st.sidebar.selectbox("Tooltip Metric:", list(metric_labels.keys()), format_func=lambda x: metric_labels[x])

# Geocoding and Mapping
geolocator = ArcGIS(user_agent="can_da_census_v15")
if address_input:
    location = geolocator.geocode(f"{address_input.strip()}, Canada")
    if location:
        center_pt = Point(location.longitude, location.latitude)
        matched_province = next((p for p in PROVINCE_ROUTER if p in strip_accents(location.address.lower())), None)
        base_da_gdf = load_provincial_sharded_data(matched_province)
        
        if base_da_gdf is not None:
            buffer_geom = gpd.GeoSeries([center_pt], crs="EPSG:4326").to_crs(epsg=3347).buffer(radius_km * 1000).to_crs(epsg=4326).iloc[0]
            possible_matches_index = base_da_gdf.sindex.query(buffer_geom, predicate="intersects")
            intersecting_das = base_da_gdf.iloc[possible_matches_index].copy()
            intersecting_das = intersecting_das[intersecting_das.geometry.intersects(buffer_geom)]
            
            subject_da_id = base_da_gdf[base_da_gdf.contains(center_pt)].iloc[0]['DAUID'] if not base_da_gdf[base_da_gdf.contains(center_pt)].empty else None

            st.sidebar.metric("DAs Identified", len(intersecting_das))
            st.sidebar.metric(f"Total of {metric_labels[selected_metric]}", f"{int(intersecting_das[selected_metric].sum()):,}")
            st.sidebar.metric("Seniors 65+", f"{int(intersecting_das['Pop_Seniors_65_Plus'].sum()):,}")

            m = folium.Map(location=[location.latitude, location.longitude], zoom_start=13)
            folium.Circle([location.latitude, location.longitude], radius=radius_km*1000, color='red', fill=False).add_to(m)
            folium.Marker([location.latitude, location.longitude], icon=folium.Icon(color="red", icon="home")).add_to(m)
            #folium.GeoJson(intersecting_das, style_function=lambda x: {'fillColor': '#2980b9' if str(x['properties']['DAUID']) != str(subject_da_id) else '#e74c3c'},
            #                tooltip=folium.GeoJsonTooltip(fields=['DAUID', selected_metric], aliases=['DA:', f'{metric_labels[selected_metric]}:'])).add_to(m)
            folium.GeoJson(intersecting_das,style_function=lambda x: {'fillColor': '#2980b9' if str(x['properties']['DAUID']) != str(subject_da_id) else '#e74c3c'},
    tooltip=folium.GeoJsonTooltip(fields=['DAUID', selected_metric], aliases=['DA:', f'{metric_labels[selected_metric]}:']), popup=None,
    bubbling_mouse_events=False).add_to(m)
          
            st_folium(m, width="100%", height=400)

            st.subheader("Mapped Dissemination Areas - 2021 Census (selected)")
            df = intersecting_das.copy()
            for col in metric_labels.keys():
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            df['DA Code'] = df['DAUID'].astype(str)
            totals = df[list(metric_labels.keys())].sum()
            totals_df = pd.DataFrame([totals], index=['GRAND TOTAL'])
            totals_df['DA Code'] = 'GRAND TOTAL'
            final_df = pd.concat([df[['DA Code'] + list(metric_labels.keys())], totals_df])

            def highlight_row(row):
                return ['font-weight: bold'] * len(row) if row['DA Code'] == str(subject_da_id) else [''] * len(row)
            st.dataframe(final_df.style.apply(highlight_row, axis=1), use_container_width=True)
    else:
        st.warning("Address not found. Please try a different location.")