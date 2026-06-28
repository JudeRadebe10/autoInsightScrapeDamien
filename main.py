from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from database import get_database_connection
from typing import Optional
import numpy as np
import pandas as pd
import traceback
import os

# app setup:
app = FastAPI(
    title="AutoInsight ZA API",
    description="API for South African car market analytics, powered by real listing data.",
    version="2.0.0"
)
# Cors middleware. Frontend to backend connection- AutoInsight.netlifyapp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



# DB helper:
def open_cursor(connection):
    return connection.cursor(dictionary=True)


# root endpoint:
@app.get("/")
def root():
    return {
        "message": "Welcome to AutoInsight ZA API",
        "version": "2.0.0",
        "docs": "/docs"
    }


# section 1: homepage endpoints:

@app.get("/api/homepage/stats")
def homepage_stats():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section:
        cursor.execute("""
            SELECT
                COUNT(*)             AS total_listings,
                AVG(price)           AS avg_price,
                MIN(price)           AS min_price,
                MAX(price)           AS max_price,
                COUNT(DISTINCT make) AS total_makes,
                SUM(price)           AS total_market_value
            FROM vehicles
            WHERE price IS NOT NULL
        """)
        stats = cursor.fetchone()

        cursor.execute("""
            SELECT COUNT(*) AS new_this_week
            FROM vehicles
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        weekly = cursor.fetchone()

        cursor.execute("""
            SELECT price FROM vehicles WHERE price IS NOT NULL ORDER BY price
        """)
        all_prices   = [float(r["price"]) for r in cursor.fetchall()]
        median_price = all_prices[len(all_prices) // 2] if all_prices else 0

        cursor.close()
        connection.close()

        total_mv = float(stats["total_market_value"]) if stats["total_market_value"] else 0
        if total_mv >= 1_000_000_000:
            mv_label = f"R{total_mv / 1_000_000_000:.1f}B+"
        elif total_mv >= 1_000_000:
            mv_label = f"R{total_mv / 1_000_000:.0f}M+"
        else:
            mv_label = f"R{total_mv:,.0f}"

        return {
            "total_listings":           stats["total_listings"],
            "avg_price":                round(float(stats["avg_price"]), 2) if stats["avg_price"] else 0,
            "median_price":             round(median_price, 2),
            "min_price":                float(stats["min_price"]) if stats["min_price"] else 0,
            "max_price":                float(stats["max_price"]) if stats["max_price"] else 0,
            "total_makes":              stats["total_makes"],
            "new_this_week":            weekly["new_this_week"],
            "total_market_value":       total_mv,
            "total_market_value_label": mv_label
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/homepage/popular-brands")
def homepage_popular_brands(province: str = None, days: int = None):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        where_parts = ["v.make IS NOT NULL"]
        params      = []
        join_sql    = ""

        if province:
            join_sql = "JOIN sellers s ON v.vehicle_id = s.vehicle_id"
            where_parts.append("s.province = %s")
            params.append(province)
        if days:
            where_parts.append("v.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)")
            params.append(days)

        # sql query section:
        cursor.execute(f"""
            SELECT v.make,
                   COUNT(DISTINCT v.vehicle_id) AS count,
                   AVG(v.price) AS avg_price
            FROM vehicles v
            {join_sql}
            WHERE {" AND ".join(where_parts)}
            GROUP BY v.make
            ORDER BY count DESC
            LIMIT 6
        """, params)
        brands = cursor.fetchall()
        cursor.close()
        connection.close()

        for b in brands:
            b["avg_price"] = round(float(b["avg_price"]), 2) if b["avg_price"] else 0
        return {"brands": brands}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/homepage/featured-vehicles")
def homepage_featured_vehicles():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section:
        cursor.execute("""
            SELECT
                v.vehicle_id, v.make, v.model, v.variant, v.year,
                v.price, v.monthly_price, v.mileage, v.fuel_type,
                v.transmission, v.body_type, v.colour,
                s.seller_name, s.province, s.seller_rating, s.agent_nada_member,
                vi.main_image,
                ml.deal_label, ml.deal_pct, ml.predicted_price
            FROM vehicles v
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            LEFT JOIN (
                SELECT vehicle_id, ANY_VALUE(COALESCE(main_image, image_url)) AS main_image
                FROM vehicle_images
                WHERE is_primary = 1
                GROUP BY vehicle_id
            ) vi ON v.vehicle_id = vi.vehicle_id
            LEFT JOIN ml_fair_value_scores ml ON v.vehicle_id = ml.vehicle_id
            ORDER BY v.created_at DESC
            LIMIT 6
        """)
        vehicles = cursor.fetchall()
        cursor.close()
        connection.close()

        for v in vehicles:
            v["price"]           = float(v["price"])           if v["price"]           else None
            v["monthly_price"]   = float(v["monthly_price"])   if v["monthly_price"]   else None
            v["seller_rating"]   = float(v["seller_rating"])   if v["seller_rating"]   else None
            v["deal_pct"]        = float(v["deal_pct"])        if v["deal_pct"]        is not None else None
            v["predicted_price"] = int(v["predicted_price"])   if v["predicted_price"] is not None else None
        return {"vehicles": vehicles}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quick-search")
def quick_search(q: str = Query(..., description="Partial make or model name")):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor      = open_cursor(connection)
        search_term = f"%{q}%"

        # sql query section:
        cursor.execute("""
            SELECT DISTINCT make, model
            FROM vehicles
            WHERE (make LIKE %s OR model LIKE %s)
              AND make IS NOT NULL AND model IS NOT NULL
            ORDER BY make, model
            LIMIT 10
        """, (search_term, search_term))
        results = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"suggestions": results}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# section 2: vehicle listing endpoints:

@app.get("/api/vehicles")
def get_vehicles(page: int = 1, limit: int = 24):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        offset = (page - 1) * limit

        # sql query section:
        cursor.execute("""
            SELECT
                v.vehicle_id, v.make, v.model, v.variant, v.year,
                v.price, v.monthly_price, v.mileage, v.fuel_type,
                v.transmission, v.body_type, v.colour, v.`condition`, v.website_url,
                s.seller_name, s.province, s.seller_rating,
                vi.main_image,
                ml.deal_label, ml.deal_pct, ml.predicted_price
            FROM vehicles v
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            LEFT JOIN (
                SELECT vehicle_id, ANY_VALUE(COALESCE(main_image, image_url)) AS main_image
                FROM vehicle_images
                WHERE is_primary = 1
                GROUP BY vehicle_id
            ) vi ON v.vehicle_id = vi.vehicle_id
            LEFT JOIN ml_fair_value_scores ml ON v.vehicle_id = ml.vehicle_id
            ORDER BY v.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        vehicles = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) AS total FROM vehicles")
        total = cursor.fetchone()["total"]
        cursor.close()
        connection.close()

        for v in vehicles:
            v["price"]           = float(v["price"])           if v["price"]           else None
            v["monthly_price"]   = float(v["monthly_price"])   if v["monthly_price"]   else None
            v["deal_pct"]        = float(v["deal_pct"])        if v["deal_pct"]        is not None else None
            v["predicted_price"] = int(v["predicted_price"])   if v["predicted_price"] is not None else None

        return {
            "vehicles":    vehicles,
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": (total + limit - 1) // limit
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vehicles/search")
def search_vehicles(
    q:            Optional[str] = None,
    make:         Optional[str] = None,
    model:        Optional[str] = None,
    min_price:    Optional[int] = None,
    max_price:    Optional[int] = None,
    min_year:     Optional[int] = None,
    max_year:     Optional[int] = None,
    transmission: Optional[str] = None,
    fuel_type:    Optional[str] = None,
    body_type:    Optional[str] = None,
    province:     Optional[str] = None,
    seller_type:  Optional[str] = None,
    deal_label:   Optional[str] = None,
    sort:         Optional[str] = "newest",
    nada_only:    bool = False,
    page:         int  = 1,
    limit:        int  = 24
):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        where  = " WHERE 1=1"
        params = []

        if q and q.strip():
            term = f"%{q.strip()}%"
            where += " AND (v.make LIKE %s OR v.model LIKE %s OR v.variant LIKE %s)"
            params.extend([term, term, term])

        if make:
            makes = [m.strip() for m in make.split(",") if m.strip()]
            if makes:
                ph = ",".join(["%s"] * len(makes))
                where += f" AND v.make IN ({ph})"
                params.extend(makes)

        if model and model.strip():
            where += " AND v.model = %s"
            params.append(model.strip())

        if min_price is not None:
            where += " AND v.price >= %s";  params.append(min_price)
        if max_price is not None:
            where += " AND v.price <= %s";  params.append(max_price)
        if min_year is not None:
            where += " AND v.year >= %s";   params.append(min_year)
        if max_year is not None:
            where += " AND v.year <= %s";   params.append(max_year)

        if transmission:
            trans = [t.strip() for t in transmission.split(",") if t.strip()]
            if trans:
                ph = ",".join(["%s"] * len(trans))
                where += f" AND v.transmission IN ({ph})"
                params.extend(trans)

        if fuel_type:
            fuels = [f.strip() for f in fuel_type.split(",") if f.strip()]
            if fuels:
                ph = ",".join(["%s"] * len(fuels))
                where += f" AND v.fuel_type IN ({ph})"
                params.extend(fuels)

        if body_type and body_type.strip():
            where += " AND v.body_type = %s"
            params.append(body_type.strip())

        if province:
            provs = [p.strip() for p in province.split(",") if p.strip()]
            if provs:
                ph = ",".join(["%s"] * len(provs))
                where += f" AND s.province IN ({ph})"
                params.extend(provs)

        # deal_label filter - Underpriced / Fair Value / Overpriced:
        if deal_label and deal_label.strip():
            where += " AND ml.deal_label = %s"
            params.append(deal_label.strip())

        need_vd_join = False
        if seller_type:
            types = [t.strip().lower() for t in seller_type.split(",") if t.strip()]
            type_conditions = []
            if any("dealer" in t or "agent" in t for t in types):
                type_conditions.append("(LOWER(vd.seller_type) LIKE %s OR LOWER(vd.seller_type) LIKE %s)")
                params.extend(["%dealer%", "%agent%"])
            if any("private" in t for t in types):
                type_conditions.append("LOWER(vd.seller_type) LIKE %s")
                params.append("%private%")
            if type_conditions:
                where += " AND (" + " OR ".join(type_conditions) + ")"
                need_vd_join = True

        if nada_only:
            where += " AND s.agent_nada_member = 1"

        vd_join = "LEFT JOIN vehicle_details vd ON v.vehicle_id = vd.vehicle_id" if need_vd_join else ""

        # sql query section - count:
        cursor.execute(f"""
            SELECT COUNT(DISTINCT v.vehicle_id) AS total
            FROM vehicles v
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            LEFT JOIN ml_fair_value_scores ml ON v.vehicle_id = ml.vehicle_id
            {vd_join}
            {where}
        """, params)
        total = cursor.fetchone()["total"]

        sort_map = {
            "newest":     "v.created_at DESC",
            "price_asc":  "v.price ASC",
            "price_desc": "v.price DESC",
            "mileage_asc": "v.mileage ASC",
            "best_deals": "ml.deal_pct DESC",
        }
        order_clause = sort_map.get(sort, "v.created_at DESC")
        offset = (page - 1) * limit

        # sql query section - main select with ML scores joined:
        cursor.execute(f"""
            SELECT
                v.vehicle_id, v.make, v.model, v.variant, v.year,
                v.price, v.monthly_price, v.mileage, v.fuel_type,
                v.transmission, v.body_type, v.colour,
                v.website_url,
                s.seller_name, s.province,
                s.seller_rating, s.agent_nada_member,
                vi.main_image,
                ml.deal_label, ml.deal_pct, ml.predicted_price, ml.confidence_pct
            FROM vehicles v
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            {vd_join}
            LEFT JOIN (
                SELECT vehicle_id, ANY_VALUE(COALESCE(main_image, image_url)) AS main_image
                FROM vehicle_images
                WHERE is_primary = 1
                GROUP BY vehicle_id
            ) vi ON v.vehicle_id = vi.vehicle_id
            LEFT JOIN ml_fair_value_scores ml ON v.vehicle_id = ml.vehicle_id
            {where}
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        vehicles = cursor.fetchall()
        cursor.close()
        connection.close()

        for v in vehicles:
            v["price"]           = float(v["price"])           if v["price"]           else None
            v["monthly_price"]   = float(v["monthly_price"])   if v["monthly_price"]   else None
            v["seller_rating"]   = float(v["seller_rating"])   if v["seller_rating"]   else None
            v["deal_pct"]        = float(v["deal_pct"])        if v["deal_pct"]        is not None else None
            v["predicted_price"] = int(v["predicted_price"])   if v["predicted_price"] is not None else None
            v["confidence_pct"]  = float(v["confidence_pct"])  if v["confidence_pct"]  is not None else None

        return {
            "vehicles":    vehicles,
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": (total + limit - 1) // limit,
            "filters_applied": {
                "q": q, "make": make, "model": model,
                "min_price": min_price, "max_price": max_price,
                "min_year": min_year, "max_year": max_year,
                "transmission": transmission, "fuel_type": fuel_type,
                "body_type": body_type, "province": province,
                "seller_type": seller_type, "deal_label": deal_label, "sort": sort
            }
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vehicles/{vehicle_id}")
def get_vehicle_detail(vehicle_id: int):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section - vehicle + specs + seller + ML score:
        cursor.execute("""
            SELECT
                v.*,
                vd.engine_size, vd.engine_power_kw, vd.engine_power_rpm,
                vd.engine_torque_nm, vd.engine_torque_rpm, vd.engine_cylinders,
                vd.engine_charger, vd.transmission_type, vd.transmission_gears,
                vd.driven_wheels, vd.top_speed_kmh, vd.acceleration_0_100,
                vd.fuel_consumption_avg, vd.fuel_range_km, vd.fuel_tank_capacity_litres,
                vd.co2_emissions_combined, vd.length_mm, vd.width_mm, vd.height_mm,
                vd.wheelbase_mm, vd.ground_clearance_mm, vd.body_shape, vd.doors,
                vd.seats, vd.kerb_weight_kg, vd.load_volume_litres, vd.airbag_quantity,
                vd.seller_type, vd.sold, vd.roadworthy, vd.date_listed,
                s.seller_name, s.seller_rating, s.seller_rating_count,
                s.agent_locality, s.province, s.agent_nada_member,
                s.agent_coords_lat, s.agent_coords_lng,
                ml.predicted_price, ml.deal_gap, ml.deal_pct,
                ml.deal_label, ml.confidence_pct, ml.scored_at
            FROM vehicles v
            LEFT JOIN vehicle_details vd        ON v.vehicle_id = vd.vehicle_id
            LEFT JOIN sellers s                 ON v.vehicle_id = s.vehicle_id
            LEFT JOIN ml_fair_value_scores ml   ON v.vehicle_id = ml.vehicle_id
            WHERE v.vehicle_id = %s
        """, (vehicle_id,))
        vehicle = cursor.fetchone()

        if not vehicle:
            cursor.close()
            connection.close()
            raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")

        # sql query section - images:
        cursor.execute("""
            SELECT image_url, is_primary, sort_order
            FROM vehicle_images
            WHERE vehicle_id = %s
            ORDER BY sort_order ASC
        """, (vehicle_id,))
        images = cursor.fetchall()
        cursor.close()
        connection.close()

        for field in ["price", "monthly_price", "acceleration_0_100",
                      "fuel_consumption_avg", "fuel_tank_capacity_litres",
                      "seller_rating", "agent_coords_lat", "agent_coords_lng"]:
            if vehicle.get(field) is not None:
                vehicle[field] = float(vehicle[field])

        for field in ["deal_pct", "confidence_pct"]:
            if vehicle.get(field) is not None:
                vehicle[field] = float(vehicle[field])

        if vehicle.get("predicted_price") is not None:
            vehicle["predicted_price"] = int(vehicle["predicted_price"])
        if vehicle.get("deal_gap") is not None:
            vehicle["deal_gap"] = int(vehicle["deal_gap"])
        if vehicle.get("scored_at") is not None:
            vehicle["scored_at"] = str(vehicle["scored_at"])

        vehicle["images"] = images
        return vehicle

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# section 3: filter dropdown endpoints:

@app.get("/api/filters/makes")
def filter_makes():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT make, COUNT(*) AS count
            FROM vehicles
            WHERE make IS NOT NULL
            GROUP BY make
            ORDER BY make ASC
        """)
        makes = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"makes": makes}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters/models/{make}")
