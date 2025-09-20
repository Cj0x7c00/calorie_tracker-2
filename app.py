import os
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, flash
from flask_sqlalchemy import SQLAlchemy

def create_app():
    app = Flask(__name__)
    # Config
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///tracker.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        # Ensure we have a single Settings row
        if Settings.query.first() is None:
            s = Settings(cal_target=2000, protein_target=150, carb_target=200, fat_target=70, weight_goal=None)
            db.session.add(s)
            db.session.commit()

    register_routes(app)
    return app

db = SQLAlchemy()

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    calories = db.Column(db.Integer, nullable=True)
    protein = db.Column(db.Float, nullable=True)  # grams
    carbs = db.Column(db.Float, nullable=True)    # grams
    fat = db.Column(db.Float, nullable=True)      # grams
    meal = db.Column(db.String(40), nullable=True)  # e.g., Breakfast/Lunch/Dinner/Snack
    quantity = db.Column(db.Float, nullable=True)   # multiplier
    when = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def computed_calories(self):
        # If calories not provided, compute from macros (4/4/9 rule)
        if self.calories is not None:
            return self.calories
        cals = 0
        if self.protein:
            cals += 4 * self.protein
        if self.carbs:
            cals += 4 * self.carbs
        if self.fat:
            cals += 9 * self.fat
        # Multiply by quantity if given
        q = self.quantity if self.quantity else 1
        return int(round(cals * q))

    def macros(self):
        q = self.quantity if self.quantity else 1
        return {
            'protein': (self.protein or 0) * q,
            'carbs': (self.carbs or 0) * q,
            'fat': (self.fat or 0) * q,
        }

class WeightLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    when = db.Column(db.Date, nullable=False, index=True)
    weight = db.Column(db.Float, nullable=False)  # in chosen units (assume lbs)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cal_target = db.Column(db.Integer, nullable=False, default=2000)
    protein_target = db.Column(db.Float, nullable=False, default=150)
    carb_target = db.Column(db.Float, nullable=False, default=200)
    fat_target = db.Column(db.Float, nullable=False, default=70)
    weight_goal = db.Column(db.Float, nullable=True)  # optional target weight

def day_bounds(d: date):
    return d, d

def summary_for_date(d: date):
    entries = Entry.query.filter_by(when=d).order_by(Entry.created_at.desc()).all()
    totals = {
        'calories': 0,
        'protein': 0.0,
        'carbs': 0.0,
        'fat': 0.0,
    }
    for e in entries:
        totals['calories'] += e.computed_calories()
        m = e.macros()
        totals['protein'] += m['protein']
        totals['carbs'] += m['carbs']
        totals['fat'] += m['fat']
    settings = Settings.query.first()
    return entries, totals, settings

def week_series(end_date: date, days: int = 7):
    xs = []
    cal_series = []
    protein_series = []
    carb_series = []
    fat_series = []
    for i in range(days-1, -1, -1):
        d = end_date - timedelta(days=i)
        _, totals, _ = summary_for_date(d)
        xs.append(d.isoformat())
        cal_series.append(totals['calories'])
        protein_series.append(round(totals['protein'], 1))
        carb_series.append(round(totals['carbs'], 1))
        fat_series.append(round(totals['fat'], 1))
    return xs, cal_series, protein_series, carb_series, fat_series

