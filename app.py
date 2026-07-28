"""
app.py
------
Pakwatan Security ERP Portal — Phase 2 entry point.

Phase 1 gave us schema + a bare connectivity check. Phase 2 adds:
  - Supabase-backed login/logout + role-based session management
  - A protected dashboard shell (sidebar, metric cards, recent activity)
  - Universal global search across Guards, Clients, and Incidents

Future phases will add the full CRUD modules (guards, attendance,
financials, weapons) as additional blueprints on this same shell.
"""

from flask import Flask, session, redirect, url_for, render_template

from config import SECRET_KEY, FLASK_DEBUG, FLASK_HOST, FLASK_PORT
from blueprints.auth import auth_bp, init_session_lifetime
from blueprints.dashboard import dashboard_bp
from blueprints.search import search_bp
from blueprints.guards import guards_bp
from blueprints.clients import clients_bp
from blueprints.deployments import deployments_bp
from blueprints.payroll import payroll_bp
from blueprints.finance import finance_bp
from blueprints.weapons import weapons_bp
from blueprints.complaints import complaints_bp
from blueprints.roles import roles_bp


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # In production behind HTTPS, also set SESSION_COOKIE_SECURE = True.
    app.config["SESSION_COOKIE_SECURE"] = not FLASK_DEBUG

    init_session_lifetime(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(guards_bp, url_prefix="/guards")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(deployments_bp, url_prefix="/deployments")
    app.register_blueprint(payroll_bp, url_prefix="/payroll")
    app.register_blueprint(finance_bp, url_prefix="/finance")
    app.register_blueprint(weapons_bp)
    app.register_blueprint(complaints_bp, url_prefix="/complaints")
    app.register_blueprint(roles_bp, url_prefix="/roles")




    @app.route("/")
    def root():
        if session.get("user"):
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_current_user():
        # Makes `current_user` available in every template without passing
        # it explicitly from each route.
        return {"current_user": session.get("user")}

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403,
                                message="You don't have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404,
                                message="That page doesn't exist."), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=FLASK_PORT)