def filter_models(make: str):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT model, COUNT(*) AS count
            FROM vehicles
            WHERE make = %s AND model IS NOT NULL
            GROUP BY model
            ORDER BY model ASC
        """, (make,))
        models = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"make": make, "models": models}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters/years")
def filter_years():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT MIN(year) AS min_year, MAX(year) AS max_year
            FROM vehicles WHERE year IS NOT NULL
        """)
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters/provinces")
def filter_provinces():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT province, COUNT(*) AS count
            FROM sellers
            WHERE province IS NOT NULL
            GROUP BY province
            ORDER BY count DESC
        """)
        provinces = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"provinces": provinces}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters/body-types")
def filter_body_types():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT body_type, COUNT(*) AS count
            FROM vehicles
            WHERE body_type IS NOT NULL
            GROUP BY body_type
            ORDER BY count DESC
        """)
        body_types = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"body_types": body_types}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filters/fuel-types")
def filter_fuel_types():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT fuel_type, COUNT(*) AS count
            FROM vehicles
            WHERE fuel_type IS NOT NULL
            GROUP BY fuel_type
            ORDER BY count DESC
        """)
        fuel_types = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"fuel_types": fuel_types}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# section 4: price estimator endpoints:

@app.post("/api/estimator/predict")
def estimator_predict(vehicle: dict):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor  = open_cursor(connection)
        make    = vehicle.get("make")
        model   = vehicle.get("model")
        year    = vehicle.get("year")
        mileage = int(vehicle.get("mileage") or 80000)

        if not make or not model or not year:
            raise HTTPException(status_code=422, detail="make, model, and year are required")

        # sql query section - market stats:
        cursor.execute("""
            SELECT
                AVG(price)  AS avg_price,
                COUNT(*)    AS sample_count,
                MIN(price)  AS min_price,
                MAX(price)  AS max_price
            FROM vehicles
            WHERE make = %s AND model = %s AND year = %s AND price IS NOT NULL
        """, (make, model, year))
        base = cursor.fetchone()

        if not base or not base["avg_price"]:
            cursor.close()
            connection.close()
            return {
                "estimated_price":        None,
                "confidence_range":       None,
                "market_avg":             None,
                "dealer_avg":             None,
                "private_avg":            None,
                "regional_pricing":       {},
                "similar_vehicles_count": 0,
                "market_position":        "Insufficient data",
                "market_position_pct":    0,
                "confidence_score":       0,
                "price_trend_30d":        None,
                "price_trend_12m":        None,
                "message":                f"Not enough listings found for {make} {model} {year}."
            }

        market_avg   = float(base["avg_price"])
        sample_count = base["sample_count"]

        # sql query section - dealer vs private avg:
        cursor.execute("""
            SELECT vd.seller_type, AVG(v.price) AS avg_price, COUNT(*) AS count
            FROM vehicles v
            JOIN vehicle_details vd ON v.vehicle_id = vd.vehicle_id
            WHERE v.make = %s AND v.model = %s AND v.year = %s
              AND v.price IS NOT NULL AND vd.seller_type IS NOT NULL
            GROUP BY vd.seller_type
        """, (make, model, year))
        seller_rows = cursor.fetchall()

        dealer_avg  = None
        private_avg = None
        for row in seller_rows:
            st = (row["seller_type"] or "").lower()
            if "dealer" in st or "agent" in st:
                dealer_avg  = round(float(row["avg_price"]), 2)
            elif "private" in st:
                private_avg = round(float(row["avg_price"]), 2)

        if dealer_avg  is None: dealer_avg  = round(market_avg * 1.06, 2)
        if private_avg is None: private_avg = round(market_avg * 0.96, 2)

        # sql query section - regional pricing:
        cursor.execute("""
            SELECT s.province, AVG(v.price) AS avg_price, COUNT(*) AS count
            FROM vehicles v
            JOIN sellers s ON v.vehicle_id = s.vehicle_id
            WHERE v.make = %s AND v.model = %s AND v.year = %s
              AND v.price IS NOT NULL
              AND s.province IN ('Gauteng', 'Western Cape', 'KwaZulu-Natal')
            GROUP BY s.province
        """, (make, model, year))
        regional_rows = cursor.fetchall()

        regional_pricing = {}
        for row in regional_rows:
            regional_pricing[row["province"]] = round(float(row["avg_price"]), 2)

        if "Gauteng"       not in regional_pricing: regional_pricing["Gauteng"]       = round(market_avg * 1.04, 2)
        if "Western Cape"  not in regional_pricing: regional_pricing["Western Cape"]  = round(market_avg * 0.97, 2)
        if "KwaZulu-Natal" not in regional_pricing: regional_pricing["KwaZulu-Natal"] = round(market_avg * 1.01, 2)

        # sql query section - 30 day trend:
        cursor.execute("""
            SELECT AVG(price) AS avg_recent FROM vehicles
            WHERE make = %s AND model = %s AND price IS NOT NULL
              AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, (make, model))
        recent_30 = cursor.fetchone()

        cursor.execute("""
            SELECT AVG(price) AS avg_prior FROM vehicles
            WHERE make = %s AND model = %s AND price IS NOT NULL
              AND created_at BETWEEN DATE_SUB(NOW(), INTERVAL 60 DAY)
                                 AND DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, (make, model))
        prior_30 = cursor.fetchone()

        # sql query section - 12 month trend:
        cursor.execute("""
            SELECT AVG(price) AS avg_12m_ago FROM vehicles
            WHERE make = %s AND model = %s AND price IS NOT NULL
              AND created_at BETWEEN DATE_SUB(NOW(), INTERVAL 13 MONTH)
                                 AND DATE_SUB(NOW(), INTERVAL 12 MONTH)
        """, (make, model))
        prior_12m = cursor.fetchone()

        cursor.close()
        connection.close()

        mileage_adjust = (80000 - mileage) * 0.50
        estimated      = round(market_avg + mileage_adjust, 2)
        estimated      = max(estimated, 20000)
        margin         = 0.10 if sample_count >= 20 else 0.20

        position_pct = round(((estimated - market_avg) / market_avg) * 100, 1)
        if position_pct > 0:
            position_label = f"{abs(position_pct)}% above market average"
        elif position_pct < 0:
            position_label = f"{abs(position_pct)}% below market average"
        else:
            position_label = "At market average"

        price_trend_30d = None
        price_trend_12m = None

        if (recent_30 and recent_30["avg_recent"]
                and prior_30 and prior_30["avg_prior"]
                and float(prior_30["avg_prior"]) > 0):
            price_trend_30d = round(
                ((float(recent_30["avg_recent"]) - float(prior_30["avg_prior"])) / float(prior_30["avg_prior"])) * 100, 1
            )

        if (recent_30 and recent_30["avg_recent"]
                and prior_12m and prior_12m["avg_12m_ago"]
                and float(prior_12m["avg_12m_ago"]) > 0):
            price_trend_12m = round(
                ((float(recent_30["avg_recent"]) - float(prior_12m["avg_12m_ago"])) / float(prior_12m["avg_12m_ago"])) * 100, 1
            )

        return {
            "make":                   make,
            "model":                  model,
            "year":                   year,
            "estimated_price":        estimated,
            "confidence_range":       {"min": round(estimated * (1 - margin), 2), "max": round(estimated * (1 + margin), 2)},
            "market_avg":             round(market_avg, 2),
            "dealer_avg":             dealer_avg,
            "private_avg":            private_avg,
            "regional_pricing":       regional_pricing,
            "similar_vehicles_count": sample_count,
            "market_position":        position_label,
            "market_position_pct":    position_pct,
            "confidence_score":       round(min(sample_count / 50, 1.0), 2),
            "price_trend_30d":        price_trend_30d,
            "price_trend_12m":        price_trend_12m,
            "weekly_demand":          max(1, round(sample_count / 52))
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/estimator/similar-vehicles")
def estimator_similar_vehicles(
    make:            str,
    model:           str,
    year:            int,
    mileage:         int,
    estimated_price: Optional[float] = None
):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor       = open_cursor(connection)
        mileage_low  = int(mileage * 0.8)
        mileage_high = int(mileage * 1.2)

        if estimated_price:
            order_clause = "ORDER BY ABS(v.price - %s)"
            extra_param  = [estimated_price]
        else:
            order_clause = "ORDER BY v.created_at DESC"
            extra_param  = []

        # sql query section:
        cursor.execute(f"""
            SELECT
                v.vehicle_id, v.make, v.model, v.variant, v.year,
                v.price, v.mileage, v.transmission, v.fuel_type,
                v.body_type, v.colour, v.website_url,
                vi.main_image,
                s.province,
                ml.deal_label, ml.deal_pct, ml.predicted_price
            FROM vehicles v
            LEFT JOIN (
                SELECT vehicle_id, ANY_VALUE(COALESCE(main_image, image_url)) AS main_image
                FROM vehicle_images WHERE is_primary = 1 GROUP BY vehicle_id
            ) vi ON v.vehicle_id = vi.vehicle_id
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            LEFT JOIN ml_fair_value_scores ml ON v.vehicle_id = ml.vehicle_id
            WHERE v.make    = %s
              AND v.model   = %s
              AND v.year    BETWEEN %s AND %s
              AND v.mileage BETWEEN %s AND %s
              AND v.price   IS NOT NULL
            {order_clause}
            LIMIT 10
        """, [make, model, year - 2, year + 2, mileage_low, mileage_high] + extra_param)

        vehicles = cursor.fetchall()
        cursor.close()
        connection.close()

        for v in vehicles:
            v["price"]           = float(v["price"])           if v["price"]           else None
            v["deal_pct"]        = float(v["deal_pct"])        if v["deal_pct"]        is not None else None
            v["predicted_price"] = int(v["predicted_price"])   if v["predicted_price"] is not None else None

        return {"similar_vehicles": vehicles, "count": len(vehicles)}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/estimator/price-distribution/{make}/{model}")
def estimator_price_distribution(make: str, model: str):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section:
        cursor.execute("""
            SELECT price FROM vehicles
            WHERE make = %s AND model = %s AND price IS NOT NULL
            ORDER BY price
        """, (make, model))
        rows = cursor.fetchall()
        cursor.close()
        connection.close()

        if not rows:
            raise HTTPException(status_code=404, detail=f"No pricing data found for {make} {model}")

        prices      = [float(r["price"]) for r in rows]
        bucket_size = 50_000
        buckets     = {}

        for p in prices:
            b = int(p // bucket_size) * bucket_size
            buckets[b] = buckets.get(b, 0) + 1

        total_px = len(prices)
        price_buckets = [
            {
                "label": f"R {b//1000}K – R {(b+bucket_size)//1000}K",
                "min":   b,
                "max":   b + bucket_size,
                "count": cnt,
                "pct":   round(cnt / total_px * 100, 1)
            }
            for b, cnt in sorted(buckets.items())
        ]

        return {
            "make":          make,
            "model":         model,
            "sample_count":  len(prices),
            "min_price":     round(min(prices), 2),
            "max_price":     round(max(prices), 2),
            "avg_price":     round(sum(prices) / len(prices), 2),
            "percentiles": {
                "p25": round(float(np.percentile(prices, 25)), 2),
                "p50": round(float(np.percentile(prices, 50)), 2),
                "p75": round(float(np.percentile(prices, 75)), 2),
                "p90": round(float(np.percentile(prices, 90)), 2),
            },
            "price_buckets": price_buckets,
            "price_sample":  prices[::max(1, len(prices) // 200)]
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/estimator/years/{make}/{model}")
def estimator_years_for_model(make: str, model: str):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT DISTINCT year FROM vehicles
            WHERE make = %s AND model = %s AND year IS NOT NULL
            ORDER BY year DESC
        """, (make, model))
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"make": make, "model": model, "years": [r["year"] for r in rows]}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# section 5: ML fair value endpoints — all read from ml_fair_value_scores table:

