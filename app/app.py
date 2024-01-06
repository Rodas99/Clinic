#!/usr/bin/python3
import os
from logging.config import dictConfig
from datetime import datetime, timedelta

import psycopg
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from psycopg.rows import namedtuple_row

# postgres://{user}:{password}@{hostname}:{port}/{database-name}
DATABASE_URL = "postgres://clinic:clinic@postgres/clinic"

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s:%(lineno)s - %(funcName)20s(): %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

app = Flask(__name__)
app.config.from_prefixed_env()
log = app.logger


def is_decimal(s):
    """Returns True if string is a parseable float number."""
    try:
        float(s)
        return True
    except ValueError:
        return False
    

@app.route("/ping", methods=("GET",))
def ping():
    log.debug("ping!")
    return jsonify({"message": "pong!", "status": "success"})


#dashboard page
@app.route("/", methods=("GET",))
@app.route("/dashboard", methods=("GET",))
def dashboard():
    
    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            dashboard = cur.execute("""
                SELECT *
                FROM facts_consultations
            """,
            {},
            ).fetchall()
            log.debug(f"Found {cur.rowcount} rows.")
    return render_template("dashboard.html", dashboard=dashboard)

#clients page
@app.route("/clients", methods=("GET",))
def clients():
    """Show all the clients, most recent first."""

    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            clients = cur.execute(
                """
                SELECT * FROM client;
                """,
                {},
            ).fetchall()
            log.debug(f"Found {cur.rowcount} rows.")
    return render_template("clients/clients.html", clients=clients)

#search_clients page
@app.route("/search_clients", methods=("GET", "POST"))
def search_clients():
    if request.method == "POST":
        search_query = request.form["search_query"]

        with psycopg.connect(conninfo=DATABASE_URL) as conn:
            with conn.cursor(row_factory=namedtuple_row) as cur:
                clients = cur.execute(
                    """
                    SELECT * FROM client 
                    WHERE 
                    name ILIKE %(search_query)s 
                    OR street ILIKE %(search_query)s 
                    OR city ILIKE %(search_query)s 
                    OR zip ILIKE %(search_query)s;
                    """,
                    {"search_query": f"%{search_query}%"},
                ).fetchall()

                log.debug(f"Found {cur.rowcount} rows matching the search query.")
        return render_template("clients/search_results.html", clients=clients)
    return render_template("clients/search_clients.html")

#check_availability page
@app.route("/check_availability", methods=("GET", "POST"))
def check_availability():
    if request.method == "POST":
        appointment_date = request.form["appointment_date"].strip()
        appointment_time = request.form["appointment_time"].strip()

        appointment_datetime_str = f"{appointment_date} {appointment_time}"

        try:
            appointment_datetime = datetime.strptime(appointment_datetime_str, "%Y-%m-%d %H:%M")
            appointment_end = appointment_datetime + timedelta(hours=1)

            with psycopg.connect(conninfo=DATABASE_URL) as conn:
                with conn.cursor(row_factory=namedtuple_row) as cur:
                    doctors = cur.execute(
                    """
                    SELECT e.name, d.specialization, d.email
                    FROM doctor d
                    JOIN employee e ON d.vat = e.vat
                    WHERE 
                    d.vat NOT IN (
                        SELECT DISTINCT VAT_doctor 
                        FROM appointment 
                        WHERE 
                        date_timestamp BETWEEN %(appointment_datetime)s AND %(appointment_end)s
                    );
                    """,
                        {"appointment_datetime": appointment_datetime, "appointment_end": appointment_end},
                    ).fetchall()

                    log.debug(f"Found {cur.rowcount} available doctors for the appointment.")
            return render_template("appointments/available_doctors.html", doctors=doctors)
        except ValueError as e:
            error_message = f"Error processing date/time: {e}"
            return render_template("appointments/check_availability.html", error_message=error_message)

    return render_template("appointments/check_availability.html")

#add_client page
@app.route("/add_client", methods=("GET", "POST"))
def add_client_form():
    if request.method == "POST":
        # Retrieve form data
        name = request.form["name"]
        vat = request.form["vat"]
        birth_date = request.form["birth_date"]
        street = request.form["street"]
        city = request.form["city"]
        zip_code = request.form["zip"]
        gender = request.form["gender"]

        # Add the client to the database
        with psycopg.connect(conninfo=DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO client (VAT, name, birth_date, street, city, zip, gender) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (vat, name, birth_date, street, city, zip_code, gender),
                )
                conn.commit()

        # Redirect to the clients page after adding the client
        return redirect(url_for("clients"))

    return render_template("clients/add_client_form.html")