def register_routes(app: Flask):
    @app.route("/")
    def index():
        return redirect(url_for('today'))

    @app.route("/today")
    def today():
        d = date.today()
        entries, totals, settings = summary_for_date(d)
        xs, cal_s, p_s, c_s, f_s = week_series(d, 7)
        wlogs = WeightLog.query.order_by(WeightLog.when.asc()).all()
        return render_template(
            "day.html",
            day=d,
            prev_day=(d - timedelta(days=1)),
            next_day=(d + timedelta(days=1)),
            entries=entries,
            totals=totals,
            settings=settings,
            week_labels=xs,
            week_cals=cal_s,
            week_p=p_s,
            week_c=c_s,
            week_f=f_s,
            weights=wlogs
        )

    @app.route("/day/<datestr>")
    def day_view(datestr):
        try:
            d = datetime.strptime(datestr, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format. Use YYYY-MM-DD.")
            return redirect(url_for('today'))
        entries, totals, settings = summary_for_date(d)
        xs, cal_s, p_s, c_s, f_s = week_series(d, 7)
        wlogs = WeightLog.query.order_by(WeightLog.when.asc()).all()
        return render_template(
            "day.html",
            day=d,
            prev_day=(d - timedelta(days=1)),
            next_day=(d + timedelta(days=1)),
            entries=entries,
            totals=totals,
            settings=settings,
            week_labels=xs,
            week_cals=cal_s,
            week_p=p_s,
            week_c=c_s,
            week_f=f_s,
            weights=wlogs
        )

    @app.post("/add_entry")
    def add_entry():
        name = request.form.get("name", "").strip() or "Food"
        meal = request.form.get("meal", "").strip() or None
        when_str = request.form.get("when", date.today().isoformat())
        try:
            when = datetime.strptime(when_str, "%Y-%m-%d").date()
        except ValueError:
            when = date.today()

        def parse_float(field):
            val = request.form.get(field)
            if val is None or val == "":
                return None
            try:
                return float(val)
            except ValueError:
                return None

        def parse_int(field):
            val = request.form.get(field)
            if val is None or val == "":
                return None
            try:
                return int(float(val))
            except ValueError:
                return None

        e = Entry(
            name=name,
            calories=parse_int("calories"),
            protein=parse_float("protein"),
            carbs=parse_float("carbs"),
            fat=parse_float("fat"),
            meal=meal,
            quantity=parse_float("quantity"),
            when=when
        )
        db.session.add(e)
        db.session.commit()
        return redirect(url_for('day_view', datestr=when.isoformat()))

    @app.post("/delete_entry/<int:entry_id>")
    def delete_entry(entry_id):
        e = Entry.query.get_or_404(entry_id)
        d = e.when
        db.session.delete(e)
        db.session.commit()
        return redirect(url_for('day_view', datestr=d.isoformat()))

    @app.route("/weights", methods=["GET", "POST"])
    def weights():
        if request.method == "POST":
            when_str = request.form.get("when", date.today().isoformat())
            try:
                when = datetime.strptime(when_str, "%Y-%m-%d").date()
            except ValueError:
                when = date.today()
            try:
                weight = float(request.form.get("weight"))
            except (TypeError, ValueError):
                flash("Please enter a valid weight.")
                return redirect(url_for('weights'))
            wl = WeightLog(when=when, weight=weight)
            db.session.add(wl)
            db.session.commit()
            return redirect(url_for('weights'))

        wlogs = WeightLog.query.order_by(WeightLog.when.asc()).all()
        return render_template("weights.html", weights=wlogs)

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        s = Settings.query.first()
        if request.method == "POST":
            try:
                s.cal_target = int(request.form.get("cal_target", s.cal_target))
                s.protein_target = float(request.form.get("protein_target", s.protein_target))
                s.carb_target = float(request.form.get("carb_target", s.carb_target))
                s.fat_target = float(request.form.get("fat_target", s.fat_target))
                wg = request.form.get("weight_goal", "")
                s.weight_goal = float(wg) if wg else None
            except ValueError:
                flash("Invalid settings values.")
                return redirect(url_for('settings'))
            db.session.commit()
            flash("Settings saved.")
            return redirect(url_for('today'))
        return render_template("settings.html", s=s)

    @app.get("/export.csv")
    def export_csv():
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "when", "name", "meal", "quantity", "calories", "protein", "carbs", "fat"])
        for e in Entry.query.order_by(Entry.when.asc(), Entry.id.asc()).all():
            writer.writerow([
                e.id,
                e.when.isoformat(),
                e.name,
                e.meal or "",
                e.quantity or 1,
                e.computed_calories(),
                e.macros()['protein'],
                e.macros()['carbs'],
                e.macros()['fat'],
            ])
        buf.seek(0)
        return send_file(
            io.BytesIO(buf.getvalue().encode('utf-8')),
            mimetype="text/csv",
            as_attachment=True,
            download_name="entries.csv"
        )

    @app.get("/api/weekly_summary")
    def api_weekly_summary():
        end = date.today()
        labels, cal_s, p_s, c_s, f_s = week_series(end, 7)
        return jsonify({
            "labels": labels,
            "calories": cal_s,
            "protein": p_s,
            "carbs": c_s,
            "fat": f_s
        })

if __name__ == "__main__":
    # For local dev: `python app.py`
    app = create_app()
    app.run(debug=True)