@app.get("/api/ml/status")
def ml_status():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section:
        cursor.execute("""
            SELECT
                COUNT(*)                             AS total_scored,
                SUM(deal_label = 'Underpriced')      AS underpriced,
                SUM(deal_label = 'Fair Value')        AS fair_value,
                SUM(deal_label = 'Overpriced')       AS overpriced,
                ROUND(AVG(confidence_pct), 1)        AS avg_confidence,
                MAX(scored_at)                       AS last_scored
            FROM ml_fair_value_scores
        """)
        stats = cursor.fetchone()
        cursor.close()
        connection.close()

        if stats.get("last_scored"):
            stats["last_scored"] = str(stats["last_scored"])

        return {
            "model_version":  "2.1",
            "scores_in_db":   stats["total_scored"],
            "distribution": {
                "underpriced": int(stats["underpriced"] or 0),
                "fair_value":  int(stats["fair_value"]  or 0),
                "overpriced":  int(stats["overpriced"]  or 0),
            },
            "avg_confidence": stats["avg_confidence"],
            "last_scored":    stats["last_scored"],
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/vehicle/{vehicle_id}/score")
def ml_vehicle_score(vehicle_id: int):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        # sql query section:
        cursor.execute("""
            SELECT
                ml.vehicle_id, ml.predicted_price, ml.listed_price,
                ml.deal_gap, ml.deal_pct, ml.deal_label,
                ml.confidence_pct, ml.scored_at,
                v.make, v.model, v.variant, v.year, v.mileage
            FROM ml_fair_value_scores ml
            LEFT JOIN vehicles v ON ml.vehicle_id = v.vehicle_id
            WHERE ml.vehicle_id = %s
            LIMIT 1
        """, (vehicle_id,))
        row = cursor.fetchone()
        cursor.close()
        connection.close()

        if not row:
            raise HTTPException(status_code=404, detail=f"No ML score found for vehicle_id={vehicle_id}.")

        row["deal_pct"]       = float(row["deal_pct"])       if row["deal_pct"]       is not None else None
        row["confidence_pct"] = float(row["confidence_pct"]) if row["confidence_pct"] is not None else None
        row["scored_at"]      = str(row["scored_at"])        if row["scored_at"]       is not None else None

        return row

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/deals")
def ml_deals(
    deal_label: Optional[str] = "Underpriced",
    make:       Optional[str] = None,
    province:   Optional[str] = None,
    max_price:  Optional[int] = None,
    limit:      int = 24,
    page:       int = 1
):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        where  = "WHERE ml.deal_label = %s"
        params = [deal_label]

        if make:
            where += " AND v.make = %s";       params.append(make)
        if province:
            where += " AND s.province = %s";   params.append(province)
        if max_price is not None:
            where += " AND v.price <= %s";     params.append(max_price)

        offset = (page - 1) * limit

        # sql query section - count:
        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM ml_fair_value_scores ml
            JOIN vehicles v ON ml.vehicle_id = v.vehicle_id
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            {where}
        """, params)
        total = cursor.fetchone()["total"]

        # sql query section - listings sorted by best deal:
        cursor.execute(f"""
            SELECT
                v.vehicle_id, v.make, v.model, v.variant, v.year,
                v.price, v.mileage, v.fuel_type, v.transmission,
                v.body_type, v.colour, v.website_url,
                s.province, s.seller_name,
                vi.main_image,
                ml.predicted_price, ml.deal_gap, ml.deal_pct,
                ml.deal_label, ml.confidence_pct
            FROM ml_fair_value_scores ml
            JOIN vehicles v ON ml.vehicle_id = v.vehicle_id
            LEFT JOIN sellers s ON v.vehicle_id = s.vehicle_id
            LEFT JOIN (
                SELECT vehicle_id, ANY_VALUE(COALESCE(main_image, image_url)) AS main_image
                FROM vehicle_images WHERE is_primary = 1 GROUP BY vehicle_id
            ) vi ON v.vehicle_id = vi.vehicle_id
            {where}
            ORDER BY ml.deal_pct DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cursor.fetchall()
        cursor.close()
        connection.close()

        for r in rows:
            r["price"]           = float(r["price"])           if r["price"]           else None
            r["deal_pct"]        = float(r["deal_pct"])        if r["deal_pct"]        is not None else None
            r["predicted_price"] = int(r["predicted_price"])   if r["predicted_price"] is not None else None
            r["deal_gap"]        = int(r["deal_gap"])          if r["deal_gap"]        is not None else None
            r["confidence_pct"]  = float(r["confidence_pct"])  if r["confidence_pct"]  is not None else None

        return {
            "deal_label":  deal_label,
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": (total + limit - 1) // limit,
            "listings":    rows
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# section 6: dashboard filter helper:

def _dashboard_filter(make=None, province=None, days=None,
                      need_price=True, skip_days=False, table_alias='v'):
    ta     = table_alias
    joins  = []
    where  = []
    params = []

    if province:
        joins.append(f"JOIN sellers s ON {ta}.vehicle_id = s.vehicle_id")
        where.append("s.province = %s")
        params.append(province)
    if need_price:
        where.append(f"{ta}.price IS NOT NULL")
    if make:
        where.append(f"{ta}.make = %s")
        params.append(make)
    if days and not skip_days:
        where.append(f"{ta}.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)")
        params.append(days)

    join_str  = " ".join(joins)
    where_str = (" WHERE " + " AND ".join(where)) if where else ""
    return join_str, where_str, params


# section 7: market dashboard endpoints:

@app.get("/api/dashboard/summary")
def dashboard_summary(make: str = None, province: str = None, days: int = None):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)

        j, w, p = _dashboard_filter(make=make, province=province, days=days, need_price=False)
        # sql query section:
        cursor.execute(f"SELECT COUNT(DISTINCT v.vehicle_id) AS total FROM vehicles v {j}{w}", p)
        total = cursor.fetchone()["total"]

        j, w, p = _dashboard_filter(make=make, province=province, days=days, skip_days=True)
        month_cond = ("AND" if w else "WHERE") + " v.created_at >= DATE_SUB(NOW(), INTERVAL 1 MONTH)"
        cursor.execute(f"SELECT AVG(v.price) AS avg_price FROM vehicles v {j}{w} {month_cond}", p)
        avg_this_month = cursor.fetchone()["avg_price"]

        j, w, p = _dashboard_filter(make=make, province=province, days=days, skip_days=True)
        prev_cond = ("AND" if w else "WHERE") + " v.created_at BETWEEN DATE_SUB(NOW(), INTERVAL 2 MONTH) AND DATE_SUB(NOW(), INTERVAL 1 MONTH)"
        cursor.execute(f"SELECT AVG(v.price) AS avg_price FROM vehicles v {j}{w} {prev_cond}", p)
        avg_prev_month = cursor.fetchone()["avg_price"]

        if make:
            j, w, p = _dashboard_filter(make=make, province=province, days=days, need_price=False)
            cursor.execute(f"SELECT COUNT(DISTINCT v.vehicle_id) AS cnt FROM vehicles v {j}{w}", p)
            make_cnt        = cursor.fetchone()["cnt"]
            top_make        = {"make": make, "count": make_cnt}
            total_with_make = make_cnt
        else:
            j, w, p    = _dashboard_filter(province=province, days=days, need_price=False)
            make_where = ("AND" if w else "WHERE") + " v.make IS NOT NULL"
            cursor.execute(
                f"SELECT v.make, COUNT(DISTINCT v.vehicle_id) AS count FROM vehicles v {j}{w} {make_where} GROUP BY v.make ORDER BY count DESC LIMIT 1", p
            )
            top_make = cursor.fetchone()
            cursor.execute(f"SELECT COUNT(DISTINCT v.vehicle_id) AS total FROM vehicles v {j}{w} {make_where}", p)
            total_with_make = cursor.fetchone()["total"]

        j, w, p   = _dashboard_filter(make=make, province=province, days=days, need_price=False, skip_days=True)
        week_cond = ("AND" if w else "WHERE") + " v.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        cursor.execute(f"SELECT COUNT(DISTINCT v.vehicle_id) AS new_this_week FROM vehicles v {j}{w} {week_cond}", p)
        new_week = cursor.fetchone()["new_this_week"]

        if province:
            j2, w2, p2 = _dashboard_filter(make=make, province=province, days=days, need_price=False)
            cursor.execute(f"SELECT COUNT(DISTINCT v.vehicle_id) AS cnt FROM vehicles v {j2}{w2}", p2)
            top_prov = {"province": province, "count": cursor.fetchone()["cnt"]}
        else:
            prov_where  = ["s.province IS NOT NULL"]
            prov_params = []
            if make:
                prov_where.append("v.make = %s"); prov_params.append(make)
            if days:
                prov_where.append("v.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"); prov_params.append(days)
            cursor.execute(
                f"""SELECT s.province, COUNT(DISTINCT v.vehicle_id) AS count
                    FROM vehicles v JOIN sellers s ON v.vehicle_id = s.vehicle_id
                    WHERE {" AND ".join(prov_where)}
                    GROUP BY s.province ORDER BY count DESC LIMIT 1""",
                prov_params
            )
            top_prov = cursor.fetchone()

        j, w, p = _dashboard_filter(make=make, province=province, days=days)
        cursor.execute(f"SELECT v.price FROM vehicles v {j}{w} ORDER BY v.price", p)
        all_prices   = [float(r["price"]) for r in cursor.fetchall()]
        median_price = all_prices[len(all_prices) // 2] if all_prices else 0

        # sql query section - ML deal distribution for dashboard KPI tile:
        cursor.execute("""
            SELECT
                SUM(deal_label = 'Underpriced') AS underpriced,
                SUM(deal_label = 'Overpriced')  AS overpriced,
                COUNT(*)                         AS total_scored
            FROM ml_fair_value_scores
        """)
        ml_stats = cursor.fetchone()

        cursor.close()
        connection.close()

        price_change_pct = None
        if avg_this_month and avg_prev_month and float(avg_prev_month) > 0:
            price_change_pct = round(
                ((float(avg_this_month) - float(avg_prev_month)) / float(avg_prev_month)) * 100, 1
            )

        top_make_share = None
        if top_make and total_with_make and not make:
            top_make_share = round((top_make["count"] / total_with_make) * 100, 1)

        return {
            "total_listings":       total,
            "avg_price_month":      round(float(avg_this_month), 2) if avg_this_month else 0,
            "median_price":         round(median_price, 2),
            "price_change_pct":     price_change_pct,
            "most_popular_make":    top_make["make"]  if top_make else None,
            "popular_make_count":   top_make["count"] if top_make else 0,
            "popular_make_share":   top_make_share,
            "new_this_week":        new_week,
            "top_province":         top_prov["province"] if top_prov else None,
            "top_province_count":   top_prov["count"]    if top_prov else 0,
            "ml_underpriced_count": int(ml_stats["underpriced"] or 0),
            "ml_overpriced_count":  int(ml_stats["overpriced"]  or 0),
            "ml_total_scored":      int(ml_stats["total_scored"] or 0),
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/price-trends")
def dashboard_price_trends():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT
                DATE_FORMAT(created_at, '%%Y-%%m') AS month,
                AVG(price)                          AS avg_price,
                COUNT(*)                            AS count
            FROM vehicles
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
              AND price IS NOT NULL
            GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
            ORDER BY month ASC
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        return {
            "months":     [r["month"] for r in rows],
            "avg_prices": [round(float(r["avg_price"]), 2) for r in rows],
            "counts":     [r["count"] for r in rows]
        }
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/price-by-make")
def dashboard_price_by_make():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT make, AVG(price) AS avg_price, MIN(price) AS min_price,
                   MAX(price) AS max_price, COUNT(*) AS count
            FROM vehicles
            WHERE make IS NOT NULL AND price IS NOT NULL
            GROUP BY make HAVING count >= 50
            ORDER BY count DESC LIMIT 15
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        for r in rows:
            r["avg_price"] = round(float(r["avg_price"]), 2)
            r["min_price"] = float(r["min_price"])
            r["max_price"] = float(r["max_price"])
        return {"brands": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/provincial-analysis")
def dashboard_provincial_analysis(make: str = None, province: str = None, days: int = None):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor      = open_cursor(connection)
        where_parts = ["s.province IS NOT NULL", "v.price IS NOT NULL"]
        params_base = []

        if make:
            where_parts.append("v.make = %s");     params_base.append(make)
        if province:
            where_parts.append("s.province = %s"); params_base.append(province)
        if days:
            where_parts.append("v.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"); params_base.append(days)

        where_sql = " AND ".join(where_parts)

        # sql query section:
        cursor.execute(f"""
            SELECT s.province,
                   AVG(v.price)                   AS avg_price,
                   COUNT(DISTINCT v.vehicle_id)   AS count,
                   MIN(v.price)                   AS min_price,
                   MAX(v.price)                   AS max_price
            FROM vehicles v JOIN sellers s ON v.vehicle_id = s.vehicle_id
            WHERE {where_sql}
            GROUP BY s.province ORDER BY count DESC
        """, params_base)
        rows = cursor.fetchall()

        top_where  = ["s.province IS NOT NULL", "v.make IS NOT NULL"]
        params_top = []
        if make:
            top_where.append("v.make = %s");     params_top.append(make)
        if province:
            top_where.append("s.province = %s"); params_top.append(province)
        if days:
            top_where.append("v.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"); params_top.append(days)

        cursor.execute(f"""
            SELECT s.province, v.make, COUNT(DISTINCT v.vehicle_id) AS cnt
            FROM vehicles v JOIN sellers s ON v.vehicle_id = s.vehicle_id
            WHERE {" AND ".join(top_where)}
            GROUP BY s.province, v.make
        """, params_top)
        make_rows = cursor.fetchall()
        cursor.close()
        connection.close()

        prov_make_count = {}
        prov_make_map   = {}
        for mr in make_rows:
            pname = mr["province"]
            if pname not in prov_make_count or mr["cnt"] > prov_make_count[pname]:
                prov_make_count[pname] = mr["cnt"]
                prov_make_map[pname]   = mr["make"]

        for r in rows:
            r["avg_price"] = round(float(r["avg_price"]), 2)
            r["min_price"] = float(r["min_price"])
            r["max_price"] = float(r["max_price"])
            r["top_make"]  = prov_make_map.get(r["province"], "N/A")

        return {"provinces": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/mileage-vs-price")
def dashboard_mileage_vs_price():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT mileage, price, make, model, year
            FROM vehicles
            WHERE mileage IS NOT NULL AND price IS NOT NULL
              AND mileage < 300000 AND price < 2000000
            ORDER BY RAND() LIMIT 500
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        for r in rows:
            r["price"] = float(r["price"])
        return {"data_points": rows, "count": len(rows)}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/transmission-comparison")
def dashboard_transmission_comparison():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT transmission, AVG(price) AS avg_price, COUNT(*) AS count
            FROM vehicles
            WHERE transmission IN ('Automatic', 'Manual') AND price IS NOT NULL
            GROUP BY transmission
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        for r in rows:
            r["avg_price"] = round(float(r["avg_price"]), 2)
        return {"transmission_data": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/top-models")
def dashboard_top_models():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT CONCAT(make, ' ', model) AS full_name, make, model,
                   COUNT(*) AS count, AVG(price) AS avg_price
            FROM vehicles
            WHERE make IS NOT NULL AND model IS NOT NULL
            GROUP BY make, model ORDER BY count DESC LIMIT 10
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        for r in rows:
            r["avg_price"] = round(float(r["avg_price"]), 2) if r["avg_price"] else 0
        return {"top_models": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/price-ranges")
def dashboard_price_ranges(make: str = None, province: str = None, days: int = None, seller_type: str = None):
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor      = open_cursor(connection)
        where_parts = ["v.price IS NOT NULL"]
        params      = []
        joins       = ""

        if province:
            joins += " JOIN sellers s ON v.vehicle_id = s.vehicle_id"
            where_parts.append("s.province = %s"); params.append(province)
        if seller_type:
            joins += " LEFT JOIN vehicle_details vd ON v.vehicle_id = vd.vehicle_id"
            where_parts.append("LOWER(COALESCE(vd.seller_type,'')) LIKE %s"); params.append(f"%{seller_type.lower()}%")
        if make:
            where_parts.append("v.make = %s"); params.append(make)
        if days:
            where_parts.append("v.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"); params.append(days)

        # sql query section:
        cursor.execute(f"""
            SELECT
                CASE
                    WHEN v.price < 100000                  THEN 'Under R100k'
                    WHEN v.price BETWEEN 100000 AND 199999 THEN 'R100k – R200k'
                    WHEN v.price BETWEEN 200000 AND 299999 THEN 'R200k – R300k'
                    WHEN v.price BETWEEN 300000 AND 499999 THEN 'R300k – R500k'
                    WHEN v.price BETWEEN 500000 AND 999999 THEN 'R500k – R1M'
                    ELSE 'Above R1M'
                END AS price_range,
                COUNT(DISTINCT v.vehicle_id) AS count
            FROM vehicles v {joins}
            WHERE {" AND ".join(where_parts)}
            GROUP BY price_range ORDER BY MIN(v.price)
        """, params)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        return {"price_ranges": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/median-prices")
def dashboard_median_prices():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT make, price FROM vehicles
            WHERE make IS NOT NULL AND price IS NOT NULL
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()

        df = pd.DataFrame(rows)
        df["price"] = df["price"].astype(float)
        median_df = (
            df.groupby("make")["price"]
              .agg(["median", "count"])
              .reset_index()
              .rename(columns={"median": "median_price", "count": "listing_count"})
        )
        median_df = median_df[median_df["listing_count"] >= 20]
        median_df = median_df.sort_values("median_price", ascending=False).head(20)
        return {"median_prices": median_df.to_dict(orient="records")}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/fuel-efficiency-trends")
def dashboard_fuel_efficiency_trends():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT v.year, AVG(vd.fuel_consumption_avg) AS avg_consumption, COUNT(*) AS count
            FROM vehicles v
            JOIN vehicle_details vd ON v.vehicle_id = vd.vehicle_id
            WHERE vd.fuel_consumption_avg IS NOT NULL AND v.year IS NOT NULL
            GROUP BY v.year ORDER BY v.year DESC LIMIT 20
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()
        for r in rows:
            r["avg_consumption"] = round(float(r["avg_consumption"]), 2) if r["avg_consumption"] else None
        return {"fuel_trends": rows}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/dealer-vs-private")
def dashboard_dealer_vs_private():
    connection = get_database_connection()
    if not connection:
        raise HTTPException(status_code=500, detail="Database connection failed")
    try:
        cursor = open_cursor(connection)
        # sql query section:
        cursor.execute("""
            SELECT vd.seller_type, AVG(v.price) AS avg_price,
                   COUNT(*) AS count, MIN(v.price) AS min_price, MAX(v.price) AS max_price
            FROM vehicles v
            JOIN vehicle_details vd ON v.vehicle_id = vd.vehicle_id
            JOIN sellers s          ON v.vehicle_id = s.vehicle_id
            WHERE v.price IS NOT NULL AND vd.seller_type IS NOT NULL
            GROUP BY vd.seller_type
        """)
        rows = cursor.fetchall()
        cursor.close()
        connection.close()

        for r in rows:
            r["avg_price"] = round(float(r["avg_price"]), 2)
            r["min_price"] = float(r["min_price"])
            r["max_price"] = float(r["max_price"])

        dealer_avg  = None
        private_avg = None
        for r in rows:
            st = (r.get("seller_type") or "").lower()
            if "dealer" in st or "agent" in st:
                dealer_avg  = r["avg_price"]
            elif "private" in st:
                private_avg = r["avg_price"]

        dealer_premium_pct = None
        if dealer_avg and private_avg and private_avg > 0:
            dealer_premium_pct = round(((dealer_avg - private_avg) / private_avg) * 100, 1)

        return {"seller_comparison": rows, "dealer_premium_pct": dealer_premium_pct}
    except Exception as e:
        traceback.print_exc()
        try:
            connection.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))