#delete_client
@app.route("/delete_client/<int:vat>", methods=["POST"])
def delete_client(vat):
    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM client WHERE VAT = %s", (vat,))
            conn.commit()

    # After deleting, redirect to the clients page
    return redirect(url_for("clients"))

#client_appointments page
@app.route("/client_appointments/<int:vat>", methods=["GET"])
def client_appointments(vat):
    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            appointments = cur.execute(
                """
                SELECT a.*, e.name AS doctor_name
                FROM appointment a
                JOIN employee e ON a.VAT_doctor = e.VAT
                WHERE a.VAT_client = %s
                ORDER BY a.date_timestamp DESC;
                """,
                (vat,),
            ).fetchall()

    return render_template("appointments/client_appointments.html", appointments=appointments)

#appointment_details page
@app.route("/appointment_details/<int:doctor_vat>/<string:date_timestamp>", methods=["GET"])
def appointment_details(doctor_vat, date_timestamp):
    parsed_date_timestamp = datetime.strptime(date_timestamp, "%Y-%m-%d %H:%M:%S")

    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            # Retrieve appointment details
            cur.execute(
                """
                SELECT c.date_timestamp AS c_date_timestamp, 
                       c.SOAP_S, c.SOAP_O, c.SOAP_A, c.SOAP_P
                FROM consultation c
                WHERE c.VAT_doctor = %s AND c.date_timestamp = %s;
                """,
                (doctor_vat, parsed_date_timestamp),
            )
            appointment_info = cur.fetchall()

            # Retrieve prescription details
            cur.execute(
                """
                SELECT name, lab, dosage, description
                FROM prescription
                WHERE VAT_doctor = %s AND date_timestamp = %s;
                """,
                (doctor_vat, parsed_date_timestamp),
            )
            prescription_info = cur.fetchall()

    return render_template("appointments/appointment_details.html", appointment_info=appointment_info, prescription_info=prescription_info, doctor_vat=doctor_vat)

#update_appointment page
@app.route("/update_appointment/<int:doctor_vat>/<string:date_timestamp>", methods=["GET", "POST"])
def update_appointment(doctor_vat, date_timestamp):
    if request.method == "POST":
# Retrieve updated form data and update the database
        soap_s = request.form.get("soap_s")
        soap_o = request.form.get("soap_o")
        soap_a = request.form.get("soap_a")
        soap_p = request.form.get("soap_p")
        prescription_name = request.form.get("name")
        prescription_lab = request.form.get("lab")
        dosage = request.form.get("dosage")
        prescription_desc = request.form.get("description")

        with psycopg.connect(conninfo=DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE consultation
                    SET SOAP_S = %s, SOAP_O = %s, SOAP_A = %s, SOAP_P = %s
                    WHERE VAT_doctor = %s AND date_timestamp = %s;
                    """,
                    (soap_s, soap_o, soap_a, soap_p, doctor_vat, date_timestamp),
                )

                cur.execute(
                    """
                    UPDATE prescription
                    SET name = %s, lab = %s, dosage = %s, description = %s
                    WHERE VAT_doctor = %s AND date_timestamp = %s;
                    """,
                    (prescription_name, prescription_lab, dosage, prescription_desc, doctor_vat, date_timestamp),
                )

        # Redirect to the appointment details page after updating
        return redirect(url_for("appointment_details", doctor_vat=doctor_vat, date_timestamp=date_timestamp))


    # Fetch existing appointment and prescription details
    with psycopg.connect(conninfo=DATABASE_URL) as conn:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            cur.execute(
                """
                SELECT c.date_timestamp AS c_date_timestamp, 
                       c.SOAP_S, c.SOAP_O, c.SOAP_A, c.SOAP_P
                FROM consultation c
                WHERE c.VAT_doctor = %s AND c.date_timestamp = %s;
                """,
                (doctor_vat, date_timestamp),
            )
            appointment_info = cur.fetchall()

            cur.execute(
                """
                SELECT name, lab, dosage, description
                FROM prescription
                WHERE VAT_doctor = %s AND date_timestamp = %s;
                """,
                (doctor_vat, date_timestamp),
            )
            prescription_info = cur.fetchall()

    return render_template(
        "appointments/update_appointment.html",
        appointment_info=appointment_info,
        prescription_info=prescription_info,
        doctor_vat=doctor_vat,
        date_timestamp=date_timestamp,
    )
if __name__ == "__main__":
    app.run()
