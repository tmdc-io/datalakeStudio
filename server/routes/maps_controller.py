from fastapi import FastAPI
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import geopandas as gpd
import h3
from shapely.geometry import Polygon
from shapely import wkt
from geojson import Feature, FeatureCollection
import plotly.express as px
from services import databaseService
from fastapi import Request

router = APIRouter(prefix="/maps")

############################################################################################################

def add_geometry(row):
    points = h3.h3_to_geo_boundary(row['h3_cell'], True)
    return Polygon(points)

def geo_to_h3(row, H3_res):
    return h3.geo_to_h3(lat=row.LATDD83, lng=row.LONGDD83, resolution=H3_res)

@router.get("/", response_class=HTMLResponse)
async def create_map(table: str, level: int = 5):
    df = databaseService.runQuery(f"""
    SELECT h3_cell, h3_cell_to_boundary_wkt(h3_cell) geom, count(*) as count,
     avg(anyoConst) as aggField, FROM
    (SELECT *,h3_latlng_to_cell(latitud, longitud, {level}) as h3_cell FROM {table}) as subq1
    GROUP BY h3_cell
    ORDER BY count DESC
    """)

    try:
        features = []
        for index, row in df.iterrows():
            geom = wkt.loads(row['geom'])  # Convierte WKT a un objeto de geometría usando wkt.loads
            feature = Feature(geometry=geom, properties={"aggField": row['aggField'], "h3_cell": row['h3_cell']})
            features.append(feature)
        geojson_obj = FeatureCollection(features)

        fig = px.choropleth_mapbox(
            df,
            geojson=geojson_obj,
            locations='h3_cell',
            featureidkey="properties.h3_cell",  # Especificar la clave para el GeoJSON
            color='aggField',
            color_continuous_scale="Viridis",
            range_color=(df['aggField'].min(), df['aggField'].max()),
            mapbox_style='carto-positron',
            zoom=5,
            center={"lat": 40.624032273164794, "lon": -3.993888283105448},
            opacity=0.7,
            labels={'count': '# cantidad de registros'}
        )
        fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})

        # Generar el HTML y agregar el JavaScript necesario
        plot_html = fig.to_html(full_html=False)
        html_content = f"""
        <html>
        <head>
            <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        </head>
        <body>
            {plot_html}
            <script>
                var plotElement = document.getElementsByClassName('plotly-graph-div')[0];
                plotElement.on('plotly_relayout', function(eventdata) {{
                    console.log('Zoom or pan detected!', eventdata);
                    // Aquí puedes enviar los datos al servidor para recalcular
                    // Por ejemplo, usando fetch para hacer una llamada a la API
                    fetch('/maps/update', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify(eventdata)
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        // Aquí puedes actualizar el gráfico con los nuevos datos
                        Plotly.react(plotElement, data);
                    }});
                }});
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    except Exception as e:
        print("Error: " + str(e))
        return "Error creating map"


@router.post("/update", response_class=HTMLResponse)
async def update_map(request: Request):
    eventdata = await request.json()

    # Extrae la nueva región de visualización del eventdata
    new_center = eventdata.get('mapbox.center')
    new_zoom = eventdata.get('mapbox.zoom')

    derived = eventdata['mapbox._derived']
    minLat = derived['coordinates'][2][1] - 0.05
    maxLat = derived['coordinates'][0][1] + 0.05
    maxLon = derived['coordinates'][1][0] + 0.05
    minLon = derived['coordinates'][0][0] - 0.05

    # Aquí debes recalcular los datos según la nueva región de visualización
    # Este es un ejemplo básico; ajusta la lógica según tus necesidades
    lat, lon = new_center['lat'], new_center['lon']
    zoom = new_zoom

    # Usa las coordenadas y zoom para filtrar o recalcular los datos
    # Esto es solo un ejemplo; necesitas definir cómo calcular los nuevos datos
    query= f"""
    SELECT h3_cell, h3_cell_to_boundary_wkt(h3_cell) geom, count(*) as count,
     avg(anyoConst) as aggField FROM
    (
    SELECT *, h3_latlng_to_cell(latitud, longitud, 10) as h3_cell FROM home
    WHERE latitud >= {minLat} AND latitud <= {maxLat} AND longitud >= {minLon} AND longitud <= {maxLon}
    ) as subq1
    GROUP BY h3_cell
    ORDER BY count DESC
    """
    print("Query: " + query)
    df = databaseService.runQuery(query)


    features = []
    for index, row in df.iterrows():
        geom = wkt.loads(row['geom'])
        feature = Feature(geometry=geom, properties={"aggField": row['aggField'], "h3_cell": row['h3_cell']})
        features.append(feature)
    geojson_obj = FeatureCollection(features)

    minimumValueGreaterThanZero = df['aggField'].min() if df['aggField'].min() > 0 else 0.1

    fig = px.choropleth_mapbox(
        df,
        geojson=geojson_obj,
        locations='h3_cell',
        featureidkey="properties.h3_cell",
        color='aggField',
        color_continuous_scale="Viridis",
        range_color=(df['aggField'].min(), df['aggField'].max()),
        mapbox_style='carto-positron',
        zoom=zoom,
        center={"lat": lat, "lon": lon},
        opacity=0.7,
        labels={'aggField': '# aggField'}
    )
    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})

    return fig.to_json()
