import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import (
    Flask, render_template, abort, request,
    flash, redirect, url_for, session
)
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message

# ---- KONFIGURÁCIÓ BETÖLTÉSE ----
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "alapertelmezett-titok")

# ---- ADATBÁZIS BEÁLLÍTÁSA ----
database_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---- LEVELEZÉS BEÁLLÍTÁSA ----
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

mail = Mail(app)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# ---- ADATMODELL ----
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

# ---- STATIKUS ADATOK (Szobák) ----
rooms_data = [
    {"id": 1, "name": "Kétágyas szoba", "description": "Kényelmes szoba 2 fő részére.", "image": "images/francia1.jpg"},
    {"id": 2, "name": "Családi szoba", "description": "Tágas szoba 4 főnek.", "image": "images/ketagyas2.jpg"},
]

# ---- SEGÉDFÜGGVÉNY A SZABAD HELYEKHEZ ----
def get_available_dates(room_name, days=30):
    today = datetime.now().date()
    next_period = [today + timedelta(days=i) for i in range(days)]
    
    # Csak a jóváhagyott foglalásokat vesszük figyelembe foglaltságként
    bookings = Booking.query.filter_by(room_name=room_name, status="approved").all()
    
    booked_dates = set()
    for b in bookings:
        try:
            start = datetime.strptime(b.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(b.end_date, '%Y-%m-%d').date()
            curr = start
            while curr < end:
                booked_dates.add(curr)
                curr += timedelta(days=1)
        except Exception as e:
            print(f"Dátum hiba: {e}")
            continue
            
    return [d.strftime('%m.%d.') for d in next_period if d not in booked_dates]

# ---- PUBLIKUS ÚTVONALAK ----
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/rooms")
def rooms():
    rooms_with_availability = []
    for room in rooms_data:
        room_copy = room.copy()
        # Az első 7 szabad napot mutatjuk a kártyán
        room_copy['available_preview'] = get_available_dates(room['name'], 30)[:7]
        rooms_with_availability.append(room_copy)
    return render_template("rooms.html", rooms=rooms_with_availability)

@app.route("/rooms/<int:room_id>", methods=["GET", "POST"])
def room_detail(room_id):
    room = next((r for r in rooms_data if r["id"] == room_id), None)
    if not room:
        abort(404)

    bookings = Booking.query.filter_by(room_name=room["name"]).all()
    disabled_ranges = [{"from": b.start_date, "to": b.end_date} for b in bookings if b.status == "approved"]
    
    # 14 napnyi szabad hely a részletes nézethez
    available_days = get_available_dates(room['name'], 30)[:14]

    if request.method == "POST":
        guest_name = request.form["name"]
        guest_email = request.form["email"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        guests = request.form.get("guests", "1")

        if start_date >= end_date:
            flash("Hibás dátumtartomány.", "danger")
            return redirect(url_for("room_detail", room_id=room_id))

        booking = Booking(
            room_name=room["name"], 
            name=guest_name, 
            email=guest_email, 
            start_date=start_date, 
            end_date=end_date
        )
        db.session.add(booking)
        db.session.commit()

        # Értesítők küldése
     # Értesítők küldése
        try:
            # Visszaigazolás a vendégnek (HTML sablonnal)
            guest_msg = Message("Foglalási igény - Füzesi Vendégház", recipients=[guest_email])
            
            # Itt a módosítás: .body helyett .html és render_template
            guest_msg.html = render_template("email_confirmation.html", 
                                           name=guest_name,
                                           room_name=room['name'],
                                           start_date=start_date, 
                                           end_date=end_date)
            
            mail.send(guest_msg)
            # Értesítés az adminnak
            if ADMIN_EMAIL:
                admin_msg = Message("ÚJ FOGLALÁS", recipients=[ADMIN_EMAIL])
                admin_msg.body = f"Új igény érkezett!\n(https://fuzesivhaz.hu/admin/login) \nVendég: {guest_name}\nSzoba: {room['name']}\nIdő: {start_date} - {end_date}"
                mail.send(admin_msg)
        except Exception as e:
            print(f"Email hiba: {e}")

        flash("Foglalás elküldve! Kérjük, várja meg e-mailes visszaigazolásunkat.", "success")
        return redirect(url_for("room_detail", room_id=room_id))

    return render_template("room_detail.html", 
                           room=room, 
                           disabled_ranges=disabled_ranges, 
                           available_days=available_days)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        if ADMIN_EMAIL:
            try:
                msg = Message(f"Üzenet: {name}", recipients=[ADMIN_EMAIL])
                msg.body = f"Feladó: {name} <{email}>\n\n{message}"
                mail.send(msg)
            except Exception as e:
                print(e)
        flash('Üzenet elküldve!', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

# ---- ADMINISZTRÁCIÓ ----
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USERNAME and request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Hibás adatok.", "danger")
    return render_template("admin_login.html")

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin"): 
        return redirect(url_for("admin_login"))
    return render_template("admin_bookings.html", bookings=Booking.query.order_by(Booking.id.desc()).all())

@app.route("/admin/approve/<int:booking_id>")
def admin_approve(booking_id):
    if not session.get("admin"): 
        return redirect(url_for("admin_login"))
    booking = Booking.query.get_or_404(booking_id)
    booking.status = "approved"
    db.session.commit()
    
    try:
        msg = Message("Foglalás JÓVÁHAGYVA - Füzesi Vendégház", recipients=[booking.email])
        msg.body = f"Kedves {booking.name}!\n\nÖrömmel értesítjük, hogy foglalását elfogadtuk a {booking.start_date} - {booking.end_date} időszakra.\n\nVárjuk szeretettel!"
        mail.send(msg)
        flash("Jóváhagyva és email elküldve.", "success")
    except Exception as e: 
        print(e)
        flash("Jóváhagyva, de az email nem ment el.", "warning")
    
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete/<int:booking_id>")
def admin_delete(booking_id):
    if not session.get("admin"): 
        return redirect(url_for("admin_login"))
    booking = Booking.query.get_or_404(booking_id)
    
    try:
        msg = Message("Tájékoztatás foglalásról - Füzesi Vendégház", recipients=[booking.email])
        msg.body = f"Kedves {booking.name}!\n\nSajnáljuk, de a kért időpontot ({booking.start_date} - {booking.end_date}) jelenleg nem tudjuk visszaigazolni.\n\nMegértését köszönjük!"
        mail.send(msg)
    except Exception as e: 
        print(e)

    db.session.delete(booking)
    db.session.commit()
    flash("Törölve és elutasító email elküldve.", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    app.run(debug=True)