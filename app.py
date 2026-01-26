import os
from dotenv import load_dotenv
from flask import (
    Flask, render_template, abort, request,
    flash, redirect, url_for, session
)
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash

# ---- ENV ----
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# ---- DATABASE ----
database_url = os.getenv("DATABASE_URL")

if not database_url:
    database_url = "sqlite:///local.db"

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---- MODEL ----
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_name = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="pending")

with app.app_context():
    db.create_all()

# ---- MAIL ----
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

mail = Mail(app)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")

# ---- ROOMS ----
rooms_data = [
    {
        "id": 1,
        "name": "Kétágyas szoba",
        "description": "Kényelmes szoba 2 fő részére.",
        "image": "images/room1.jpg",
    },
    {
        "id": 2,
        "name": "Családi szoba",
        "description": "Tágas szoba 4 főnek.",
        "image": "images/room2.jpg",
    },
]

# ---- PUBLIC ROUTES ----
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/rooms")
def rooms():
    return render_template("rooms.html", rooms=rooms_data)

@app.route("/rooms/<int:room_id>", methods=["GET", "POST"])
def room_detail(room_id):
    room = next((r for r in rooms_data if r["id"] == room_id), None)
    if not room:
        abort(404)

    bookings = Booking.query.filter_by(room_name=room["name"]).all()

    disabled_ranges = [
        {"from": b.start_date, "to": b.end_date}
        for b in bookings if b.status == "approved"
    ]

    if request.method == "POST":
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]

        if start_date >= end_date:
            flash("Hibás dátumtartomány.", "danger")
            return redirect(url_for("room_detail", room_id=room_id))

        conflict = Booking.query.filter(
            Booking.room_name == room["name"],
            Booking.end_date > start_date,
            Booking.start_date < end_date,
            Booking.status == "approved",
        ).first()

        if conflict:
            flash("Ez az időszak már foglalt.", "danger")
            return redirect(url_for("room_detail", room_id=room_id))

        booking = Booking(
            room_name=room["name"],
            name=request.form["name"],
            email=request.form["email"],
            start_date=start_date,
            end_date=end_date,
        )

        db.session.add(booking)
        db.session.commit()

        if ADMIN_EMAIL:
            msg = Message(
                subject="Új foglalás",
                recipients=[ADMIN_EMAIL],
                body=f"{room['name']} – {booking.name}"
            )
            mail.send(msg)

        flash("Foglalás elküldve.", "success")
        return redirect(url_for("room_detail", room_id=room_id))

    return render_template(
        "room_detail.html",
        room=room,
        disabled_ranges=disabled_ranges
    )


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')

        if not name or not email or not message:
            flash('Kérlek tölts ki minden mezőt.', 'danger')
            return redirect(url_for('contact'))

        # Send email to admin if configured
        if ADMIN_EMAIL:
            try:
                msg = Message(subject=f"Kapcsolat: {name}",
                              recipients=[ADMIN_EMAIL],
                              body=f"Név: {name}\nEmail: {email}\n\n{message}")
                mail.send(msg)
            except Exception:
                # Don't raise; show friendly message
                flash('Hiba történt az üzenet küldése közben, de az üzenet elmentve helyben.', 'warning')
                return redirect(url_for('contact'))

        flash('Köszönjük az üzenetedet — hamarosan válaszolunk.', 'success')
        return redirect(url_for('contact'))

    return render_template('contact.html')

@app.route('/accessibility')
def accessibility():
    return render_template('accessibility.html')

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Itt most sima szöveges jelszóval hasonlítunk össze
        if username == os.getenv("ADMIN_USERNAME") and password == os.getenv("ADMIN_PASSWORD"):
            session["admin"] = True
            flash("Sikeres bejelentkezés.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Hibás felhasználónév vagy jelszó.", "danger")

    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Kijelentkeztél.", "info")
    return redirect(url_for("admin_login"))

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    bookings = Booking.query.order_by(Booking.id.desc()).all()
    return render_template("admin_bookings.html", bookings=bookings)

@app.route("/admin/approve/<int:booking_id>")
def admin_approve(booking_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    booking = Booking.query.get_or_404(booking_id)
    booking.status = "approved"
    db.session.commit()

    flash("Foglalás jóváhagyva.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete/<int:booking_id>")
def admin_delete(booking_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()

    flash("Foglalás törölve.", "info")
    return redirect(url_for("admin_dashboard"))

# ---- MAIN ----
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
